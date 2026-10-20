#!/bin/bash
# Setup users and socket permissions for Cold War TDM

# Create moderator user if needed
id -u moderator &>/dev/null || useradd -m -s /bin/bash moderator

# Create 4 test players if they don't exist
for i in {0..3}; do
    id -u player$i &>/dev/null || useradd -m -s /bin/bash player$i
    # Distribute client.py and comm.py to each player home directory
    cp comm.py client.py /home/player$i/
    chown player$i:player$i /home/player$i/comm.py /home/player$i/client.py
    chmod 755 /home/player$i/comm.py /home/player$i/client.py
done

# Copy game files to moderator
cp comm.py server.py /home/moderator/
chown -R moderator:moderator /home/moderator/
chmod 755 /home/moderator/comm.py /home/moderator/server.py

# Setup socket directory with full permissions so all users can connect
mkdir -p /tmp/coldwar_ipc
chmod 777 /tmp/coldwar_ipc

echo "[+] Cold War TDM environment setup complete."
