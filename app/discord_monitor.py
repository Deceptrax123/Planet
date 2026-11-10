"""Plain-language Discord observability; detailed tool payloads never leave the monitor."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
from mission_control import snapshot

HOME = Path('/var/lib/personal-agent')
CONFIG = HOME / '.config/discord-monitor.json'
STATE = HOME / '.config/discord-monitor-state.json'


class Publisher:
    def __init__(self):
        self.token = (Path(os.environ['CREDENTIALS_DIRECTORY']) / 'discord_token').read_text().strip()
        self.channels = json.loads(CONFIG.read_text())
        self.state = json.loads(STATE.read_text()) if STATE.exists() else {}

    def save(self):
        tmp = STATE.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.state))
        tmp.chmod(0o600)
        tmp.replace(STATE)

    def send(self, channel, payload, message=None):
        payload['allowed_mentions'] = {'parse': []}
        url = 'https://discord.com/api/v10/channels/' + channel + '/messages'
        if message:
            url += '/' + message
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={
            'Authorization': 'Bot ' + self.token, 'Content-Type': 'application/json', 'User-Agent': 'JiEunMonitor/1.0'}, method='PATCH' if message else 'POST')
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                return json.load(response)['id']
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and message:
                return self.send(channel, payload)
            # Only log response code; never credential/request body.
            raise RuntimeError('Discord monitor HTTP ' + str(exc.code)) from None

    def tick(self):
        d = snapshot()
        rows = d.get('threads', [])
        known = self.state.setdefault('threads', {})
        changed = []
        first = not self.state.get('initialized')
        for row in reversed(rows):
            old = known.get(row['id'])
            current = row['state']
            # A short turn can start and finish between polls on the same thread.
            # Its visible event timestamp still distinguishes it from the last turn.
            fingerprint = current + '|' + str((row.get('latest') or {}).get('at', ''))
            known[row['id']] = fingerprint
            if (old != fingerprint and not first) or (first and current == 'working'):
                role = row['role']
                parent = ' · teammate delegated by another agent' if row['parent_id'] else ''
                verb = {'working': 'started working', 'done': 'finished', 'failed': 'hit an error', 'stopped': 'stopped', 'unconfirmed': 'needs a status check', 'unknown': 'has a session with unconfirmed status'}.get(current, current)
                # No task prompt, tool command, arguments, or mailbox/health data in Discord logs.
                changed.append(f"**{role}** {verb}{parent}\nModel: `{row['model'] or 'unavailable'}` · session `{row['id'][:8]}`")
        known_ids = {r['id'] for r in rows}
        self.state['threads'] = {k:v for k,v in known.items() if k in known_ids}
        research=d.get('research') or {}
        research_known=self.state.setdefault('research_tasks',{})
        for task in reversed(research.get('tasks',[])):
            old=research_known.get(task['id']);current=task['state']
            research_known[task['id']]=current
            if (old!=current and not first) or (first and current=='working'):
                verb={'queued':'queued a requested task','submitting':'is connecting to start work','starting':'is starting the remote runner','working':'started work',
                      'done':'finished','failed':'hit an error','waiting':'is waiting for its connection',
                      'connection_lost':'lost its connection; remote work may still be running',
                      'cancelling':'is cancelling','cancelled':'cancelled the task','timed_out':'reached its time limit'}.get(current,current)
                changed.append(f"**Ji An / {task['engine']}** {verb}\nServer: `{task['host']}` · task `{task['id']}`\nVisible logs are in the private server monitor.")
        research_ids={task['id'] for task in research.get('tasks',[])}
        self.state['research_tasks']={k:v for k,v in research_known.items() if k in research_ids}
        self.state['initialized'] = True
        if changed:
            content = '\n\n'.join(changed[-12:])[:1900]
            try:
                self.send(self.channels['agent-activity'], {'content': content})
            except (OSError, RuntimeError):
                # Do not blindly repeat after an ambiguous network send.
                self.save()
                raise
        now = time.time()
        health = json.dumps({'whatsapp':d.get('whatsapp'), 'services':d.get('services'), 'reminders':d.get('reminders'), 'board':[(r.get('id'),r.get('status')) for r in d.get('board',[])], 'working':sum(r['state']=='working' for r in rows), 'paused':d.get('paused'), 'error':d.get('error'), 'schedules':d.get('schedules'), 'research':{'auth':research.get('auth'),'hosts':[(h['name'],h.get('state')) for h in research.get('hosts',[])],'tasks':[(r['id'],r['state']) for r in research.get('tasks',[])]}},sort_keys=True)
        if health != self.state.get('health') or now - self.state.get('status_at', 0) >= 300:
            services = '\n'.join(('🟢' if state == 'active' else '🔴') + ' ' + name + ': ' + state for name,state in d.get('services',{}).items())
            failures = sum(r['state']=='failed' for r in rows)
            delivery_errors = sum(r['status'] in {'failed','ambiguous'} for r in d.get('deliveries',[]))
            embed = {'title':'Ji Eun · Operations monitor', 'color':0xc5e4aa if not failures and not delivery_errors and not d.get('error') else 0xf1988f,
                     'description':('⏸ New work paused\n' if d.get('paused') else '')+(services or 'Service status unavailable'), 'fields':[
                         {'name':'Agents working','value':str(sum(r['state']=='working' for r in rows)), 'inline':True},
                         {'name':'Open tasks','value':str(sum(r.get('status') not in {'done','archived','cancelled'} for r in d.get('board',[]))), 'inline':True},
                         {'name':'WhatsApp','value':(d.get('whatsapp') or {}).get('state','not_paired'), 'inline':True},
                         {'name':'Delivery alerts','value':str(delivery_errors), 'inline':True},
                         {'name':'Research servers','value':('GCP: '+research.get('auth','unavailable')+'\n'+'\n'.join(h['name']+': '+h.get('state','not verified') for h in research.get('hosts',[])))[:1000]},
                         {'name':'Schedule','value':'Daily brief 09:00 IST · Proactive conversations anytime\n'+'\n'.join(job['name']+': '+(job.get('last_status') or job.get('state') or 'scheduled') for job in d.get('schedules',[]))},
                         {'name':'Detailed monitor','value':'Private server dashboard on port 9120. Server terminal: `personal-agent-monitor --watch`.'}],
                     'timestamp':datetime.now(timezone.utc).isoformat(), 'footer':{'text':'Live observations · no raw tool commands · updates on change'}}
            message = self.send(self.channels['ji-eun-status'], {'embeds':[embed]}, self.state.get('status_message'))
            self.state.update(status_message=message,health=health,status_at=now)
        self.save()


def main():
    publisher = Publisher()
    print('Ji Eun Discord monitoring started', flush=True)
    while True:
        try:
            publisher.tick()
        except (OSError, ValueError, RuntimeError) as exc:
            print('Discord monitor update failed: '+type(exc).__name__,flush=True)
        time.sleep(15)


if __name__ == '__main__':
    main()
