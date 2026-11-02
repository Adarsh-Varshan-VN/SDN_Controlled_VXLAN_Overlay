import json
import subprocess
import time
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, arp, ipv4, ether_types

TELEMETRY_FILE = "/tmp/sdn_telemetry.json"


class SDNOverlayController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(SDNOverlayController, self).__init__(*args, **kwargs)
        self.datapaths = {}
        self.active_tunnels = {}  # key: "sX<->sY", value: dict metadata

        # Centralized SDN Controller Directory Database:
        # Maps Overlay IP -> {mac, dpid, switch, host_port, vtep_ip, vni}
        self.vm_directory = {
            "10.0.0.1": {
                "name": "h1",
                "mac": "00:00:00:00:00:01",
                "dpid": 1,
                "switch": "s1",
                "host_port": 1,
                "vtep_ip": "192.168.1.10",
                "vni": 100,
            },
            "10.0.0.2": {
                "name": "h2",
                "mac": "00:00:00:00:00:02",
                "dpid": 2,
                "switch": "s2",
                "host_port": 1,
                "vtep_ip": "192.168.2.20",
                "vni": 100,
            },
            "10.0.0.3": {
                "name": "h3",
                "mac": "00:00:00:00:00:03",
                "dpid": 3,
                "switch": "s3",
                "host_port": 1,
                "vtep_ip": "192.168.3.30",
                "vni": 100,
            },
            "10.0.0.4": {
                "name": "h4",
                "mac": "00:00:00:00:00:04",
                "dpid": 3,
                "switch": "s3",
                "host_port": 2,
                "vtep_ip": "192.168.3.30",
                "vni": 200,  # Isolated Tenant Network (VNI 200)
            },
        }

        self.metrics = {
            "arp_suppressed": 0,
            "tunnels_created": 0,
            "flows_installed": 0,
            "vni_violations_blocked": 0,
            "events": [],
        }
        self._save_telemetry("Controller initialized with 4 VMs across 3 Hypervisors.")

    def _log_event(self, tag, message):
        timestamp = time.strftime("%H:%M:%S")
        entry = f"[{timestamp}] [{tag}] {message}"
        self.logger.info(entry)
        self.metrics["events"].insert(0, entry)
        self.metrics["events"] = self.metrics["events"][:25]
        self._save_telemetry()

    def _save_telemetry(self, init_msg=None):
        if init_msg:
            timestamp = time.strftime("%H:%M:%S")
            self.metrics["events"].insert(0, f"[{timestamp}] [INIT] {init_msg}")
        payload = {
            "metrics": self.metrics,
            "active_tunnels": self.active_tunnels,
            "vm_directory": self.vm_directory,
            "connected_switches": list(self.datapaths.keys()),
        }
        try:
            with open(TELEMETRY_FILE, "w") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            self.logger.error("Telemetry write error: %s", e)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        dpid = datapath.id
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        self.datapaths[dpid] = datapath

        # 1. Install Priority 0 Table-Miss Rule
        match_miss = parser.OFPMatch()
        actions_miss = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match_miss, actions_miss)

        # 2. Install Priority 20 Edge ARP Interception Rule (True ARP Suppression)
        match_arp = parser.OFPMatch(eth_type=ether_types.ETH_TYPE_ARP)
        actions_arp = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 20, match_arp, actions_arp)

        self._log_event(
            "SWITCH-HANDSHAKE",
            f"Switch s{dpid} (DPID={dpid}) connected. Installed Priority 20 Edge ARP Suppression rule.",
        )

    def add_flow(self, datapath, priority, match, actions, idle_timeout=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            idle_timeout=idle_timeout,
            match=match,
            instructions=inst,
        )
        datapath.send_msg(mod)

    def _create_ovs_vxlan_port(self, switch_name, port_name, local_ip, remote_ip, vni, ofport_req):
        """Dynamically provisions a globally unique VXLAN VTEP port on Open vSwitch via OVSDB CLI."""
        cmd = [
            "sudo", "ovs-vsctl", "--may-exist", "add-port", switch_name, port_name,
            "--", "set", "interface", port_name,
            "type=vxlan",
            f"options:local_ip={local_ip}",
            f"options:remote_ip={remote_ip}",
            f"options:key={vni}",
            "options:dst_port=4789",
            f"ofport_request={ofport_req}",
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            self.logger.error("OVSDB error creating %s on %s: %s", port_name, switch_name, res.stderr.strip())
            raise subprocess.CalledProcessError(res.returncode, cmd, output=res.stdout, stderr=res.stderr)

    def ensure_on_demand_tunnel(self, src_vm, dst_vm):
        """Creates bidirectional VXLAN tunnels on-demand ONLY when two switches need to communicate."""
        dpid_a, dpid_b = sorted([src_vm["dpid"], dst_vm["dpid"]])
        tunnel_key = f"s{dpid_a}<->s{dpid_b}"

        # Deterministic OpenFlow port numbers: on sX, tunnel to sY is port (10 + Y)
        port_on_src = 10 + dst_vm["dpid"]
        port_on_dst = 10 + src_vm["dpid"]

        if tunnel_key not in self.active_tunnels:
            vni = src_vm["vni"]
            # Globally unique port names across all OVS bridges (e.g., vxlan-s1-s3 and vxlan-s3-s1)
            port_name_src = f"vxlan-s{src_vm['dpid']}-s{dst_vm['dpid']}"
            port_name_dst = f"vxlan-s{dst_vm['dpid']}-s{src_vm['dpid']}"

            self._create_ovs_vxlan_port(
                src_vm["switch"], port_name_src,
                src_vm["vtep_ip"], dst_vm["vtep_ip"], vni, port_on_src
            )
            self._create_ovs_vxlan_port(
                dst_vm["switch"], port_name_dst,
                dst_vm["vtep_ip"], src_vm["vtep_ip"], vni, port_on_dst
            )

            self.active_tunnels[tunnel_key] = {
                "switches": [src_vm["switch"], dst_vm["switch"]],
                "ports": [port_name_src, port_name_dst],
                "vteps": [src_vm["vtep_ip"], dst_vm["vtep_ip"]],
                "vni": vni,
                "created_at": time.strftime("%H:%M:%S"),
            }
            self.metrics["tunnels_created"] += 1
            self._log_event(
                "ON-DEMAND-VTEP",
                f"Created VXLAN tunnel {tunnel_key} ({port_name_src} <-> {port_name_dst}, VNI={vni})",
            )

        return port_on_src, port_on_dst

    def install_reactive_unicast_flows(self, src_vm, dst_vm):
        """Installs Priority 10 unicast forwarding flows on both switches."""
        if src_vm["dpid"] == dst_vm["dpid"]:
            dp = self.datapaths.get(src_vm["dpid"])
            if dp:
                parser = dp.ofproto_parser
                self.add_flow(
                    dp, 10,
                    parser.OFPMatch(eth_dst=dst_vm["mac"]),
                    [parser.OFPActionOutput(dst_vm["host_port"])]
                )
                self.add_flow(
                    dp, 10,
                    parser.OFPMatch(eth_dst=src_vm["mac"]),
                    [parser.OFPActionOutput(src_vm["host_port"])]
                )
            return

        port_on_src, port_on_dst = self.ensure_on_demand_tunnel(src_vm, dst_vm)

        dp_src = self.datapaths.get(src_vm["dpid"])
        dp_dst = self.datapaths.get(dst_vm["dpid"])
        if not dp_src or not dp_dst:
            return

        parser_src = dp_src.ofproto_parser
        parser_dst = dp_dst.ofproto_parser

        # On Source Switch (s_src):
        self.add_flow(
            dp_src, 10,
            parser_src.OFPMatch(eth_dst=dst_vm["mac"]),
            [parser_src.OFPActionOutput(port_on_src)]
        )
        self.add_flow(
            dp_src, 10,
            parser_src.OFPMatch(eth_dst=src_vm["mac"]),
            [parser_src.OFPActionOutput(src_vm["host_port"])]
        )

        # On Destination Switch (s_dst):
        self.add_flow(
            dp_dst, 10,
            parser_dst.OFPMatch(eth_dst=dst_vm["mac"]),
            [parser_dst.OFPActionOutput(dst_vm["host_port"])]
        )
        self.add_flow(
            dp_dst, 10,
            parser_dst.OFPMatch(eth_dst=src_vm["mac"]),
            [parser_dst.OFPActionOutput(port_on_dst)]
        )

        self.metrics["flows_installed"] += 4
        self._log_event(
            "FLOW-MOD",
            f"Installed Priority 10 unicast flows on {src_vm['switch']} and {dst_vm['switch']} for {src_vm['name']} <-> {dst_vm['name']}",
        )

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        dpid = datapath.id
        in_port = msg.match["in_port"]

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if not eth or eth.ethertype in (ether_types.ETH_TYPE_LLDP, ether_types.ETH_TYPE_IPV6):
            return
        if eth.dst.startswith("33:33") or eth.dst.startswith("01:00:5e"):
            return

        arp_pkt = pkt.get_protocol(arp.arp)
        if arp_pkt:
            # GUARD CLAUSE: Strictly process 10.0.0.0/24 overlay ARPs; ignore 192.168.x.x underlay ARPs
            if not arp_pkt.src_ip.startswith("10.0.0.") or not arp_pkt.dst_ip.startswith("10.0.0."):
                return

            if arp_pkt.opcode == arp.ARP_REQUEST:
                src_vm = self.vm_directory.get(arp_pkt.src_ip)
                dst_vm = self.vm_directory.get(arp_pkt.dst_ip)

                if not src_vm or not dst_vm:
                    return

                # Multi-Tenant VNI Isolation Check
                if src_vm["vni"] != dst_vm["vni"]:
                    self.metrics["vni_violations_blocked"] += 1
                    self._log_event(
                        "VNI-ISOLATION",
                        f"BLOCKED ARP from {src_vm['name']} ({arp_pkt.src_ip}, VNI={src_vm['vni']}) to {dst_vm['name']} ({arp_pkt.dst_ip}, VNI={dst_vm['vni']})",
                    )
                    return

                # 1. Dynamically provision VXLAN tunnel & install Priority 10 data flows
                self.install_reactive_unicast_flows(src_vm, dst_vm)

                # 2. Suppress ARP broadcast & reply directly to requesting VM via PacketOut
                self.send_arp_reply(
                    datapath=datapath,
                    src_mac=dst_vm["mac"],
                    src_ip=arp_pkt.dst_ip,
                    dst_mac=eth.src,
                    dst_ip=arp_pkt.src_ip,
                    out_port=in_port,
                )
                self.metrics["arp_suppressed"] += 1
                self._log_event(
                    "PROXY-ARP",
                    f"Suppressed broadcast on DPID={dpid}: Responded {arp_pkt.dst_ip} is-at {dst_vm['mac']} directly to {src_vm['name']} ({arp_pkt.src_ip})",
                )
                return

        # Handle table-miss IPv4 packets (if ARP was already cached on host)
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        if ip_pkt and ip_pkt.src.startswith("10.0.0.") and ip_pkt.dst.startswith("10.0.0."):
            src_vm = self.vm_directory.get(ip_pkt.src)
            dst_vm = self.vm_directory.get(ip_pkt.dst)
            if src_vm and dst_vm and src_vm["vni"] == dst_vm["vni"]:
                self.install_reactive_unicast_flows(src_vm, dst_vm)

    def send_arp_reply(self, datapath, src_mac, src_ip, dst_mac, dst_ip, out_port):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        pkt = packet.Packet()
        pkt.add_protocol(
            ethernet.ethernet(
                ethertype=ether_types.ETH_TYPE_ARP,
                dst=dst_mac,
                src=src_mac,
            )
        )
        pkt.add_protocol(
            arp.arp(
                opcode=arp.ARP_REPLY,
                src_mac=src_mac,
                src_ip=src_ip,
                dst_mac=dst_mac,
                dst_ip=dst_ip,
            )
        )
        pkt.serialize()

        actions = [parser.OFPActionOutput(out_port)]
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=ofproto.OFP_NO_BUFFER,
            in_port=ofproto.OFPP_CONTROLLER,
            actions=actions,
            data=pkt.data,
        )
        datapath.send_msg(out)
