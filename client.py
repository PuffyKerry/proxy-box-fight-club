#!/usr/bin/env python3
"""
client.py
Purpose: minimal client side handler for handling client input

This is minimal on purpose, to keep as little as possible client-side. 
"""
import sys
import select
from comm import CommClient

C_RED   = "\033[91m" #color coded terminal UI for prettiness, still looks jank
C_CYAN  = "\033[96m"
C_MAG   = "\033[95m"
C_GREEN = "\033[92m"
C_YEL   = "\033[93m"
C_RESET = "\033[0m"

def main():
    client = CommClient()
    try:
        client.connect()
    except Exception as e:
        print(f"[-] Connection failed: {e}. Check if moderator server's running.")
        sys.exit(1)

    print(f"{C_GREEN}========================================================{C_RESET}")
    print(f"{C_GREEN}                  PROXY BOX FIGHT CLUB                  {C_RESET}")
    print(f"{C_GREEN}        Where Politics is but War by Other Means        {C_RESET}")
    print(f"{C_GREEN}                                                        {C_RESET}")
    print(f"{C_GREEN}          A Geopolitical Werewolves-esque TDM           {C_RESET}")
    print(f"{C_GREEN}  Inspired by a smorgasbord of almost any IRL conflict  {C_RESET}")
    print(f"{C_GREEN}========================================================{C_RESET}")
    print("Commands:")
    print("  msg <text>            -> Talk on Faction Radio (War Phase)")
    print("  act <player>          -> Execute Action (Kill / Inspect / Protect) (War Phase)")
    print("  say <text>            -> Broadcast to all living players ('actors') (Summit Phase)")
    print("  whisper <player> <m>  -> 1-to-1 Back Channel Diplomacy with any player (Any Phase)")
    print("  vote <player>         -> Vote to censure player (Tribunal Phase)")
    print("  exit (or Ctrl+C)      -> Disconnect and exit terminal")
    print(f"{C_GREEN}========================================================{C_RESET}\n")

    try:
        while True:
            readable, _, _ = select.select([sys.stdin, client.sock], [], [], 0.05)

            for src in readable:
                if src == client.sock:
                    messages = client.receive_messages()
                    if not messages and client.buf == "": #make sure socket is open
                        pass
                    for m in messages:
                        mtype = m.get('type')
                        if mtype == 'CHAFF': #side channel defense here is to write an invisible ANSI no-op, which updates /dev/pts/X modification time for all clients who are not recipients of the message alongside the actual recipients
                            sys.stdout.write("\033[s\033[u")
                            sys.stdout.flush()
                        elif mtype == 'SYS':
                            print(f"{C_GREEN}[SYSTEM] {m['msg']}{C_RESET}")
                        elif mtype == 'DEAD':
                            print(f"{C_RED}{m['msg']}{C_RESET}")
                        elif mtype == 'BRIEFING':
                            color = C_CYAN if m.get('team') == 'BLUFOR' else C_RED
                            print(f"{color}{m['msg']}{C_RESET}")
                        elif mtype == 'PHASE':
                            print(f"{C_YEL}{m['msg']}{C_RESET}")
                        elif mtype == 'RADIO':
                            color = C_CYAN if m.get('team') == 'BLUFOR' else C_RED
                            print(f"{color}[RADIO {m['team']}] {m['sender']} ({m['role']}): {m['msg']}{C_RESET}")
                        elif mtype == 'WHISPER':
                            print(f"{C_MAG}[BACK CHANNEL from {m['sender']}]: {m['msg']}{C_RESET}")
                        elif mtype == 'SUMMIT':
                            print(f"[SUMMIT] {m['sender']}: {m['msg']}")
                        elif mtype in ('ANNOUNCE', 'VOTE_CAST', 'GAMEOVER'):
                            print(f"{C_YEL}{m['msg']}{C_RESET}")
                            if mtype == 'GAMEOVER':
                                print(f"{C_GREEN}[SYSTEM] Match complete. Press Ctrl+C or type 'exit' to leave.{C_RESET}")
                        elif mtype == 'ERR':
                            print(f"{C_RED}[ERROR] {m['msg']}{C_RESET}")

                elif src == sys.stdin:
                    line = sys.stdin.readline()
                    if not line:
                        return
                    parts = line.strip().split(' ', 1)
                    cmd = parts[0].lower()
                    arg = parts[1] if len(parts) > 1 else ''

                    if cmd in ('msg', 'radio'):
                        client.send({'action': 'radio', 'data': arg})
                    elif cmd in ('whisper', 'drop'):
                        client.send({'action': 'whisper', 'data': arg})
                    elif cmd in ('say', 'talk'):
                        client.send({'action': 'say', 'data': arg})
                    elif cmd in ('act', 'kill', 'protect', 'inspect'):
                        client.send({'action': 'act', 'data': arg})
                    elif cmd == 'vote':
                        client.send({'action': 'vote', 'data': arg})
                    elif cmd in ('exit', 'quit'):
                        print("Disconnecting from game, and Proxy Box...")
                        return
                    else:
                        print("[!] Commands: msg <txt>, act <name>, say <txt>, whisper <name> <txt>, vote <name>, exit")

    except KeyboardInterrupt:
        print("\n[!] Disconnecting via Ctrl+C...")
    finally:
        client.close()

if __name__ == '__main__':
    main()
