#!/usr/bin/env python3
"""
comm.py
Purpose: Hardened UNIX Domain Socket IPC Library

Features:
1. Event-Driven I/O: Uses selectors.DefaultSelector (Linux epoll) for non-blocking multiplexing.
2. Kernel Authentication: Uses SO_PEERCRED to verify client UID, GID, and PID via Linux kernel.
3. Side-Channel Defense: Constant-Rate Traffic Padding (aka sending Chaff packets) on 1-to-1 and 
   Multicast calls so all client processes wake from sleep and update PTY timestamps simultaneously. 
   This is meant to defeat side channel attacks like /proc/[pid]/stat (spyboth.sh example from class) 
   and /dev/pts mtime (spy.sh example from class).
4. Signal Safety: Decided to ignore SIGPIPE because broken pipes can cause crashes. 

Basically all the backend communications happens here. 
"""

import os
import socket
import struct
import selectors
import json
import pwd
import signal

SO_PEERCRED = 17  #Linux kernel socket option for peer credentials
MAX_BUF_SIZE = 8192

class CommServer: #not to be confused with server.py, this is the actual server
    def __init__(self, socket_path="/tmp/coldwar_ipc/game.sock", enable_chaff=True): #this is not modular. for now
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)
        self.socket_path = socket_path
        self.enable_chaff = enable_chaff
        self.selector = selectors.DefaultSelector()
        self.clients = {}         #cid -> {'sock': sock, 'uid': uid, 'pid': pid, 'username': str, 'buf': ''}
        self.sock_to_id = {}       #sock -> cid
        self.groups = {}           #group_name -> set(cids)
        self.next_client_id = 1

        self.on_connect_cb = None #callback hooks
        self.on_message_cb = None #callback hooks
        self.on_disconnect_cb = None #callback hooks

        self._setup_socket()

    def _setup_socket(self): #use socket, for sockets, to socket sockets (yes this is a real sentence in normal English as much as Developer)
        os.makedirs(os.path.dirname(self.socket_path), exist_ok=True)
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)
        self.server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_sock.bind(self.socket_path)
        os.chmod(self.socket_path, 0o777)
        self.server_sock.listen(16)
        self.server_sock.setblocking(False)
        self.selector.register(self.server_sock, selectors.EVENT_READ, data=self._accept)

    def _get_peer_cred(self, client_sock): #query kernel with SO_PEERCRED, which returns unforgeable process credentials for authentication purposes
        try:
            cred = client_sock.getsockopt(socket.SOL_SOCKET, SO_PEERCRED, struct.calcsize("3i"))
            pid, uid, gid = struct.unpack("3i", cred)
            try:
                username = pwd.getpwuid(uid).pw_name
            except KeyError:
                username = f"uid_{uid}"
            return pid, uid, username
        except Exception:
            return 0, 65534, "unknown"

    def _accept(self, sock, mask): #log connection requests from clients 
        conn, _ = sock.accept()
        conn.setblocking(False)
        pid, uid, username = self._get_peer_cred(conn)
        cid = self.next_client_id
        self.next_client_id += 1

        self.clients[cid] = {
            'sock': conn,
            'uid': uid,
            'pid': pid,
            'username': username,
            'buf': ''
        }
        self.sock_to_id[conn] = cid
        self.selector.register(conn, selectors.EVENT_READ, data=self._read)

        if self.on_connect_cb: #option for hook for connections doing things if set up to do things
            self.on_connect_cb(cid, username, uid, pid)

    def _read(self, conn, mask): #input parsing triggered by epoll whenever client socket has input, appends input to client's string buffer, sanitizes and parses buffer into JSON
        cid = self.sock_to_id.get(conn)
        if not cid:
            return
        try:
            data = conn.recv(4096)
            if data:
                self.clients[cid]['buf'] += data.decode('utf-8', errors='ignore')
                if len(self.clients[cid]['buf']) > MAX_BUF_SIZE:
                    self.clients[cid]['buf'] = ''  #protection from memory exhaustion DoS attacks by slapping their buf's down
                while '\n' in self.clients[cid]['buf']:
                    line, self.clients[cid]['buf'] = self.clients[cid]['buf'].split('\n', 1)
                    if line.strip():
                        try:
                            msg = json.loads(line)
                            if isinstance(msg, dict) and self.on_message_cb: #option for hook for messages doing things if set up to Do Things (TM). 
                                self.on_message_cb(cid, msg)
                        except json.JSONDecodeError:
                            pass
            else:
                self._disconnect(conn)
        except (ConnectionResetError, BrokenPipeError, OSError):
            self._disconnect(conn)

    def _disconnect(self, conn): #remove disconnected client socket
        cid = self.sock_to_id.get(conn)
        if cid:
            try:
                self.selector.unregister(conn) #unregister from epoll socket
                conn.close() #close socket on OS side
            except Exception:
                pass
            
            for grp in self.groups.values(): #remove client from multicast groups (game functionality)
                grp.discard(cid)
            username = self.clients[cid]['username']
            del self.clients[cid] #remove client data from own storage
            del self.sock_to_id[conn] #ditto
            
            if self.on_disconnect_cb: #option for disconnect hook to do things, for server to handle on their side if it's set up. 
                self.on_disconnect_cb(cid, username)

    def disconnect_client(self, cid): #helper to kick duplicate or mid-game connections cleanly, meant to catch invalid clients before crashes
        client = self.clients.get(cid)
        if client:
            self._disconnect(client['sock'])

    def _raw_send(self, cid, payload_dict): #helper for sending to client, formats dict into JSON, encodes to UTF-8, sends to client's domain socket
        client = self.clients.get(cid)
        if client:
            try:
                raw = (json.dumps(payload_dict) + '\n').encode('utf-8') #adds newline separators for readability
                client['sock'].sendall(raw)
            except Exception:
                pass

    def _send_chaff_to_others(self, excluded_cids, target_len=64): #send dummy packets to non-recipient clients to mask CPU wakeups and PTY timestamps of the intended recipient, which are possible side channels. 
        if not self.enable_chaff:
            return
        pad = "X" * max(1, target_len - 25)
        chaff_payload = {'type': 'CHAFF', 'pad': pad}
        for cid in list(self.clients.keys()):
            if cid not in excluded_cids:
                self._raw_send(cid, chaff_payload)


#   VERY.             IMPORTANT:         PUBLIC COMMUNICATIONS API STARTS HERE, is below

    def send_direct(self, client_id, payload): #1-to-1 whisper API for payload using _raw_send
        """1-to-1 Primitive (with optional side-channel chaff masking)."""
        self._raw_send(client_id, payload)
        self._send_chaff_to_others({client_id}, len(json.dumps(payload))) #send chaff to everyone else to prevent side channel

    def join_group(self, client_id, group_name): #add client to group, creates group first if not created, for multicast aka Radio. 
        if group_name not in self.groups:
            self.groups[group_name] = set()
        self.groups[group_name].add(client_id)

    def leave_group(self, client_id, group_name): #remove client from group, for dead or DC'd players
        if group_name in self.groups:
            self.groups[group_name].discard(client_id)

    def send_group(self, group_name, payload): #primitive for multicasting to group, which sends chaff to everyone outside of the group as well. 
        members = self.groups.get(group_name, set())
        for cid in list(members):
            self._raw_send(cid, payload)
        self._send_chaff_to_others(members, len(json.dumps(payload)))

    def broadcast(self, payload): #primitive for broadcasting, doesn't need chaff due to sending to all. 
        for cid in list(self.clients.keys()):
            self._raw_send(cid, payload)

    def dump_forensics(self): #return a table of clients connected, protected by the Linux kernel's built in features around identity
        lines = ["=== KERNEL SO_PEERCRED FORENSIC TABLE ==="]
        for cid, c in self.clients.items():
            grps = [g for g, m in self.groups.items() if cid in m]
            lines.append(f"CID={cid} | User={c['username']} | UID={c['uid']} | PID={c['pid']} | FD={c['sock'].fileno()} | Groups={grps}")
        lines.append("=========================================")
        return "\n".join(lines)

    def poll(self, timeout=0.05): #event loop driver
        events = self.selector.select(timeout=timeout) #invokes epoll_wait in kernel to sleep until a socket I/O event is ready or timeout is over
        for key, mask in events:
            callback = key.data
            callback(key.fileobj, mask) #execute bound callback, either _accept or _read, for each ready socket

    def close(self): #self-explanatory
        self.selector.close()
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)


class CommClient: #very basic client objects meant to adhere to least privilege by keeping communications handling solely server-side
    def __init__(self, socket_path="/tmp/coldwar_ipc/game.sock"):
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)
        self.socket_path = socket_path
        self.sock = None
        self.buf = ""

    def connect(self): #map socket path to self 
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.socket_path)
        self.sock.setblocking(False)

    def send(self, payload): #forwarding done by server
        raw = (json.dumps(payload) + '\n').encode('utf-8')
        self.sock.sendall(raw)

    def receive_messages(self): #sanitize input received before printing bc injection attacks
        try:
            data = self.sock.recv(4096)
            if data:
                self.buf += data.decode('utf-8', errors='ignore')
                messages = []
                while '\n' in self.buf:
                    line, self.buf = self.buf.split('\n', 1)
                    if line.strip():
                        try:
                            messages.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
                return messages
        except BlockingIOError:
            pass
        return []

    def close(self): #self-explanatory
        if self.sock:
            self.sock.close()
