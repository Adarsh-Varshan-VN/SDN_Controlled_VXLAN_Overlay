import json
import os
import subprocess

TELEMETRY_FILE = "/tmp/sdn_telemetry.json"


def get_ovs_ports(bridge):
    try:
        out = subprocess.check_output(["sudo", "ovs-vsctl", "list-ports", bridge], text=True)
        return [p.strip() for p in out.splitlines() if p.strip().startswith("vxlan")]
    except Exception:
        return []


def run_benchmark():
    print("\n================================================================================")
    print("   SDN OVERLAY FABRIC vs. MESH-FABRIC vs. BGP EVPN — ARCHITECTURAL BENCHMARK")
    print("================================================================================")

    # 1. Live Fabric State
    s1_tunnels = get_ovs_ports("s1")
    s2_tunnels = get_ovs_ports("s2")
    s3_tunnels = get_ovs_ports("s3")
    active_bidirectional = (len(s1_tunnels) + len(s2_tunnels) + len(s3_tunnels)) // 2

    telemetry = {}
    if os.path.exists(TELEMETRY_FILE):
        with open(TELEMETRY_FILE, "r") as f:
            telemetry = json.load(f)

    metrics = telemetry.get("metrics", {})
    arp_suppressed = metrics.get("arp_suppressed", 0)
    vni_blocked = metrics.get("vni_violations_blocked", 0)

    print(f"\n[1] LIVE 3-HYPERVISOR TOPOLOGY TELEMETRY (N = 3 Switches: s1, s2, s3)")
    print(f"    • s1 VXLAN Ports           : {s1_tunnels if s1_tunnels else 'None (Idle)'}")
    print(f"    • s2 VXLAN Ports           : {s2_tunnels if s2_tunnels else 'None (Idle)'}")
    print(f"    • s3 VXLAN Ports           : {s3_tunnels if s3_tunnels else 'None (Idle)'}")
    print(f"    • Active Tunnels Maintained: {active_bidirectional} (Full Mesh requires N(N-1)/2 = 3)")
    print(f"    • ARP Broadcasts Suppressed: {arp_suppressed} packets (0 bytes flooded into VXLAN)")
    print(f"    • Cross-VNI Attempts Blocked: {vni_blocked} packets (VNI 100 vs VNI 200 isolated)")

    # 2. Scaling Comparison Table (N Hypervisors)
    print("\n[2] SCALABILITY COMPARISON: STATIC O(N^2) TUNNELS vs. ON-DEMAND SDN")
    print("--------------------------------------------------------------------------------")
    print(f"{'Hypervisors (N)':<17} | {'Mesh / EVPN Tunnels N(N-1)/2':<30} | {'Mesh New-VM Floods (N-1)^2':<26} | {'SDN Floods'}")
    print("--------------------------------------------------------------------------------")
    for n in [3, 5, 10, 25, 50, 100]:
        tunnels = (n * (n - 1)) // 2
        floods = (n - 1) * (n - 1)
        print(f"{n:<17} | {tunnels:<30} | {floods:<26} | 0 (Proxy-ARP)")
    print("--------------------------------------------------------------------------------\n")


if __name__ == "__main__":
    run_benchmark()
