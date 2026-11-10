from pathlib import Path
import json,tomllib,subprocess,shutil,pwd,os
u=pwd.getpwnam('personal-agent')
policy='''Latest owner correction: Ji Eun may proactively start conversations and share important updates AT ANY TIME, including overnight. There is no conversation quiet-hour restriction, cooldown, daily/weekly message quota, or prescribed message frequency. This explicitly supersedes all earlier proactive quiet-hour and frequency limits. Reach out based on relevance, natural conversation, important developments, schedule changes or a useful thought. Do not force messages to fill a schedule. Keep source-event deduplication and expiry of stale updates. Standalone reminder settings and the daily 09:00 brief stay as separately configured. Images are welcome. No voice.'''
replacements={
 'During daytime, flag sourced urgent messages':'When useful, flag sourced urgent messages',
 'It enforces quiet hours, deduplication, cooldown and a maximum of four unsolicited alerts/day.':'It deduplicates source events and expires stale updates. Proactive conversation can happen at any time with no message quota.',
 'At most two casual starters per rolling week and one per day are enforced in code, within the four-total daily unsolicited-message budget.':'There is no fixed number or frequency of casual starters or proactive messages.',
 'During quiet hours 23:00–09:00 do not send unsolicited owner DMs.':'Proactive owner conversations are authorized at any time, including overnight.',
 'Quiet hours: 23:00–09:00 for\nproactive messages.':'Standalone reminder quiet hours: 23:00–09:00. Proactive conversations are authorized at any time.',
}
paths=list(Path('/var/lib/personal-agent/.hermes').glob('**/SOUL.md'))+list(Path('/var/lib/personal-agent/codex/agents').glob('*.toml'))
for p in paths:
 if p.suffix=='.toml':
  d=tomllib.loads(p.read_text());s=d['developer_instructions']
 else:s=p.read_text()
 for old,new in replacements.items():s=s.replace(old,new)
 if policy not in s:s+='\n\n'+policy+'\n'
 if p.suffix=='.toml':
  d['developer_instructions']=s;s='\n'.join(k+' = '+json.dumps(v) for k,v in d.items())+'\n'
 p.write_text(s);os.chown(p,u.pw_uid,u.pw_gid)
Path('/root/personal-agents/proactive-anytime-policy.txt').write_text(policy+'\n')
base=['runuser','-u','personal-agent','--','env','HOME='+u.pw_dir,'CODEX_HOME='+u.pw_dir+'/codex','PATH=/var/lib/personal-agent/.local/bin:/opt/personal-agents/bin:/usr/bin:/bin','/var/lib/personal-agent/.local/bin/hermes']
jobs=json.loads(Path('/var/lib/personal-agent/.hermes/cron/jobs.json').read_text())['jobs'];job=next(j for j in jobs if j['id']=='28dd0ad764ff')
s=job['prompt']
s=s.replace('First check current Asia/Kolkata time; outside 09:00–23:00 return exactly [SILENT], without reading external sources or notifying.','The owner authorizes proactive conversations at any time, including overnight, with no quiet window or fixed message frequency. This hourly job refreshes sources; it is not a timetable requiring messages. Check time only to make content relevant.')
s=s.replace("At most once a day, around the 12:15 or 18:15 check when useful, look for significant developments", "When useful, look for significant developments")
s=s.replace('No more than one compact owner message per check.','Combine related points naturally; there is no prescribed number of messages.')
s=s.replace('Quiet hours, four unsolicited messages/day, cooldown and two casual starters/week are enforced by code; explicit reminders/brief are separate.','There is no proactive quiet-hour rule, cooldown or daily/weekly message quota. Source-event deduplication and stale-alert expiry remain enforced; explicit reminders/brief are separate.')
p=subprocess.run(base+['cron','edit',job['id'],'--schedule','15 * * * *','--prompt',s],cwd=u.pw_dir,capture_output=True,text=True,timeout=45);print(p.stdout[-700:],p.stderr[-300:]);p.check_returncode()
for name in ['assistant_store.py','assistant_mcp.py','reminder_scheduler.py']:
 shutil.copy2('/root/personal-agents/app/'+name,'/opt/personal-agents/app/'+name)
subprocess.run(['systemctl','restart','personal-agent-data','personal-agent-reminders'],check=True)
state=json.loads(Path('/var/lib/personal-agent/.hermes/gateway_state.json').read_text())
if state.get('active_agents')==0:
 subprocess.run(['systemctl','restart','personal-agent-gateway','personal-agent-monitor'],check=True);print('Anytime outreach policy loaded while idle.')
else:print('Active conversation preserved; full policy loads at next restart.')
print('No proactive quiet-hour or frequency limits remain in the notification backend.')
