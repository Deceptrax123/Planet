#!/usr/bin/env python3
"""Add Ji An and the isolated SSH broker without replacing live auth/config."""
from pathlib import Path
import json
import os
import pwd
import re
import shutil
import subprocess
import tomllib
import yaml

SOURCE=Path(__file__).resolve().parent
PREFIX=Path('/opt/personal-agents')
HOME=Path('/var/lib/personal-agent')
user=pwd.getpwnam('personal-agent')
if os.geteuid()!=0:raise SystemExit('Run as server administrator')
for name in ['research_admin.py','research_broker.py','research_remote.py','assistant_broker.py','assistant_mcp.py','monitor.py','mission_control.py','discord_monitor.py','backup.py','control.py']:
    shutil.copy2(SOURCE/'app'/name,PREFIX/'app'/name)
for name in ['index.html','app.js','styles.css']:
    shutil.copy2(SOURCE/'mission-control'/name,PREFIX/'mission-control'/name)
shutil.copy2(SOURCE/'systemd/personal-agent-research.service','/etc/systemd/system/personal-agent-research.service')

policy=(SOURCE/'research-policy.txt').read_text()+'\n'+(SOURCE/'routing-policy.txt').read_text()
profiles=HOME/'.hermes/profiles'
new=profiles/'ji-an'
if not new.exists():
    new.mkdir()
    shutil.copy2(profiles/'research/config.yaml',new/'config.yaml')
    shutil.copy2(profiles/'research/SOUL.md',new/'SOUL.md')
    shutil.copytree(profiles/'research/plugins',new/'plugins')
for p in [HOME/'.hermes/SOUL.md',*profiles.glob('*/SOUL.md')]:
    s=p.read_text()
    if 'RESEARCH TEAM: Ji An (ji-an)' in s:s=s[:s.index('RESEARCH TEAM: Ji An (ji-an)')].rstrip()
    s+='\n\n'+policy
    if p.parent==new and 'Your name is Ji An' not in s:
        s+='\nYour name is Ji An. You own scientific interpretation and research-method review. Ji Eun coordinates owner conversation. Use Sol for substantive interpretation.\n'
    p.write_text(s);os.chown(p,user.pw_uid,user.pw_gid)
for p in [HOME/'.hermes/config.yaml',*profiles.glob('*/config.yaml')]:
    cfg=yaml.safe_load(p.read_text())
    cfg['mcp_servers']['personal']['timeout']=130
    cfg.setdefault('agent',{})['system_prompt']=(p.parent/'SOUL.md').read_text()
    if p.parent==new:cfg['model']['default']='gpt-6.1-sol'
    p.write_text(yaml.safe_dump(cfg,sort_keys=False));p.chmod(0o600);os.chown(p,user.pw_uid,user.pw_gid)
for p in new.rglob('*'):
    os.chown(p,user.pw_uid,user.pw_gid)
os.chown(new,user.pw_uid,user.pw_gid)

agents=HOME/'codex/agents'
if not (agents/'ji-an.toml').exists():shutil.copy2(agents/'research.toml',agents/'ji-an.toml')
for p in agents.glob('*.toml'):
    d=tomllib.loads(p.read_text())
    if 'RESEARCH TEAM: Ji An (ji-an)' in d['developer_instructions']:
        d['developer_instructions']=d['developer_instructions'][:d['developer_instructions'].index('RESEARCH TEAM: Ji An (ji-an)')].rstrip()
    d['developer_instructions']+='\n\n'+policy
    if p.stem=='ji-an':
        d['model']='gpt-6.1-sol'
        if 'Your name is Ji An' not in d['developer_instructions']:
            d['developer_instructions']+='\nYour name is Ji An. Own scientific interpretation, uncertainty and methodological review; Ji Eun coordinates the conversation.\n'
    p.write_text('\n'.join(k+' = '+json.dumps(v) for k,v in d.items())+'\n');os.chown(p,user.pw_uid,user.pw_gid)
config=HOME/'codex/config.toml'
s=config.read_text()
if 'ji-an' not in tomllib.loads(s).get('agents',{}):
    s+='\n[agents.ji-an]\ndescription = "Ji An: scientific interpretation, experiment analysis, statistics and methodological review."\nconfig_file = "/var/lib/personal-agent/codex/agents/ji-an.toml"\n'
pattern=r'(\[mcp_servers\.personal\]\n)(.*?)(?=\n\[|\Z)'
def timeout(m):
    body=m[2]
    if re.search(r'^tool_timeout_sec\s*=',body,re.M):body=re.sub(r'^tool_timeout_sec\s*=.*$', 'tool_timeout_sec = 130.0',body,flags=re.M)
    else:body+='\ntool_timeout_sec = 130.0\n'
    return m[1]+body
s=re.sub(pattern,timeout,s,flags=re.S)
tomllib.loads(s)
config.write_text(s);os.chown(config,user.pw_uid,user.pw_gid)
base=['runuser','-u','personal-agent','--','env','HOME='+str(HOME),
      'CODEX_HOME='+str(HOME/'codex'),'PATH=/var/lib/personal-agent/.local/bin:/opt/personal-agents/bin:/usr/bin:/bin',
      '/var/lib/personal-agent/.local/bin/hermes']
for profile in ['', *[p.name for p in profiles.iterdir() if p.is_dir() and (p/'config.yaml').exists()]]:
    subprocess.run(base+(['--profile',profile] if profile else [])+['sessions','refresh-prompts','--json'],cwd=HOME,check=True)
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','restart','personal-agent-data'],check=True)
subprocess.run(['systemctl','enable','--now','personal-agent-research'],check=True)
subprocess.run(['systemctl','restart','personal-agent-research'],check=True)
subprocess.run(['systemctl','restart','personal-agent-mission-control'],check=True)
state=HOME/'.hermes/gateway_state.json'
active=json.loads(state.read_text()).get('active_agents') if state.exists() else None
if active==0:
    subprocess.run(['systemctl','restart','personal-agent-gateway','personal-agent-monitor'],check=True)
    print('Ji An and research tools loaded; gateway restarted while idle.')
else:
    print('Ji An and research tools installed; active owner turn preserved. Gateway reload remains pending.')
print('Research SSH broker installed. Current connection state: personal-agent-research-setup status. No experiments launched by this installer.')
