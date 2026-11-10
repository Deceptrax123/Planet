#!/usr/bin/env python3
"""Administrator installation of the owner-approved application maintenance path."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import tomllib
import yaml

SOURCE=Path(__file__).resolve().parent
PREFIX=Path('/opt/personal-agents')
HOME=Path('/var/lib/personal-agent')
WORK=HOME/'workspaces/scientific-assistants'
STATE=Path('/var/lib/personal-agent-maintenance')

def run(args,**kw):return subprocess.run(args,check=True,**kw)
def owned(path,uid=0,gid=0,mode=0o644):os.chown(path,uid,gid);path.chmod(mode)

def main():
    if os.getuid()!=0:raise SystemExit('Administrator setup only')
    try:build=pwd.getpwnam('personal-agent-build')
    except KeyError:
        run(['/usr/sbin/useradd','--system','--home-dir','/nonexistent','--shell','/usr/sbin/nologin','personal-agent-build']);build=pwd.getpwnam('personal-agent-build')
    agent=pwd.getpwnam('personal-agent')
    if WORK.exists():raise SystemExit('Workspace already exists; preserve its changes and update deliberately')
    # Only reviewed source, never runtime state or authentication.
    export=Path('/root/scientific-assistants-export')
    shutil.copytree(export,WORK,ignore=shutil.ignore_patterns('.git','__pycache__'))
    for directory in ['app','tests','maintenance','systemd','mission-control']:
        shutil.copytree(SOURCE/directory,WORK/directory,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
    for name in ['install-self-maintenance.py','SELF-MAINTENANCE.md','self-maintenance-policy.txt']:
        shutil.copy2(SOURCE/name,WORK/name)
    # The bridge is pinned source only. No npm dependencies, QR state or session files.
    bridge=WORK/'whatsapp-bridge';bridge.mkdir(exist_ok=True)
    for path in (PREFIX/'whatsapp-bridge').iterdir():
        if path.is_file() and path.suffix in {'.js','.mjs','.json'}:shutil.copy2(path,bridge/path.name)
    for path in [WORK,*WORK.rglob('*')]:owned(path,agent.pw_uid,agent.pw_gid,0o700 if path.is_dir() else 0o600)
    instructions=(WORK/'AGENTS.md').read_text()
    instructions+='\n- Owner authorizes autonomous application self-maintenance. Read SELF-MAINTENANCE.md and use the scoped maintenance MCP. Do not read /root or ask the owner for sudo to edit/deploy supported application files. Root policy and credentials remain protected.\n'
    (WORK/'AGENTS.md').write_text(instructions)
    env={**os.environ,'HOME':str(HOME),'GIT_CONFIG_NOSYSTEM':'1'}
    base=['/usr/sbin/runuser','-u','personal-agent','--','/usr/bin/git','-C',str(WORK)]
    for args in [['init','-b','main'],['config','user.name','Ji Eun and Ji An'],['config','user.email','scientific-assistants@localhost'],['remote','add','origin','git@github.com:Deceptrax123/scientific-assistants.git'],['add','.'],['commit','-m','Snapshot deployed assistant source and maintenance tools']]:run(base+args,env=env,stdout=subprocess.DEVNULL)
    (PREFIX/'maintenance').mkdir(exist_ok=True)
    for name in ['service.py','protocol.py','mcp.py','run_checks.py']:
        target=PREFIX/'maintenance'/name;shutil.copy2(SOURCE/'maintenance'/name,target);owned(target)
    owned(PREFIX/'maintenance',mode=0o755)
    # Stop root control from importing or executing replaceable app modules as root.
    shutil.copy2(SOURCE/'app/control.py',PREFIX/'app/control.py');owned(PREFIX/'app/control.py')
    STATE.mkdir(exist_ok=True);owned(STATE,0,build.pw_gid,0o750)
    (STATE/'candidates').mkdir(exist_ok=True);owned(STATE/'candidates',0,build.pw_gid,0o750)
    baseline={p.relative_to(WORK).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in WORK.rglob('*') if p.is_file() and '.git' not in p.parts}
    (STATE/'source-baseline.json').write_text(json.dumps(baseline));owned(STATE/'source-baseline.json',mode=0o600)
    policy=(SOURCE/'self-maintenance-policy.txt').read_text()
    configs=[HOME/'.hermes/config.yaml',*sorted((HOME/'.hermes/profiles').glob('*/config.yaml'))]
    for path in configs:
        config=yaml.safe_load(path.read_text());config.setdefault('mcp_servers',{})['maintenance']={'command':'/usr/bin/python3','args':[str(PREFIX/'maintenance/mcp.py')],'timeout':65,'connect_timeout':20}
        config.setdefault('agent',{})['system_prompt']=config['agent'].get('system_prompt','')+'\n\n'+policy
        path.write_text(yaml.safe_dump(config,sort_keys=False,allow_unicode=True));owned(path,agent.pw_uid,agent.pw_gid,0o600)
        soul=path.parent/'SOUL.md'
        if soul.exists():soul.write_text(soul.read_text()+'\n\n'+policy)
    config=HOME/'codex/config.toml';text=config.read_text()
    if '[mcp_servers.maintenance]' not in text:text+='\n[mcp_servers.maintenance]\ncommand = "/usr/bin/python3"\nargs = ["/opt/personal-agents/maintenance/mcp.py"]\nstartup_timeout_sec = 20.0\ntool_timeout_sec = 65.0\n'
    config.write_text(text)
    # Native teammate roles can find the checkout and use the same maintenance tools.
    for path in (HOME/'codex/agents').glob('*.toml'):
        text=path.read_text();data=tomllib.loads(text)
        text='\n'.join(('developer_instructions = '+json.dumps(data['developer_instructions']+'\n\n'+policy)) if line.startswith('developer_instructions =') else line for line in text.splitlines())+'\n'
        path.write_text(text)
    unit='personal-agent-maintenance.service';shutil.copy2(SOURCE/'systemd'/unit,Path('/etc/systemd/system')/unit)
    run(['/usr/bin/systemctl','daemon-reload']);run(['/usr/bin/systemctl','enable','--now',unit])
    print('Maintenance service installed; source checkout and MCP are ready. Gateway reload follows an idle check.')

if __name__=='__main__':main()
