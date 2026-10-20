# Proxy Box Fight Club (CSE 536 - Project #1)
Author: Kerry Zhuo

## Overview
Proxy Box Fight Club is a multi-user, multi-process geopolitical Team DeathMatch (TDM) social deduction game (BLUFOR vs. REDFOR). Every player runs as an isolated Linux user and process, assigned an active role:
- Arms: Eliminates a target Actor's Proxy during the War (Night) Phase.
- Peacekeeping: Shields a target Actor's Proxy from Arms offensives during the War Phase.
- Intelligence: Investigates a target Actor during the War Phase to learn their TRUE faction and role.
- Diplomatic (Infiltrator): Has no kinetic War action, but is placed inside the enemy faction's multicast radio channel and appears as a member of the enemy faction in all public reports except to Intelligence.

## Location & API of the Communications Library
- Library File Name & Location: ./comm.py (deployed to /home/moderator/comm.py and /home/player0..3/comm.py).
- Communications Primitive: Non-blocking UNIX Domain Stream Sockets (AF_UNIX, SOCK_STREAM) multiplexed via Python's selectors.DefaultSelector (Linux epoll), hardened with kernel SO_PEERCRED authentication and Constant-Rate Chaff Traffic Padding.

### comm.py Public API:
1. CommServer(socket_path="/tmp/coldwar_ipc/game.sock", enable_chaff=True)
   - on_connect_cb(cid, username, uid, pid) : Callback fired when a client connects and is verified via SO_PEERCRED.
   - on_message_cb(cid, msg_dict) : Callback fired when a newline-delimited JSON message is received.
   - on_disconnect_cb(cid, username) : Callback fired when a client disconnects.
   - send_direct(client_id, payload_dict) : 1-to-1 Primitive. Sends a JSON message to client_id and dispatches equal-length CHAFF packets to all other clients.
   - join_group(client_id, group_name) : Adds client_id to multicast group group_name.
   - leave_group(client_id, group_name) : Removes client_id from multicast group group_name.
   - send_group(group_name, payload_dict) : Multicast Primitive. Sends a JSON message to all members of group_name and dispatches CHAFF packets to non-members.
   - broadcast(payload_dict) : Broadcast Primitive. Sends a JSON message to all connected clients.
   - disconnect_client(client_id) : Cleanly unregisters and closes a client socket.
   - dump_forensics() : Returns a formatted string table of connected clients (CID, Username, UID, PID, FD, and Groups).
   - poll(timeout=0.05) : Polls the epoll selector and dispatches ready I/O events.
   - close() : Closes the selector and unlinks the UNIX socket file.

2. CommClient(socket_path="/tmp/coldwar_ipc/game.sock")
   - connect() : Connects to the UNIX domain socket in non-blocking mode.
   - send(payload_dict) : Serializes payload_dict to newline-delimited JSON and sends it to the server.
   - receive_messages() : Non-blockingly reads from the socket and returns a list of parsed JSON dicts.
   - close() : Closes the client socket.

## File Manifest
- comm.py    : Single-file UNIX domain socket IPC library.
- server.py  : Moderator game engine and state machine.
- client.py  : Minimal player terminal client with ANSI UI and chaff handling.
- setup.sh   : Deployment script that creates moderator and player0..3 Linux users and sets permissions.
- report.pdf : Project writeup and gameplay screenshots.

## Setup & How to Play
1. Run the setup script as root to create the Linux users and deploy the files:
   chmod +x setup.sh
   sudo bash setup.sh

2. In Terminal 1 (Moderator), start the server:
   sudo su - moderator
   python3 server.py

3. In Terminals 2, 3, 4, and 5 (Players), log into each player account and launch the client:
   sudo su - player0
   python3 client.py
   (Repeat for player1, player2, and player3).

4. In-Game Commands:
   - msg <text>            : Transmit on encrypted faction multicast radio (War Phase).
   - act <player>          : Execute your role's War Phase action (Arms, Peacekeeping, Intelligence).
   - say <text>            : Broadcast to all living actors during the Emergency Summit (Day Phase).
   - whisper <player> <m>  : Send a covert 1-to-1 back-channel message (Any Phase).
   - vote <player>         : Vote to censure a suspect during the Tribunal Phase.
   - exit (or Ctrl+C)      : Disconnect and exit.
