#!/usr/bin/env python3
"""Install reviewed WhatsApp integration code; interactive pairing is separate."""
import os
import hashlib
from pathlib import Path
import pwd
import shutil
import subprocess
import yaml

SOURCE=Path('/root/personal-agents')
ROOT=Path('/opt/personal-agents')
HOME=Path('/var/lib/personal-agent')
if os.geteuid()!=0:raise SystemExit('Run as server administrator')
bridge=ROOT/'whatsapp-bridge'
if not bridge.exists():
    shutil.copytree(HOME/'setup/whatsapp-bridge',bridge,symlinks=True)
    # Dependencies are root-owned after their unprivileged, script-free build.
    for path in [bridge,*bridge.rglob('*')]:
        if not path.is_symlink():os.chown(path,0,0)
subprocess.run(['/usr/bin/python3',str(SOURCE/'patch-whatsapp-pairing.py')],check=True)
# Hermes verifies this stamp before accepting a prepared dependency tree.
(bridge/'node_modules/.hermes-pkg-hash').write_text(hashlib.sha256((bridge/'package.json').read_bytes()).hexdigest()[:16])
for name in ['assistant_store.py','assistant_broker.py','assistant_mcp.py','reminder_scheduler.py','whatsapp_delivery.py','monitor.py','discord_monitor.py']:
    shutil.copy2(SOURCE/'app'/name,ROOT/'app'/name)
shutil.copy2(SOURCE/'mission-control/app.js',ROOT/'mission-control/app.js')
shutil.copy2(SOURCE/'configure-whatsapp.py',ROOT/'configure-whatsapp.py')
entry=Path('/usr/local/bin/personal-agent-whatsapp-setup')
entry.write_text('#!/bin/sh\nexec /usr/bin/python3 /opt/personal-agents/configure-whatsapp.py "$@"\n')
entry.chmod(0o755)
policy=(SOURCE/'whatsapp-policy.txt').read_text()
user=pwd.getpwnam('personal-agent')
for soul in [HOME/'.hermes/SOUL.md',*sorted((HOME/'.hermes/profiles').glob('*/SOUL.md'))]:
    text=soul.read_text()
    if policy not in text:
        soul.write_text(text+'\n\n'+policy)
    os.chown(soul,user.pw_uid,user.pw_gid)
    config=soul.parent/'config.yaml'
    cfg=yaml.safe_load(config.read_text())
    cfg.setdefault('agent',{})['system_prompt']=soul.read_text()
    # Pairing enables only Ji Eun later, never leave an unpaired platform live.
    if not (HOME/'.hermes/whatsapp/session/creds.json').exists() or soul.parent!=HOME/'.hermes':
        cfg.setdefault('platforms',{}).setdefault('whatsapp',{})['enabled']=False
    config.write_text(yaml.safe_dump(cfg,sort_keys=False));config.chmod(0o600)
    os.chown(config,user.pw_uid,user.pw_gid)
for path in (HOME/'codex/agents').glob('*.toml'):
    import tomllib,json
    cfg=tomllib.loads(path.read_text());instructions=cfg.get('developer_instructions','')
    if policy in instructions:continue
    cfg['developer_instructions']=instructions+'\n\n'+policy
    # Existing role TOML consists of simple scalar values; preserve every key.
    if not all(isinstance(v,(str,bool,int,float)) for v in cfg.values()):
        raise SystemExit('Unsupported nested role config; review before changing '+str(path))
    path.write_text('\n'.join(k+' = '+json.dumps(v) for k,v in cfg.items())+'\n')
    os.chown(path,user.pw_uid,user.pw_gid)
for service in ['personal-agent-data','personal-agent-reminders','personal-agent-mission-control','personal-agent-discord-monitor']:
    subprocess.run(['systemctl','restart',service],check=True)
print('WhatsApp integration installed. Pair with sudo personal-agent-whatsapp-setup in the server terminal.')
