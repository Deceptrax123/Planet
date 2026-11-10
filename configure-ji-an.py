#!/usr/bin/env python3
"""Join Ji An to the owner's Discord server using a hidden terminal-only token."""
import getpass
import argparse
import json
import os
from pathlib import Path
import pwd
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import yaml

GUILD='1248530615662284810'
OWNER='562571259758772254'
JI_EUN='1569046625853251614'
HOME=Path('/var/lib/personal-agent')
ROOT=Path('/opt/personal-agents')
# Text, attachments, reactions and public thread access only; no voice/admin rights.
PERMISSIONS=sum(1<<bit for bit in [6,10,11,14,15,16,35,38])


def api(token,path,method='GET',body=None):
    req=urllib.request.Request('https://discord.com/api/v10'+path,
        data=json.dumps(body).encode() if body is not None else None,method=method,
        headers={'Authorization':'Bot '+token,'Content-Type':'application/json','User-Agent':'JiAnSetup/1.0'})
    try:
        with urllib.request.urlopen(req,timeout=25) as r:
            return json.load(r) if r.status!=204 else None
    except urllib.error.HTTPError as exc:
        raise ValueError('Discord HTTP '+str(exc.code)) from None


def private_write(path,content):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,tmp=tempfile.mkstemp(prefix='.ji-an-',dir=path.parent)
    with os.fdopen(fd,'w') as out:os.fchmod(out.fileno(),0o600);out.write(content)
    os.replace(tmp,path)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--finish',action='store_true',help='Finish an already entered token after the bot joined; never reads a token from stdin')
    args=parser.parse_args()
    path=Path('/etc/personal-agents/ji-an-discord.token')
    if os.geteuid()!=0 or (not os.isatty(0) and not (args.finish and path.exists())):
        raise SystemExit('Run sudo personal-agent-add-jian in this server\'s interactive terminal')
    token=path.read_text().strip() if path.exists() else getpass.getpass('Ji An Discord BOT token (hidden): ').strip()
    if not token or any(c.isspace() for c in token):raise SystemExit('Expected one bot token')
    try:
        bot=api(token,'/users/@me')
        if not bot.get('bot') or bot['id']==JI_EUN:
            raise ValueError('Use Ji An\'s separate bot token; Ji Eun must keep her own identity')
        private_write(path,token+'\n')
        private_write(Path('/etc/personal-agents/ji-an-discord.json'),json.dumps({'bot_id':bot['id'],'owner_id':OWNER,'guild_id':GUILD})+'\n')
        invite='https://discord.com/oauth2/authorize?'+urllib.parse.urlencode({'client_id':bot['id'],'scope':'bot applications.commands','permissions':str(PERMISSIONS),'guild_id':GUILD,'disable_guild_select':'true'})
        while True:
            guilds=api(token,'/users/@me/guilds')
            if any(g['id']==GUILD for g in guilds):break
            if args.finish:raise ValueError('Ji An has not joined the owner server yet; finish the printed invite first')
            print('\nAdd Ji An to your existing server using:\n'+invite+'\n',flush=True)
            input('After adding the bot, press Enter here to continue: ')
        api(token,'/users/@me','PATCH',{'username':'Ji An'})
        primary=Path('/etc/personal-agents/discord.token').read_text().strip()
        # Give Ji An access to the same explicitly bot-enabled private channels.
        channels=api(primary,'/guilds/'+GUILD+'/channels')
        granted=[]
        for ch in channels:
            overwrites=ch.get('permission_overwrites',[])
            primary_member=next((p for p in overwrites if p.get('id')==JI_EUN and p.get('type')==1),None)
            monitor=ch['id'] in {'1569058485033894160','1569058490692149299'}
            if not primary_member and not monitor:continue
            # Mirror only the ordinary text permissions needed for conversation.
            allow=int(primary_member.get('allow','0'))&PERMISSIONS if primary_member else PERMISSIONS
            deny=int(primary_member.get('deny','0'))&PERMISSIONS if primary_member else 0
            try:
                api(primary,'/channels/'+ch['id']+'/permissions/'+bot['id'],'PUT',
                    {'id':bot['id'],'type':1,'allow':str(allow),'deny':str(deny)})
                granted.append(ch['id'])
            except ValueError as exc:
                if str(exc)!='Discord HTTP 403':raise
                print('Private channel '+ch['id']+': add Ji An in its Discord Permissions to let her read it. Shared monitoring still works through Ji Eun.')
        profile=HOME/'.hermes/profiles/ji-an'
        cfg=yaml.safe_load((profile/'config.yaml').read_text())
        cfg['platforms']['discord'].update(enabled=True,allow_from=[OWNER],allow_admin_from=[OWNER],allow_bots='none',require_mention=True,gateway_restart_notification=False)
        cfg['kanban'].update(dispatch_in_gateway=False,notify_in_gateway=False)
        cfg.setdefault('gateway',{})['standalone']=True
        # Schedules stay profile-local and empty: Ji Eun owns the daily brief/proactive jobs.
        cfg['model']['default']='gpt-6.1-sol'
        cfg.setdefault('agent',{})['system_prompt']=(profile/'SOUL.md').read_text()
        (profile/'config.yaml').write_text(yaml.safe_dump(cfg,sort_keys=False))
        u=pwd.getpwnam('personal-agent');os.chown(profile/'config.yaml',u.pw_uid,u.pw_gid);(profile/'config.yaml').chmod(0o600)
        metadata=HOME/'.config/ji-an-discord.json'
        private_write(metadata,json.dumps({'bot_id':bot['id'],'owner_id':OWNER,'guild_id':GUILD,'shared_channels':granted})+'\n')
        os.chown(metadata,u.pw_uid,u.pw_gid)
        subprocess.run(['systemctl','daemon-reload'],check=True)
        subprocess.run(['systemctl','enable','--now','personal-agent-ji-an'],check=True)
        print('\nJi An is configured. Mention @Ji An in your server, or DM her. Only your owner account can start work.')
        print('Ji Eun and Ji An share structured memory, research access and the task board. Tokens were not printed.')
    except (ValueError,OSError) as exc:
        raise SystemExit(str(exc)+'. Setup stopped; rerun the helper after resolving it.') from None


if __name__=='__main__':main()
