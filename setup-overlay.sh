#!/bin/bash
echo "Setting up persistent VXLAN overlay..."

# 1. Re-add VXLAN ports with local underlay bindings
sudo ovs-vsctl add-port s1 vxlan-s2 -- set interface vxlan-s2 type=vxlan options:remote_ip=192.168.2.20 options:local_ip=192.168.1.10 options:key=100 options:dst_port=4789
sudo ovs-vsctl add-port s2 vxlan-s1 -- set interface vxlan-s1 type=vxlan options:remote_ip=192.168.1.10 options:local_ip=192.168.2.20 options:key=100 options:dst_port=4789

# 2. Adjust MTU to prevent fragmentation
sudo ip link set dev s1 mtu 1450
sudo ip link set dev s2 mtu 1450

# ==========================================================
# OpenFlow 1.3 Forwarding Rules with In-Port Scoping
# ==========================================================
# Switch s1
sudo ovs-ofctl -O OpenFlow13 add-flow s1 "priority=20,in_port=1,arp,dl_dst=ff:ff:ff:ff:ff:ff,actions=output:3"
sudo ovs-ofctl -O OpenFlow13 add-flow s1 "priority=20,in_port=3,arp,dl_dst=ff:ff:ff:ff:ff:ff,actions=output:1"
sudo ovs-ofctl -O OpenFlow13 add-flow s1 "priority=10,dl_dst=00:00:00:00:00:02,actions=output:3"
sudo ovs-ofctl -O OpenFlow13 add-flow s1 "priority=10,dl_dst=00:00:00:00:00:01,actions=output:1"

# Switch s2
sudo ovs-ofctl -O OpenFlow13 add-flow s2 "priority=20,in_port=1,arp,dl_dst=ff:ff:ff:ff:ff:ff,actions=output:3"
sudo ovs-ofctl -O OpenFlow13 add-flow s2 "priority=20,in_port=3,arp,dl_dst=ff:ff:ff:ff:ff:ff,actions=output:1"
sudo ovs-ofctl -O OpenFlow13 add-flow s2 "priority=10,dl_dst=00:00:00:00:00:02,actions=output:1"
sudo ovs-ofctl -O OpenFlow13 add-flow s2 "priority=10,dl_dst=00:00:00:00:00:01,actions=output:3"

echo "Overlay setup complete!"
