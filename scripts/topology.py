import subprocess
from mininet.net import Mininet
from mininet.node import Node, OVSSwitch, RemoteController
from mininet.cli import CLI
from mininet.log import setLogLevel, info


class LinuxRouter(Node):
    """A Node with IPv4 forwarding enabled acting as the physical L3 underlay router."""
    def config(self, **params):
        super(LinuxRouter, self).config(**params)
        self.cmd("sysctl -w net.ipv4.ip_forward=1")

    def terminate(self):
        self.cmd("sysctl -w net.ipv4.ip_forward=0")
        super(LinuxRouter, self).terminate()


def configure_root_underlay():
    """Configures the L3 Underlay VTEP IPs, MTU 1450, and cross-subnet routes on s1, s2, s3."""
    underlay_configs = [
        ("s1", "192.168.1.10/24"),
        ("s2", "192.168.2.20/24"),
        ("s3", "192.168.3.30/24"),
    ]
    for br, ip_cidr in underlay_configs:
        subprocess.run(["sudo", "ip", "link", "set", "dev", br, "up"], check=False)
        subprocess.run(["sudo", "ip", "addr", "flush", "dev", br], check=False)
        subprocess.run(["sudo", "ip", "addr", "add", ip_cidr, "dev", br], check=False)
        subprocess.run(["sudo", "ip", "link", "set", "dev", br, "mtu", "1450"], check=False)

    # Ensure underlay VTEPs can route across r1 between Subnets 1, 2, and 3
    subprocess.run(["sudo", "ip", "route", "replace", "192.168.1.0/24", "dev", "s1", "src", "192.168.1.10"], check=False)
    subprocess.run(["sudo", "ip", "route", "replace", "192.168.2.0/24", "dev", "s2", "src", "192.168.2.20"], check=False)
    subprocess.run(["sudo", "ip", "route", "replace", "192.168.3.0/24", "dev", "s3", "src", "192.168.3.30"], check=False)


def run_topology():
    net = Mininet(controller=RemoteController, switch=OVSSwitch, waitConnected=True)

    info("*** Adding Ryu Remote Controller (127.0.0.1:6653)\n")
    c0 = net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6653)

    info("*** Adding L3 Underlay Router (r1)\n")
    # FIXED: Mininet() instance uses addHost() with cls=LinuxRouter
    r1 = net.addHost("r1", cls=LinuxRouter, ip="192.168.1.1/24")

    info("*** Adding 3 OVS Hypervisor Switches (s1, s2, s3) in OpenFlow13 secure mode\n")
    s1 = net.addSwitch("s1", dpid="0000000000000001", protocols="OpenFlow13", failMode="secure")
    s2 = net.addSwitch("s2", dpid="0000000000000002", protocols="OpenFlow13", failMode="secure")
    s3 = net.addSwitch("s3", dpid="0000000000000003", protocols="OpenFlow13", failMode="secure")

    info("*** Adding 4 Overlay Virtual Machine Hosts (h1, h2, h3 in VNI 100; h4 in VNI 200)\n")
    h1 = net.addHost("h1", ip="10.0.0.1/24", mac="00:00:00:00:00:01")
    h2 = net.addHost("h2", ip="10.0.0.2/24", mac="00:00:00:00:00:02")
    h3 = net.addHost("h3", ip="10.0.0.3/24", mac="00:00:00:00:00:03")
    h4 = net.addHost("h4", ip="10.0.0.4/24", mac="00:00:00:00:00:04")

    info("*** Wiring Host-to-Switch Overlay Links (Deterministic OpenFlow Ports)\n")
    net.addLink(h1, s1, port1=0, port2=1)  # s1-eth1 (OF Port 1)
    net.addLink(h2, s2, port1=0, port2=1)  # s2-eth1 (OF Port 1)
    net.addLink(h3, s3, port1=0, port2=1)  # s3-eth1 (OF Port 1) - VNI 100
    net.addLink(h4, s3, port1=0, port2=2)  # s3-eth2 (OF Port 2) - VNI 200

    info("*** Wiring Switch-to-Router Underlay Links\n")
    net.addLink(s1, r1, port1=2, port2=1, params2={"ip": "192.168.1.1/24"})
    net.addLink(s2, r1, port1=2, port2=2, params2={"ip": "192.168.2.1/24"})
    net.addLink(s3, r1, port1=3, port2=3, params2={"ip": "192.168.3.1/24"})

    info("*** Starting Network\n")
    net.build()
    c0.start()
    s1.start([c0])
    s2.start([c0])
    s3.start([c0])

    info("*** Configuring Router r1 Gateways (Subnets 1, 2, and 3)\n")
    r1.cmd("ip addr flush dev r1-eth1 && ip addr add 192.168.1.1/24 dev r1-eth1 && ip link set r1-eth1 up")
    r1.cmd("ip addr flush dev r1-eth2 && ip addr add 192.168.2.1/24 dev r1-eth2 && ip link set r1-eth2 up")
    r1.cmd("ip addr flush dev r1-eth3 && ip addr add 192.168.3.1/24 dev r1-eth3 && ip link set r1-eth3 up")

    info("*** Setting Host MTUs to 1450 (50B VXLAN Headroom)\n")
    for host in (h1, h2, h3, h4):
        host.cmd(f"ip link set dev {host.name}-eth0 mtu 1450")

    info("*** Configuring OVS Underlay VTEPs (192.168.1.10, 192.168.2.20, 192.168.3.30)\n")
    configure_root_underlay()

    info("\n======================================================================\n")
    info(" 100% SDN OVERLAY FABRIC READY (ZERO STATIC VXLAN TUNNELS PRE-BUILT)\n")
    info(" - h1 (10.0.0.1, s1, VNI 100) | h2 (10.0.0.2, s2, VNI 100)\n")
    info(" - h3 (10.0.0.3, s3, VNI 100) | h4 (10.0.0.4, s3, VNI 200 Isolated)\n")
    info("======================================================================\n")

    CLI(net)
    net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    run_topology()
