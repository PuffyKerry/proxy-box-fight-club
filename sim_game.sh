#!/bin/bash
# Automated 5-user game simulator for Proxy Box Fight Club (finishes in ~15s)

sudo bash setup.sh >/dev/null

cat << 'PYEOF' > /tmp/fast_server.py
import os, sys, signal, threading
sys.path.insert(0, '/home/moderator')
import server
server.CONFIG['night_duration'] = 5
server.CONFIG['debate_duration'] = 5
server.CONFIG['vote_duration'] = 4

# Send SIGUSR1 strictly to the Python server PID 3 seconds in
threading.Timer(3.0, lambda: os.kill(os.getpid(), signal.SIGUSR1)).start()
server.ColdWarServer().run()
PYEOF
chmod 755 /tmp/fast_server.py

cat << 'PYEOF' > /tmp/auto_player.py
import os, sys, time, pwd
me = pwd.getpwuid(os.getuid()).pw_name
sys.path.insert(0, f"/home/{me}")
from comm import CommClient

C_RED, C_CYAN, C_MAG, C_GREEN, C_YEL, C_RESET = "\033[91m", "\033[96m", "\033[95m", "\033[92m", "\033[93m", "\033[0m"

client = CommClient()
client.connect()
print(f"{C_GREEN}=== PROXY BOX FIGHT CLUB TERMINAL ({me}) ==={C_RESET}", flush=True)

my_role = None
my_team = None
round_num = 0
alive = True
others = [f"player{i}" for i in range(4) if f"player{i}" != me]

while True:
    for m in client.receive_messages():
        mtype = m.get('type')
        if mtype == 'CHAFF':
            sys.stdout.write("\033[s\033[u")
            sys.stdout.flush()
        elif mtype == 'SYS':
            print(f"{C_GREEN}[SYSTEM] {m['msg']}{C_RESET}", flush=True)
        elif mtype == 'DEAD':
            alive = False
            print(f"{C_RED}{m['msg']}{C_RESET}", flush=True)
        elif mtype == 'BRIEFING':
            my_team = m.get('team')
            my_role = m.get('role')
            color = C_CYAN if my_team == 'BLUFOR' else C_RED
            print(f"{color}{m['msg']}{C_RESET}", flush=True)
        elif mtype == 'PHASE':
            print(f"{C_YEL}{m['msg']}{C_RESET}", flush=True)
            p = m.get('phase')
            if p == 'NIGHT' and alive:
                round_num += 1
                time.sleep(0.6)
                radio_msg = f"Check-in from {me} (Round {round_num}). Coordinating operations."
                print(f"> msg {radio_msg}", flush=True)
                client.send({'action': 'radio', 'data': radio_msg})
                time.sleep(0.3)
                if my_role != 'Diplomatic':
                    target = others[(round_num - 1) % len(others)]
                    print(f"> act {target}", flush=True)
                    client.send({'action': 'act', 'data': target})
            elif p == 'DAY_DEBATE' and alive:
                time.sleep(0.6)
                say_msg = f"Actor {me} condemns recent foreign escalations in Proxy Box!"
                print(f"> say {say_msg}", flush=True)
                client.send({'action': 'say', 'data': say_msg})
                time.sleep(0.3)
                w_target = others[0]
                w_msg = f"{w_target} Lets coordinate our Tribunal vote this round."
                print(f"> whisper {w_msg}", flush=True)
                client.send({'action': 'whisper', 'data': w_msg})
            elif p == 'DAY_VOTE' and alive:
                time.sleep(0.6)
                v_target = "player2" if round_num == 1 and me != "player2" else others[-1]
                print(f"> vote {v_target}", flush=True)
                client.send({'action': 'vote', 'data': v_target})
        elif mtype == 'RADIO':
            color = C_CYAN if m.get('team') == 'BLUFOR' else C_RED
            print(f"{color}[RADIO {m['team']}] {m['sender']} ({m['role']}): {m['msg']}{C_RESET}", flush=True)
        elif mtype == 'WHISPER':
            print(f"{C_MAG}[BACK CHANNEL from {m['sender']}]: {m['msg']}{C_RESET}", flush=True)
        elif mtype == 'SUMMIT':
            print(f"[SUMMIT] {m['sender']}: {m['msg']}", flush=True)
        elif mtype in ('ANNOUNCE', 'VOTE_CAST', 'GAMEOVER'):
            print(f"{C_YEL}{m['msg']}{C_RESET}", flush=True)
            if mtype == 'GAMEOVER':
                time.sleep(60)
                sys.exit(0)
        elif mtype == 'ERR':
            print(f"{C_RED}[ERROR] {m['msg']}{C_RESET}", flush=True)
    time.sleep(0.05)
PYEOF
chmod 755 /tmp/auto_player.py

if command -v tmux >/dev/null && [ "${1:-}" != "--inline" ]; then
    tmux kill-session -t proxybox 2>/dev/null || true
    tmux new-session -d -s proxybox -n "ProxyBox" "runuser -u moderator -- python3 -u /tmp/fast_server.py; read"
    sleep 0.8
    for i in 0 1 2 3; do
        tmux split-window -t proxybox:0 "runuser -u player$i -- python3 -u /tmp/auto_player.py; read"
        tmux select-layout -t proxybox:0 tiled >/dev/null
        sleep 0.25
    done
    tmux set-option -t proxybox mouse on
    tmux attach-session -t proxybox
else
    runuser -u moderator -- python3 -u /tmp/fast_server.py &
    SRV_PID=$!
    sleep 0.8
    for i in 0 1 2 3; do
        runuser -u player$i -- python3 -u /tmp/auto_player.py > /tmp/p$i.log 2>&1 &
        sleep 0.25
    done
    wait $SRV_PID 2>/dev/null || true
    for i in 0 1 2 3; do
        echo -e "\n================ PLAYER $i TERMINAL ================"
        cat /tmp/p$i.log
    done
fi
