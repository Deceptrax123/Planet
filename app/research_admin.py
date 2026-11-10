"""Interactive server-console setup; never asks for auth codes in Discord/chat."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from research_broker import HOME, SDK, PROFILE, PROJECT, SUBJECT, POOL, HOSTS, Backend, SOCKET
from assistant_broker import request


def main():
    parser=argparse.ArgumentParser(description='Ji Eun research-server setup (use the server terminal)')
    parser.add_argument('action',choices=['login','_login','status','probe','trust','inventory'])
    parser.add_argument('host',nargs='?')
    args=parser.parse_args()
    if os.geteuid()==0:
        action='_login' if args.action=='login' else args.action
        os.execvp('runuser',['runuser','-u','personal-agent-research','--','env',
            'HOME='+str(HOME),'CLOUDSDK_CONFIG='+str(HOME/'.config/gcloud'),
            sys.executable,__file__,action,*([args.host] if args.host else [])])
    if args.action=='_login':
        if not sys.stdin.isatty(): raise SystemExit('Run login interactively in the server terminal')
        print('Sign in with your AWS identity '+SUBJECT+'. Paste the returned result ONLY into this terminal.\n',flush=True)
        result=subprocess.run([SDK,'auth','login','--configuration='+PROFILE,
            '--login-config='+str(HOME/'config/lossfunk-workforce-login.json'),'--no-browser'])
        if result.returncode: raise SystemExit(result.returncode)
        try:
            Backend().identity(token=True)
        except ValueError:
            print('The signed-in identity does not match the owner. Research access remains blocked.')
            raise SystemExit(1)
        print('Verified owner workforce identity. Research login is ready for up to eight hours.')
    elif args.action=='trust':
        # Import PUBLIC host keys exported from the owner's existing trusted Mac.
        allowed={'compute.'+h['id'] for h in HOSTS.values()}
        lines=[]
        for line in sys.stdin:
            if not line.strip() or line.startswith('#'):continue
            fields=line.split()
            if len(fields)<3 or fields[0] not in allowed or fields[1] not in {'ssh-ed25519','ssh-rsa','ecdsa-sha2-nistp256'}:
                raise SystemExit('Only public host-key entries for the two registered instance aliases are accepted')
            import base64
            try:base64.b64decode(fields[2],validate=True)
            except ValueError:raise SystemExit('Invalid public host key')
            lines.append(' '.join(fields[:3]))
        if not lines:raise SystemExit('No matching public host-key entries supplied')
        path=HOME/'.ssh/google_compute_known_hosts'
        old=path.read_text().splitlines() if path.exists() else []
        incoming={line.split()[0]:set() for line in lines}
        for line in lines:incoming[line.split()[0]].add(line)
        for alias,entries in incoming.items():
            existing={line for line in old if line.split() and line.split()[0]==alias}
            if existing and not existing.issubset(entries):
                raise SystemExit('Host key differs from an existing trusted entry; inspect before replacing')
        path.write_text('\n'.join(sorted(set(old+lines)))+'\n');path.chmod(0o600)
        print('Imported public host keys. No private key or credential was imported.')
    elif args.action=='inventory':
        backend=Backend();backend.identity(token=True)
        rows=json.loads(backend.cloud(['compute','instances','list','--format=json']))
        print(json.dumps([{'name':r['name'],'id':r['id'],'zone':r['zone'].split('/')[-1],'status':r['status'],
                           'labels':r.get('labels',{})} for r in rows],indent=2))
        print('Inventory only. New instances must be checked against owner/project context before adding to the SSH allowlist.')
    else:
        method='research_probe' if args.action=='probe' else 'research_status'
        print(json.dumps(request(method,{'host':args.host} if args.action=='probe' else {},socket_path=SOCKET,timeout=125),indent=2))


if __name__=='__main__':main()
