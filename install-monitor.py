from pathlib import Path
import subprocess,shutil,secrets,os,pwd,sys
for name in ['mission_control.py','monitor.py','control.py']:
 shutil.copy2('/root/personal-agents/app/'+name,'/opt/personal-agents/app/'+name)
shutil.copytree('/root/personal-agents/mission-control','/opt/personal-agents/mission-control',dirs_exist_ok=True)
p=Path('/etc/personal-agents/monitor.password')
if not p.exists():
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as f:f.write(secrets.token_urlsafe(24)+'\n')
Path('/etc/systemd/system/personal-agent-mission-control.service').write_text('''[Unit]
Description=Ji Eun private live agent mission control
After=personal-agent-data.service
[Service]
Type=simple
User=personal-agent
Group=personal-agent
Environment=HOME=/var/lib/personal-agent
Environment=CODEX_HOME=/var/lib/personal-agent/codex
Environment=PATH=/var/lib/personal-agent/.local/bin:/opt/personal-agents/bin:/usr/bin:/bin
LoadCredential=monitor_password:/etc/personal-agents/monitor.password
ExecStart=/usr/bin/python3 /opt/personal-agents/app/mission_control.py
WorkingDirectory=/opt/personal-agents/app
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
ReadWritePaths=/var/lib/personal-agent
MemoryMax=384M
TasksMax=64
[Install]
WantedBy=multi-user.target
''')
u=pwd.getpwnam('personal-agent')
base=['runuser','-u','personal-agent','--','env','HOME='+u.pw_dir,'CODEX_HOME='+u.pw_dir+'/codex','PATH=/var/lib/personal-agent/.local/bin:/opt/personal-agents/bin:/usr/bin:/bin','XDG_RUNTIME_DIR=/run/user/'+str(u.pw_uid),'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/'+str(u.pw_uid)+'/bus','/var/lib/personal-agent/.local/bin/hermes']
for profile in ['', 'inbox','planner','research','everyday','subscriptions']:
 command=base+(['--profile',profile] if profile else [])+['config','set','display.platforms.discord.tool_progress','off']
 p=subprocess.run(command,cwd=u.pw_dir,capture_output=True,text=True,timeout=30)
 if p.returncode: print(p.stdout,p.stderr);raise SystemExit(p.returncode)
 print('Discord raw tool display disabled:',profile or 'coordinator')
for p in list(Path('/var/lib/personal-agent/.hermes').glob('**/SOUL.md'))+list(Path('/var/lib/personal-agent/codex/agents').glob('*.toml')):
 s=p.read_text()
 replacement='Keep Discord conversational: never echo raw MCP calls, tool commands, or JSON payloads there. Use short plain-language progress updates; detailed actions belong in the private server monitor.'
 if replacement not in s:
  sep='\\n\\n' if p.suffix=='.toml' else '\n\n'
  s=s.replace('Make work observable.',replacement+sep+'Make work observable.')
  p.write_text(s)
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','enable','--now','personal-agent-mission-control'],check=True)
subprocess.run(['systemctl','restart','personal-agent-gateway','personal-agent-monitor'],check=True)
sys.path.insert(0,'/opt/personal-agents/app')
from assistant_broker import request
print(request('memory_record',{'topic':'preferences/assistant','text':'The personal Discord assistant is named Ji Eun. Hide raw MCP calls and tool command traces in Discord; show useful plain-language progress there and detailed actions in the private server monitor.','source':'Direct owner instructions in this chat on 2026-11-08','confirmed':True,'fact_key':'assistant-name-and-display','importance':'high'}))
print('Mission control installed at localhost:9120; password kept in root-only file.')
