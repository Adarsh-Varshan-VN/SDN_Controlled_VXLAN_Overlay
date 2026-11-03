# SDN-Controlled VXLAN Overlay Fabric

A production-grade, software-defined virtual extensible LAN (VXLAN) overlay network architecture implemented using **Ryu OpenFlow 1.3** (Control Plane), **Open vSwitch** (Data Plane), and **Mininet** (Topology Emulation). 

This project addresses the architectural inefficiencies of traditional static full-mesh overlays and BGP EVPN (such as O(N^2) idle tunnel memory bloat and (N-1)^2 Head-End Ingress Replication broadcast storms) by implementing **On-Demand VTEP Provisioning**, **Edge Proxy-ARP Suppression**, and **Multi-Tenant VNI Isolation**.

---

## Team Members
* **Adarsh Varshan V N** — 25BCE1055
* **C S Akshay Khanna Reddy** — 25BCE1113

---

## Key Features
* **On-Demand Tunneling:** Hypervisors maintain zero pre-built tunnels at initialization; VXLAN VTEP ports (UDP Port 4789) are provisioned via OVSDB strictly when two virtual machines need to communicate.
* **Edge Proxy-ARP Suppression:** Intercepts ARP broadcasts at the edge switch using OpenFlow Priority 20 rules and responds directly via controller telemetry, eliminating underlay broadcast floods.
* **Multi-Tenant VNI Isolation:** Enforces strict logical network boundaries, instantly blocking unauthorized cross-VNI packet and ARP transmissions at the control plane.
* **Real-Time Telemetry & UI:** Includes a Streamlit monitoring dashboard (`dashboard.py`) tracking active tunnels, KPI metrics, architectural scaling comparisons, and live OpenFlow table dumps.

---

## Repository Structure
```text
sdn-overlay-project/
├── controller/
│   └── app.py            # Ryu SDN Controller (Proxy-ARP, VNI Isolation, On-Demand VTEPs)
├── scripts/
│   ├── topology.py       # Mininet 3-Switch, 4-VM Topology & L3 Underlay Router
│   └── benchmark.py      # OVSDB Scalability Query & Mathematical Comparison Utility
├── dashboard.py          # Streamlit Real-Time Monitoring & Telemetry Dashboard
└── README.md             # Project Documentation
```

## Prerequisites & Environment Setup

### 1. System Requirements
* **Operating System:** Ubuntu Linux (running natively or via Oracle VM VirtualBox).
* **Python Version:** Python 3.12 or higher.

### 2. Core Software Packages
Ensure the following networking utilities and emulators are installed on your Ubuntu environment:
* **Mininet:** Network emulator for creating virtual topologies.
* **Open vSwitch (OVS):** Production-quality multilayer software switch supporting OpenFlow.

You can install them via the system package manager:
```bash
sudo apt-get update
sudo apt-get install -y mininet openvswitch-switch
```

## Execution Guide

To run the SDN fabric, control plane, and telemetry dashboard, open **three separate terminal windows** inside your project directory (`~/Desktop/sdn-overlay-project`) and execute the following commands sequentially:

### Terminal 1: Start the Ryu SDN Controller
Activate your virtual environment and start the Ryu manager to listen for OpenFlow connections:
```bash
source venv/bin/activate
ryu-manager controller/app.py
```

### Terminal 2: Start the Mininet Topology
Run the topology script with root privileges to instantiate the switches, the L3 underlay router, and the virtual machines:
```bash
source venv/bin/activate
sudo python3 scripts/topology.py
```

### Terminal 3: Launch the Streamlit Dashboard
Start the real-time monitoring web application:
```bash
source venv/bin/activate
streamlit run dashboard.py
```
