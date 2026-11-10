"""Create owner-private Discord monitor channels, then install their publisher."""
from pathlib import Path
import json,os,pwd,shutil,subprocess,urllib.request,urllib.error
secret=json.loads(Path('/root/.config/personal-agents/discord.json').read_text())
headers={'Authorization':'Bot '+secret['bot_token'],'Content-Type':'application/json','User-Agent':'JiEunSetup/1.0'}
def api(method,path,data=None):
 req=urllib.request.Request('https://discord.com/api/v10'+path,data=json.dumps(data).encode() if data is not None else None,headers=headers,method=method)
 try:
  with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)
 except urllib.error.HTTPError as exc:
  raise SystemExit('Discord setup HTTP '+str(exc.code)+'. Check bot Manage Channels permission.') from None
guild='1248530615662284810';channels=api('GET','/guilds/'+guild+'/channels');saved={}
for name,purpose in [('agent-activity','Ji Eun teammate and swarm progress. Plain-language milestones; detailed tool logs stay in the private server dashboard.'),('ji-eun-status','Ji Eun service health, reminder delivery, and failures. Updated automatically.')]:
 matches=[c for c in channels if c['name']==name and c['type']==0]
 overwrites=[{'id':guild,'type':0,'deny':'1024','allow':'0'},{'id':secret['owner_id'],'type':1,'allow':'68608','deny':'0'},{'id':secret['bot_id'],'type':1,'allow':'84992','deny':'0'}]
 if matches:
  channel=api('PATCH','/channels/'+matches[0]['id'],{'topic':purpose,'permission_overwrites':overwrites})
 else:channel=api('POST','/guilds/'+guild+'/channels',{'name':name,'type':0,'topic':purpose,'permission_overwrites':overwrites})
 saved[name]=channel['id'];print(name,'https://discord.com/channels/'+guild+'/'+channel['id'])
p=Path('/var/lib/personal-agent/.config/discord-monitor.json');p.parent.mkdir(exist_ok=True);p.write_text(json.dumps(saved));p.chmod(0o600)
u=pwd.getpwnam('personal-agent');os.chown(p,u.pw_uid,u.pw_gid);os.chown(p.parent,u.pw_uid,u.pw_gid)
shutil.copy2('/root/personal-agents/app/discord_monitor.py','/opt/personal-agents/app/discord_monitor.py')
Path('/etc/systemd/system/personal-agent-discord-monitor.service').write_text('''[Unit]
Description=Ji Eun Discord activity and health channels
After=network-online.target personal-agent-data.service
Wants=network-online.target
[Service]
User=personal-agent
Group=personal-agent
Environment=HOME=/var/lib/personal-agent
LoadCredential=discord_token:/etc/personal-agents/discord.token
ExecStart=/usr/bin/python3 /opt/personal-agents/app/discord_monitor.py
WorkingDirectory=/opt/personal-agents/app
Restart=on-failure
RestartSec=15
UMask=0077
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadWritePaths=/var/lib/personal-agent/.config
MemoryMax=256M
TasksMax=32
[Install]
WantedBy=multi-user.target
''')
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','enable','--now','personal-agent-discord-monitor'],check=True)
