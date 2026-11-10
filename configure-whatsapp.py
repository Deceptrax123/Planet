#!/usr/bin/env python3
"""Root terminal setup for Ji Eun's owner-only WhatsApp self-chat.

QR/device credentials remain in the server terminal and private service home.
No history import, group admission, number provisioning or third-party sends.
"""
import argparse
import fcntl
import getpass
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import tempfile
import time
import urllib.request
import yaml

HOME = Path('/var/lib/personal-agent')
PROFILE = HOME/'.hermes'
SESSION = PROFILE/'whatsapp/session'
BRIDGE = Path('/opt/personal-agents/whatsapp-bridge/bridge.js')
NODE = '/opt/personal-agents/bin/node'


def phone(value):
    value = value.strip().removeprefix('+').replace(' ','').replace('-','')
    if not re.fullmatch(r'[1-9][0-9]{6,14}',value):
        raise ValueError('Enter your phone number with country code, e.g. 919876543210')
    return value


def private_write(path, text, user='personal-agent'):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    account = pwd.getpwnam(user)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.whatsapp-')
    try:
        with os.fdopen(fd,'w') as stream:
            os.fchmod(stream.fileno(),0o600)
            os.fchown(stream.fileno(),account.pw_uid,account.pw_gid)
            stream.write(text)
        os.replace(temporary,path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def save_env(values):
    path = PROFILE/'.env'
    lines = path.read_text().splitlines() if path.exists() else []
    # Preserve all unrelated provider/settings lines without printing them.
    keys = set(values)
    lines = [line for line in lines if line.partition('=')[0].strip().removeprefix('export ') not in keys]
    private_write(path,'\n'.join(lines+[key+'='+str(value) for key,value in values.items()])+'\n')


def linked_phone():
    try:
        data = json.loads((SESSION/'creds.json').read_text())
        # Baileys' QR configureSuccessfulPairing saves a signed account and me;
        # its legacy registered flag remains false even after connection=open.
        if not data.get('account') or not data.get('me',{}).get('id'):
            return None
        return phone(re.split(r'[:@]',data.get('me',{}).get('id',''))[0])
    except (OSError,ValueError,TypeError):
        return None


def activate(owner):
    cfg_path = PROFILE/'config.yaml'
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg.setdefault('platforms',{}).setdefault('whatsapp',{}).update(
        enabled=True, allow_from=[owner], allow_admin_from=[owner],
        gateway_restart_notification=False,
        extra={'bridge_port':3000,'bridge_script':str(BRIDGE),'session_path':str(SESSION),
               'dm_policy':'allowlist','allow_from':[owner], 'group_policy':'disabled',
               'group_allow_from':[], 'reply_prefix':'Ji Eun: ', 'send_read_receipts':False})
    cfg.setdefault('whatsapp',{}).update(unauthorized_dm_behavior='ignore',group_policy='disabled',reply_prefix='Ji Eun: ')
    private_write(cfg_path,yaml.safe_dump(cfg,sort_keys=False))
    # Only the main profile owns this linked device. Never inherit it into Ji An.
    for path in (PROFILE/'profiles').glob('*/config.yaml'):
        other = yaml.safe_load(path.read_text())
        other.setdefault('platforms',{}).setdefault('whatsapp',{})['enabled']=False
        private_write(path,yaml.safe_dump(other,sort_keys=False))
    save_env({'WHATSAPP_MODE':'self-chat','WHATSAPP_ENABLED':'true',
              'WHATSAPP_ALLOWED_USERS':owner,'WHATSAPP_ALLOW_ALL_USERS':'false',
              'WHATSAPP_GROUP_POLICY':'disabled','WHATSAPP_FROM_OWNER':'false',
              'WHATSAPP_DEBUG':'false'})
    metadata={'enabled':True,'mode':'self-chat','owner_jid':owner+'@s.whatsapp.net'}
    private_write(Path('/var/lib/personal-agent-data/whatsapp.json'),json.dumps(metadata)+'\n','personal-agent-data')
    private_write(HOME/'.config/whatsapp.json',json.dumps(metadata)+'\n')
    # Wait for the current Discord turn rather than interrupt it.
    for _ in range(300):
        state=json.loads((PROFILE/'gateway_state.json').read_text())
        if not state.get('active_agents'):
            subprocess.run(['systemctl','restart','personal-agent-gateway'],check=True)
            break
        time.sleep(1)
    else:
        raise ValueError('Pairing saved, but Ji Eun is still busy. Rerun this helper with --finish after her turn ends.')
    for _ in range(60):
        try:
            with urllib.request.urlopen('http://127.0.0.1:3000/health',timeout=2) as response:
                health=json.load(response)
            if health.get('status')=='connected' and health.get('session')==str(SESSION):
                print('\nJi Eun is connected to WhatsApp. Open Message yourself and send: Hi Ji Eun.')
                print('Only your self-chat is admitted. No groups or other chats are being monitored.')
                print('WhatsApp reminders are ready; Discord stays connected. No voice is enabled.')
                return
        except (OSError,ValueError):
            pass
        time.sleep(1)
    raise ValueError('Pairing saved; bridge connection is still pending. Check the private monitor before messaging.')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--finish',action='store_true',help='Activate an already paired and verified self-chat account')
    parser.add_argument('--retry',action='store_true',help='Retry QR pairing using the owner number already entered in the terminal')
    args=parser.parse_args()
    if os.geteuid()!=0 or (not args.finish and not os.isatty(0)):
        raise SystemExit('Run sudo personal-agent-whatsapp-setup in this server’s interactive terminal.')
    with open('/run/lock/personal-agent-whatsapp-setup.lock','w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            existing=linked_phone()
            if args.finish or args.retry:
                if args.finish and not existing:raise ValueError('No completed WhatsApp pairing; run the helper interactively first.')
                saved=json.loads((HOME/'.config/whatsapp-pairing.json').read_text())
                owner=phone(saved['owner'])
            else:
                print('Ji Eun • WhatsApp Message yourself setup')
                print('Use YOUR existing personal WhatsApp account. No new number or paid API is created.')
                print('Enter country code + number as digits (India: 91 then 10 digits). Typing stays invisible; press Enter when done.')
                owner=phone(getpass.getpass('Your personal WhatsApp number, with country code (hidden): '))
                private_write(HOME/'.config/whatsapp-pairing.json',json.dumps({'owner':owner})+'\n')
            if existing and existing!=owner:
                raise ValueError('The existing linked account does not match the owner number. It was left untouched.')
            if not existing:
                if args.finish:raise ValueError('Pairing required.')
                save_env({'WHATSAPP_MODE':'self-chat','WHATSAPP_ENABLED':'false','WHATSAPP_ALLOWED_USERS':owner})
                SESSION.mkdir(parents=True,exist_ok=True,mode=0o700)
                user=pwd.getpwnam('personal-agent')
                for path in [SESSION.parent,SESSION]:os.chown(path,user.pw_uid,user.pw_gid);path.chmod(0o700)
                print('\nOn your phone: WhatsApp → Settings → Linked Devices → Link a Device.')
                print('Scan the QR below. Keep the QR and any login confirmation in this terminal.\n',flush=True)
                env=dict(os.environ,HOME=str(HOME),HERMES_HOME=str(PROFILE),PATH='/opt/personal-agents/bin:/usr/bin:/bin',WHATSAPP_MODE='self-chat',WHATSAPP_ALLOWED_USERS=owner,WHATSAPP_GROUP_POLICY='disabled',WHATSAPP_DEBUG='false')
                subprocess.run(['/usr/sbin/runuser','-u','personal-agent','--',NODE,str(BRIDGE),'--pair-only','--session',str(SESSION),'--mode','self-chat'],env=env,cwd=HOME,check=True)
            if linked_phone()!=owner:
                raise ValueError('Pairing is incomplete or belongs to another number; WhatsApp was not enabled.')
            activate(owner)
        except (ValueError,OSError,subprocess.CalledProcessError) as exc:
            raise SystemExit(str(exc)) from None


if __name__=='__main__':main()
