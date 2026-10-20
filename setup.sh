#!/bin/bash
# Setup users and locked-down rwx permissions for Proxy Box Fight Club

id -u moderator &>/dev/null || useradd -m -s /bin/bash moderator

for i in {0..3}; do
    id -u player$i &>/dev/null || useradd -m -s /bin/bash player$i
    cp comm.py client.py /home/player$i/
    chown -R player$i:player$i /home/player$i/
    chmod 700 /home/player$i
    chmod 700 /home/player$i/comm.py /home/player$i/client.py
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

echo "[+] Proxy Box Fight Club environment setup complete with hardened permissions."
