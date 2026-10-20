#!/usr/bin/env python3
"""
server.py
Purpose: moderator for running games of Proxy Box Fight Club

Features: 
1. Handle user connections and disconnections: Done with the rather reliable CommServer. 
2. Handle user I/O: Process and respond to user I/O with error handling based on game state. 
3. Update game state: Basic logic for checking for victory, tracking user states, and phase scheduling.

This is my "fun" file, so all the simple but necessary game design is in here. I did in fact have fun writing it.  
"""
import os
import re
import time
import signal
import random
from comm import CommServer

CONFIG = {
    'min_players': 4,
    'night_duration': 50,      #War Phase duration (seconds)
    'debate_duration': 50,     #Summit Phase duration (seconds)
    'vote_duration': 40,       #Tribunal Phase duration (seconds)
    'enable_chaff': True,      #toggle for side-channel defense with chaff, see comm.py
    'max_msg_len': 300         #max characters per message, protects from DoS or buffer overflow
}

class ColdWarServer:
    def __init__(self): #set up a server for Proxy Box
        self.comm = CommServer(enable_chaff=CONFIG['enable_chaff'])
        self.comm.on_connect_cb = self.on_connect #callback setup
        self.comm.on_message_cb = self.on_message #callback setup
        self.comm.on_disconnect_cb = self.on_disconnect #callback setup

        signal.signal(signal.SIGUSR1, self._handle_sigusr1) #register SIGUSR1 for live forensic audit dumping if needed

        self.players = {}       #cid to: {'name': str, 'true_team': str, 'apparent_team': str, 'role': str, 'alive': bool}
        self.phase = "LOBBY"    #possible Phases: LOBBY, NIGHT, DAY_DEBATE, DAY_VOTE, GAMEOVER. Should refine this. 
        self.defcon = 5
        self.phase_end_time = 0
        self.night_actions = {} #cid to: {'role': str, 'target_cid': int}
        self.votes = {}         #voter_cid to target_cid

    def _handle_sigusr1(self, signum, frame): #user data dumping
        print("\n" + self.comm.dump_forensics(), flush=True)

    def log(self, text): #self-explanatory)
        print(f"[MODERATOR {time.strftime('%X')}] {text}", flush=True)

    def _sanitize(self, text): #sanitizes input for ANSI escape sequences / control characters, because security.
    #also truncates strings to max length
        if not isinstance(text, str):
            return ""
            
        cleaned = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
        cleaned = "".join(ch for ch in cleaned if ch.isprintable())
        return cleaned[:CONFIG['max_msg_len']].strip()

    def _eliminate_player(self, cid, reason_banner): #update dead player state and partition them from the network. 
        p = self.players.get(cid)
        if not p or not p['alive']:
            return
        p['alive'] = False
        
        if p['apparent_team']: #remove dead players from team multicast
            self.comm.leave_group(cid, p['apparent_team'])
        self.comm.send_direct(cid, {
            'type': 'DEAD',
            'msg': (f"\n╔══════════════════════════════════════════════════════════════╗\n"
                    f"║                  [!] YOU ARE ELIMINATED [!]                  ║\n"
                    f"╠══════════════════════════════════════════════════════════════╣\n"
                    f"║ {reason_banner:<60} ║\n"
                    f"║  You can no longer vote, speak, whisper, or use actions.     ║\n"
                    f"║  Back channel whispering to you is now blocked.              ║\n"
                    f"║  Type 'exit' or press Ctrl+C at any time to disconnect.      ║\n"
                    f"╚══════════════════════════════════════════════════════════════╝")
        })

    def on_connect(self, cid, username, uid, pid): #connection handler, 
        self.log(f"SO_PEERCRED Verified: CID={cid} | User={username} (UID={uid}, PID={pid})")

        if self.phase != "LOBBY": #prevent mid-game connections
            self.log(f"Rejected mid-game connection from {username}.")
            self.comm.send_direct(cid, {
                'type': 'ERR',
                'msg': "A conflict in Proxy Box is already in progress! Connection rejected. Press Ctrl+C to exit."
            })
            self.comm.disconnect_client(cid)
            return

        if any(p['name'] == username for p in self.players.values()): #prevent duplicate connections
            self.log(f"Rejected duplicate connection from {username}.")
            self.comm.send_direct(cid, {
                'type': 'ERR',
                'msg': f"User '{username}' is already connected in another terminal! Press Ctrl+C to exit."
            })
            self.comm.disconnect_client(cid)
            return

        self.players[cid] = {
            'name': username,
            'true_team': None,
            'apparent_team': None,
            'role': None,
            'alive': True
        }

        waiting_list = [p['name'] for p in self.players.values() if p['alive']] #waiting list
        self.comm.send_direct(cid, {
            'type': 'SYS',
            'msg': (f"Kernel SO_PEERCRED Auth Verified: {username} (UID={uid}, PID={pid}). Chaff defense: ACTIVE.\n"
                    f"[LOBBY] Players (aka Actors) currently waiting ({len(waiting_list)}/{CONFIG['min_players']}): {', '.join(waiting_list)}")
        })
        self.comm.broadcast({
            'type': 'ANNOUNCE',
            'msg': f"[+] Actor {username} has announced their official stance on recent instability in Proxy Box ({len(waiting_list)}/{CONFIG['min_players']} ready)"
        })

    def on_disconnect(self, cid, username): #DC handler, will alert all other players of a player disconnecting, with variable messages based on phase
        self.log(f"Player {username} disconnected.")
        if cid in self.players:
            if self.phase == "LOBBY":
                del self.players[cid]
                waiting_list = [p['name'] for p in self.players.values()]
                self.comm.broadcast({
                    'type': 'ANNOUNCE',
                    'msg': f"[-] Player {username} withdrew from the lobby. Waiting ({len(waiting_list)}/{CONFIG['min_players']}): {', '.join(waiting_list)}"
                })
            else:
                was_alive = self.players[cid]['alive']
                self.players[cid]['alive'] = False
                if was_alive:
                    self.comm.broadcast({
                        'type': 'ANNOUNCE',
                        'msg': f"[-] Actor {username}'s Proxy abruptly collapsed due to domestic events (probably) unrelated to Proxy Box and other Actors (Disconnected)."
                    })
                    self.check_win()

    def on_message(self, cid, msg): #message handler to pass messages to comm.py
        player = self.players.get(cid)
        if not player:
            return
        if not player['alive']:
            self.comm.send_direct(cid, {
                'type': 'ERR',
                'msg': "YOU ARE DEAD. Your Proxy is eliminated, leaving you with insufficient influence over Proxy Box's affairs to speak, whisper, vote, or act. (Press Ctrl+C or type 'exit' to quit)."
            })
            return

        mtype = self._sanitize(msg.get('action', ''))
        content = self._sanitize(msg.get('data', ''))

        if not content:
            self.comm.send_direct(cid, {'type': 'ERR', 'msg': "Command argument cannot be empty."})
            return

        if mtype == 'radio': #multicast to team only in War phase, e.g. Werewolves chat for werewolves to coordinate
            if self.phase != 'NIGHT':
                self.comm.send_direct(cid, {'type': 'ERR', 'msg': "Team radio is only available to coordinate WAR operations."})
                return

            radio_team = player['apparent_team'] #Diplomatic actors broadcast on their apparent_team radio, to represent soft power being able to mislead decision makers, institutions, etc.
            shown_role = "Operative" if player['role'] == 'Diplomatic' else player['role']
            self.log(f"Multicast [Radio {radio_team}] {player['name']} (True={player['true_team']}/{player['role']}): {content}")
            self.comm.send_group(radio_team, {
                'type': 'RADIO',
                'team': radio_team,
                'sender': player['name'],
                'role': shown_role,
                'msg': content
            })

        elif mtype == 'whisper': #1-to-1 channel for whispering in any phase
            parts = content.split(' ', 1)
            if len(parts) < 2 or not parts[1].strip():
                self.comm.send_direct(cid, {'type': 'ERR', 'msg': "Usage: whisper <player_name> <secret_message>"})
                return
            target_name, secret_msg = parts[0].strip(), parts[1].strip()
            target_cid = self._get_cid_by_name(target_name)
            if target_cid == cid:
                self.comm.send_direct(cid, {'type': 'ERR', 'msg': "You cannot whisper to yourself."})
                return
            if target_cid and self.players[target_cid]['alive']:
                self.log(f"1-to-1 [BACK CHANNEL] {player['name']} -> {target_name}: {secret_msg}")
                self.comm.send_direct(target_cid, {
                    'type': 'WHISPER',
                    'sender': player['name'],
                    'msg': secret_msg
                })
                self.comm.send_direct(cid, {'type': 'SYS', 'msg': f"Back channel message delivered to {target_name}."})
            else:
                self.comm.send_direct(cid, {'type': 'ERR', 'msg': f"Actor '{target_name}' is either eliminated or does not exist."})

        elif mtype == 'say': #broadcast during summit phase, e.g. when the town has its meeting in Werewolves
            if self.phase != 'DAY_DEBATE':
                self.comm.send_direct(cid, {'type': 'ERR', 'msg': "Summit not in session. Wait for SUMMIT Phase."})
                return
            self.log(f"Broadcast [Summit] {player['name']}: {content}")
            self.comm.broadcast({
                'type': 'SUMMIT',
                'sender': player['name'],
                'msg': content
            })

        elif mtype == 'act': #actions during War, aka Night in Werewolves, where the Werewolves do Werewolfing
            if self.phase != 'NIGHT':
                self.comm.send_direct(cid, {'type': 'ERR', 'msg': "Actions can only be executed in the WAR Phase."})
                return
            if player['role'] == 'Diplomatic':
                self.comm.send_direct(cid, {
                    'type': 'ERR',
                    'msg': "Diplomatic actors have no  War actions, but you can eavesdrop and talk on the enemy's radio ('msg <text>')."
                })
                return
            target_cid = self._get_cid_by_name(content)
            if target_cid and self.players[target_cid]['alive']:
                self.night_actions[cid] = {'role': player['role'], 'target_cid': target_cid}
                self.log(f"War Action Locked: {player['name']} ({player['role']}) -> {content}")
                self.comm.send_direct(cid, {'type': 'SYS', 'msg': f"[{player['role']}] Order locked on target's Proxy: {content}."})
            else:
                self.comm.send_direct(cid, {'type': 'ERR', 'msg': f"Invalid or eliminated target: {content}"})

        elif mtype == 'vote': #voting logic, called the Tribunal in this, same as Werewolves
            if self.phase != 'DAY_VOTE':
                self.comm.send_direct(cid, {'type': 'ERR', 'msg': "Tribunal is not currently convened."})
                return
            target_cid = self._get_cid_by_name(content)
            if target_cid and self.players[target_cid]['alive']:
                self.votes[cid] = target_cid
                self.comm.broadcast({'type': 'VOTE_CAST', 'msg': f"[TRIBUNAL] {player['name']} registered a vote against {content}."})
            else:
                self.comm.send_direct(cid, {'type': 'ERR', 'msg': f"Invalid or eliminated vote target: '{content}'."})

    def _get_cid_by_name(self, name): #lets game mod see more info on players
        for cid, p in self.players.items():
            if p['name'] == name:
                return cid
        return None

    def start_game(self): #self-explanatory
        alive_cids = [cid for cid, p in self.players.items() if p['alive']]
        if len(alive_cids) < CONFIG['min_players']:
            return False

        self.log(f"Initializing PROXY BOX FIGHT CLUB ({len(alive_cids)} Players)...")
        random.shuffle(alive_cids)

        
        assignments = [ #role pool
        #format: (true_team, apparent_team, role, description)
            ('BLUFOR', 'BLUFOR', 'Arms',         'War Action: Destroy another Actor\'s Proxy by arming your own (act <name>).'),
            ('BLUFOR', 'BLUFOR', 'Intelligence', 'War Action: Investigate an Actor to learn their Proxy\'s TRUE faction & role (act <name>).'),
            ('REDFOR', 'REDFOR', 'Peacekeeping', 'War Action: Protect any Actor\'s Proxy from destruction with foreign Arms via peacekeeping operations with your own armed forces (act <name>).'),
            ('REDFOR', 'BLUFOR', 'Diplomatic',   'War Action: NONE. You can listen and speak on the REDFOR radio channel and appear as REDFOR to everyone besides Intelligence using their War Action on you. ')
        ]

        extra_Pool = [ #extra roles if playing with 5 or 6 players
            ('REDFOR', 'REDFOR', 'Arms',         'War Action: Destroy another Actor\'s Proxy by arming your own (act <name>).'),
            ('REDFOR', 'BLUFOR', 'Diplomatic',   'War Action: NONE. You can listen and speak on the BLUFOR radio channel and appear as BLUFOR to everyone besides Intelligence using their War Action on you. ')
        ]
        
        while len(assignments) < len(alive_cids):
            assignments.append(extra_Pool[(len(assignments) - 4) % len(extra_Pool)])

        for i, cid in enumerate(alive_cids): #add to teams and assign roles
            true_t, app_t, role, desc = assignments[i]
            p = self.players[cid]
            p['true_team'] = true_t
            p['apparent_team'] = app_t
            p['role'] = role
            self.comm.join_group(cid, app_t) #join apparent_team so Diplomatic shows up as on the other team

        for cid in alive_cids:
            p = self.players[cid]
            
            apparent_allies = [ #allies list uses apparent_team bc Diplomatic
                other['name'] for ocid, other in self.players.items()
                if other['apparent_team'] == p['apparent_team'] and ocid != cid
            ]
            infiltrator_note = (
                f"\n║ COVER   : Disguised as {p['apparent_team']} (On {p['apparent_team']} Radio!)      ║"
                if p['role'] == 'Diplomatic' else ""
            )
            self.comm.send_direct(cid, {
                'type': 'BRIEFING',
                'team': p['true_team'],
                'role': p['role'],
                'msg': (f"\n╔══════════════════════════════════════════════════════╗\n"
                        f"║             CLASSIFIED DOSSIER // EYES ONLY          ║\n"
                        f"╠══════════════════════════════════════════════════════╣\n"
                        f"║ TRUE FACTION : {p['true_team']:<37} ║\n"
                        f"║ ROLE         : {p['role']:<37} ║{infiltrator_note}\n"
                        f"║ RADIO GROUP  : {p['apparent_team']} ({', '.join(apparent_allies)}){'':<18} ║\n"
                        f"╠══════════════════════════════════════════════════════╣\n"
                        f"║       The situation in Proxy Box is... dynamic       ║\n"
                        f"╚══════════════════════════════════════════════════════╝")
            })

        self.enter_night()
        return True

    def enter_night(self): #state transition to night (war), reset night action dict, start phase timer, inform players
        self.phase = "NIGHT"
        self.night_actions = {}
        dur = CONFIG['night_duration']
        self.phase_end_time = time.time() + dur
        alive_list = [p['name'] for p in self.players.values() if p['alive']]
        self.comm.broadcast({
            'type': 'PHASE',
            'phase': 'NIGHT',
            'msg': (f"\n[DEFCON {self.defcon} - WAR ACTIONS ({dur}s)]\n"
                    f"Actors sponsoring Proxies: {alive_list}\n"
                    f"  Use 'msg <text>' for encrypted team multicast radio.\n"
                    f"  Use 'act <name>' to execute your role ability.\n"
                    f"  Use 'whisper <name> <text>' for 1-to-1 back channel diplomacy.")
        })

    def resolve_night(self): #handle night operations in order of Peacekeeping, then Intelligence, then Arms
        self.log("Resolving War Operations...")
        shielded = set()
        deaths = set()

        for actor_cid, act in self.night_actions.items():
            role = act['role']
            target_cid = act['target_cid']
            if role == 'Peacekeeping':
                shielded.add(target_cid)
            elif role == 'Intelligence':
                target_p = self.players[target_cid]

                self.comm.send_direct(actor_cid, { #Intelligence counters Diplomatic via espionage. Such as by obtaining information on Diplomatic's plans to double-cross, evidence of secret operations, or information warfare masking the real situation on the ground. Could give IRL examples from pretty much any modern region, bloc, alliance, system of government, etc, but want to remain apolitical.  
                    'type': 'SYS',
                    'msg': f"[SIGINT] Surveillance confirms {target_p['name']}'s Proxy's TRUE faction is {target_p['true_team']} (Role: {target_p['role']}, Apparent: {target_p['apparent_team']})!"
                })

        for actor_cid, act in self.night_actions.items():
            if act['role'] == 'Arms':
                target_cid = act['target_cid']
                if target_cid in shielded:
                    self.log(f"A Proxy offensive against {self.players[target_cid]['name']}'s in-country Proxy, despite foreign Arms support, was intercepted by Peacekeeping operations!")
                else:
                    deaths.add(target_cid)

        for d_cid in deaths: #update player states for dead players and remove from multicast groups
            self._eliminate_player(d_cid, "[DEAD] Your Proxy in Proxy Box was destroyed in a Wartime offensive assisted by a foreign Arms supplier!")

        self.defcon = max(1, self.defcon - 1)
        self.enter_day(deaths)

    def enter_day(self, night_deaths): #state transition to day (summit)
        if self.check_win():
            return
        self.phase = "DAY_DEBATE"
        dur = CONFIG['debate_duration']
        self.phase_end_time = time.time() + dur
        death_names = [self.players[d]['name'] for d in night_deaths]

        if len(death_names) > 1:
            summary = f"War Developments: {', '.join(death_names)} had their Proxies destroyed. They can no longer exert influence on Proxy Box. "
        elif len(death_names) == 1:
            summary = f"War Development: {death_names[0]}'s Proxy was destroyed. They can no longer exert influence on Proxy Box. "
        else:
            summary = "The balance of power in Proxy Box remains stable, if not Proxy Box itself..."

        self.comm.broadcast({
            'type': 'PHASE',
            'phase': 'DAY_DEBATE',
            'msg': (f"\n[DEFCON {self.defcon} - EMERGENCY SUMMIT ({dur}s)]\n"
                    f"Actors with a stake in Proxy Box will now convene a Summit to discuss recent developments via industrialized mud-slinging en masse and other forms of information/narrative warfare.\n"
                    f"{summary}\n"
                    f"  Use 'say <text>' to address all actors publicly.\n"
                    f"  Use 'whisper <name> <text>' for 1-to-1 back channel messages.")
        })

    def enter_vote(self): #state transition to vote (tribunal) and accept player votes
        self.phase = "DAY_VOTE"
        self.votes = {}
        dur = CONFIG['vote_duration']
        self.phase_end_time = time.time() + dur
        alive_names = [p['name'] for p in self.players.values() if p['alive']]
        self.comm.broadcast({
            'type': 'PHASE',
            'phase': 'DAY_VOTE',
            'msg': f"\n[TRIBUNAL VOTE ({dur}s)] Cast your vote to censure an actor for... Violating Bloxian Sovereignty: {alive_names}\n  Use 'vote <name>'."
        })

    def resolve_vote(self): #tally votes, update state of censured player, remove censured player from multicast group, call check for victory
        if self.votes:
            tally = {}
            for target in self.votes.values():
                tally[target] = tally.get(target, 0) + 1
            expelled = max(tally, key=tally.get)
            p = self.players[expelled]
            self._eliminate_player(expelled, "You were censured by the Tribunal!")
            
            self.comm.broadcast({ #censure death shows apparent_team because nations/other geopolitical actors with diplomatic weight tend to be good at shaping media narrative to some part, even when condemned, so having enough control over the narrative to obfuscate one's side enough to be believed is pretty plausible for international actors with a lot of soft power. I can give examples IRL from all corners of the world with various systems of government, beliefs, etc, but would prefer to remain apolitical. 
                'type': 'ANNOUNCE',
                'msg': f"[TRIBUNAL VERDICT] {p['name']} was censured by the Tribunal! International sanctions enforcement reports list their Proxy under: {p['apparent_team']}."
            })
        else:
            self.comm.broadcast({'type': 'ANNOUNCE', 'msg': "[TRIBUNAL VERDICT] Deadlock. No actor's Proxy was censured."})

        if not self.check_win():
            self.enter_night()

    def check_win(self):
        blu_alive = sum(1 for p in self.players.values() if p['true_team'] == 'BLUFOR' and p['alive'])
        red_alive = sum(1 for p in self.players.values() if p['true_team'] == 'REDFOR' and p['alive'])

        if blu_alive == 0 and red_alive == 0:
            self.phase = "GAMEOVER"
            self.comm.broadcast({'type': 'GAMEOVER', 'msg': "\n[GAME OVER] MUTUAL DESTRUCTION: Proxy Box is free of foreign meddling. ONLY BOXIANS can meddle with... Boxians. Oh."})
            return True
        elif blu_alive == 0:
            self.phase = "GAMEOVER"
            self.comm.broadcast({'type': 'GAMEOVER', 'msg': "\n[GAME OVER] REDFOR VICTORY: All BLUFOR Proxies neutralized!\nProxy Box belongs to REDFOR via its Proxies, for now..."})
            return True
        elif red_alive == 0:
            self.phase = "GAMEOVER"
            self.comm.broadcast({'type': 'GAMEOVER', 'msg': "\n[GAME OVER] BLUFOR VICTORY: All REDFOR Proxies neutralized!\nProxy Box belongs to BLUFOR via its Proxies, for now..."})
            return True
        return False

    def run(self): #scheduling phases
        self.log(f"Server PID={os.getpid()} online. (Run 'kill -SIGUSR1 {os.getpid()}' for forensic table).")
        try:
            while True:
                self.comm.poll(timeout=0.05)
                now = time.time()

                if self.phase == "GAMEOVER":
                    self.comm.poll(timeout=0.5)
                    self.log("Match concluded. Shutting down server. Ending History (or not).")
                    break
                elif self.phase == "LOBBY":
                    alive = [cid for cid, p in self.players.items() if p['alive']]
                    if len(alive) >= CONFIG['min_players']:
                        self.start_game()
                elif self.phase == "NIGHT" and now >= self.phase_end_time:
                    self.resolve_night()
                elif self.phase == "DAY_DEBATE" and now >= self.phase_end_time:
                    self.enter_vote()
                elif self.phase == "DAY_VOTE" and now >= self.phase_end_time:
                    self.resolve_vote()

        except KeyboardInterrupt:
            self.log("Server shutting down.")
        finally:
            self.comm.close()

if __name__ == '__main__':
    ColdWarServer().run()
