import json
import os
import subprocess
import time
import pandas as pd
import streamlit as st

TELEMETRY_FILE = "/tmp/sdn_telemetry.json"

st.set_page_config(page_title="SDN VXLAN Overlay Fabric Dashboard", layout="wide")

st.title("SDN-Controlled VXLAN Overlay Fabric — Live Control & Data Plane Dashboard")
st.caption("Real-Time Telemetry: Edge ARP Suppression, On-Demand VTEP Tunneling, Multi-Tenant VNI Isolation & Scaling Benchmarks")


def load_telemetry():
    if os.path.exists(TELEMETRY_FILE):
        try:
            with open(TELEMETRY_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"metrics": {}, "active_tunnels": {}, "vm_directory": {}, "connected_switches": []}


def get_ovs_flows(switch):
    try:
        return subprocess.check_output(
            ["sudo", "ovs-ofctl", "-O", "OpenFlow13", "dump-flows", switch],
            text=True, stderr=subprocess.DEVNULL
        )
    except Exception:
        return f"Switch {switch} not active."


data = load_telemetry()
metrics = data.get("metrics", {})
active_tunnels = data.get("active_tunnels", {})
vm_dir = data.get("vm_directory", {})

# Top KPI Row
col1, col2, col3, col4 = st.columns(4)
active_count = len(active_tunnels)
mesh_required = 3  # For N=3 switches: 3*(3-1)/2 = 3

col1.metric(
    label="Active VXLAN Tunnels (On-Demand)",
    value=f"{active_count} / {mesh_required} Max",
    delta=f"{mesh_required - active_count} Idle Tunnels Saved vs Mesh/EVPN",
)
col2.metric(
    label="ARP Broadcasts Suppressed (Proxy-ARP)",
    value=metrics.get("arp_suppressed", 0),
    delta="0 ARP Floods in Underlay",
)
col3.metric(
    label="Dynamic Priority-10 Flows Installed",
    value=metrics.get("flows_installed", 0),
    delta="Reactive OpenFlow 1.3",
)
col4.metric(
    label="Cross-VNI Packets Blocked (Isolation)",
    value=metrics.get("vni_violations_blocked", 0),
    delta="VNI 100 vs VNI 200 Enforced",
)

st.divider()

# Middle Row: Active Tunnels & VM Directory
left_col, right_col = st.columns(2)

with left_col:
    st.subheader("On-Demand VXLAN Tunnel Status (UDP Port 4789)")
    if active_tunnels:
        tunnel_rows = []
        for key, info in active_tunnels.items():
            tunnel_rows.append({
                "Tunnel Pair": key,
                "Underlay VTEPs": f"{info['vteps'][0]} ↔ {info['vteps'][1]}",
                "VNI": info["vni"],
                "Provisioned At": info["created_at"],
                "State": "ACTIVE (On-Demand)",
            })
        st.dataframe(pd.DataFrame(tunnel_rows), use_container_width=True)
    else:
        st.info("Zero VXLAN tunnels currently provisioned. Send a ping in Mininet to watch Ryu build tunnels on-demand!")

    st.subheader("Centralized SDN Controller VM Database")
    if vm_dir:
        vm_rows = [
            {
                "Host": v["name"],
                "Overlay IP": ip,
                "MAC Address": v["mac"],
                "Switch": v["switch"],
                "Underlay VTEP": v["vtep_ip"],
                "VNI": v["vni"],
            }
            for ip, v in vm_dir.items()
        ]
        st.dataframe(pd.DataFrame(vm_rows), use_container_width=True)

with right_col:
    st.subheader("Live Ryu Controller Event Stream")
    events = metrics.get("events", [])
    if events:
        st.code("\n".join(events[:12]), language="text")
    else:
        st.write("Waiting for OpenFlow events...")

st.divider()

# Architecture Comparison Charts (Mesh vs BGP EVPN vs SDN)
st.subheader("Architectural Benchmark: Mesh-Fabric vs. BGP EVPN vs. Our SDN Overlay")
chart_col1, chart_col2 = st.columns(2)

n_values = [3, 5, 10, 20, 30, 50]
with chart_col1:
    st.markdown("**1. Pre-Configured Tunnel Overhead: $N(N-1)/2$ vs. Active On-Demand Pairs**")
    df_tunnels = pd.DataFrame({
        "Hypervisors (N)": n_values,
        "Mesh-Fabric & BGP EVPN Static Tunnels N(N-1)/2": [(n * (n - 1)) // 2 for n in n_values],
        "SDN On-Demand Tunnels (Active Communicating Pairs)": [min(n - 1, max(1, active_count)) for n in n_values],
    }).set_index("Hypervisors (N)")
    st.line_chart(df_tunnels)

with chart_col2:
    st.markdown("**2. Broadcast Flooding Overhead on New VM Boot: $(N-1)^2$ vs. $0$ Floods**")
    df_floods = pd.DataFrame({
        "Hypervisors (N)": n_values,
        "Mesh-Fabric Head-End Replication Floods (N-1)^2": [(n - 1) ** 2 for n in n_values],
        "BGP EVPN Route Reflector Unicast Updates (N-1)": [n - 1 for n in n_values],
        "Our SDN Overlay (Centralized Proxy-ARP)": [0 for _ in n_values],
    }).set_index("Hypervisors (N)")
    st.line_chart(df_floods)

st.divider()

# Live OpenFlow Table Inspector
st.subheader("Live Open vSwitch OpenFlow 1.3 Forwarding Tables")
s_col1, s_col2, s_col3 = st.columns(3)
with s_col1:
    st.markdown("**Switch `s1` (`192.168.1.10`)**")
    st.code(get_ovs_flows("s1"), language="text")
with s_col2:
    st.markdown("**Switch `s2` (`192.168.2.20`)**")
    st.code(get_ovs_flows("s2"), language="text")
with s_col3:
    st.markdown("**Switch `s3` (`192.168.3.30`)**")
    st.code(get_ovs_flows("s3"), language="text")

if st.button("Refresh Live Telemetry"):
    st.rerun()
