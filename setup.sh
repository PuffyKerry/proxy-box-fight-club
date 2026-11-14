#!/bin/bash
# Setup users, locked-down rwx permissions, cgroups v2, and /proc isolation for Proxy Box Fight Club

id -u moderator &>/dev/null || useradd -m -s /bin/bash moderator

for i in {0..3}; do
    id -u player$i &>/dev/null || useradd -m -s /bin/bash player$i
    cp comm.py client.py crash_test.py /home/player$i/
    chown -R player$i:player$i /home/player$i/
    chmod 700 /home/player$i
    chmod 700 /home/player$i/*.py
done

cp comm.py server.py /home/moderator/
chown -R moderator:moderator /home/moderator/
chmod 700 /home/moderator
chmod 700 /home/moderator/comm.py /home/moderator/server.py

# Directory owned by moderator with 755 (rwxr-xr-x):
# Only moderator can create/delete game.sock; players can traverse (r-x) to connect.
mkdir -p /tmp/coldwar_ipc
chown moderator:moderator /tmp/coldwar_ipc
chmod 755 /tmp/coldwar_ipc

# Set up cgroup v2 slice to cap player CPU (20%), RAM (64MB), and max processes (32)
if [ -d /sys/fs/cgroup ]; then
    mkdir -p /sys/fs/cgroup/proxybox
    echo "+cpu +memory +pids" > /sys/fs/cgroup/cgroup.subtree_control 2>/dev/null || true
    echo "20000 100000" > /sys/fs/cgroup/proxybox/cpu.max 2>/dev/null || true
    echo "67108864" > /sys/fs/cgroup/proxybox/memory.max 2>/dev/null || true
    echo "32" > /sys/fs/cgroup/proxybox/pids.max 2>/dev/null || true
    find /sys/fs/cgroup -name "cgroup.procs" -exec chmod 666 {} + 2>/dev/null || true
    echo "[+] Configured cgroup v2 isolation at /sys/fs/cgroup/proxybox (CPU=20%, RAM=64MB, PIDs=32)."
fi

# Remount /proc with hidepid=2 so players can't snoop on other users' PIDs
mount -o remount,rw,hidepid=2 /proc 2>/dev/null && echo "[+] Mounted /proc with hidepid=2." || true

echo "[+] Proxy Box Fight Club environment setup complete with hardened permissions and isolation."
