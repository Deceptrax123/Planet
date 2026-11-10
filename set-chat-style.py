from pathlib import Path
import subprocess,pwd,sys
u=pwd.getpwnam('personal-agent')
base=['runuser','-u','personal-agent','--','env','HOME='+u.pw_dir,'CODEX_HOME='+u.pw_dir+'/codex','PATH=/var/lib/personal-agent/.local/bin:/opt/personal-agents/bin:/usr/bin:/bin','/var/lib/personal-agent/.local/bin/hermes']
settings={'interim_assistant_messages':'false','long_running_notifications':'false','busy_ack_detail':'false','busy_steer_ack_enabled':'false','show_reasoning':'false'}
for profile in ['', 'inbox','planner','research','everyday','subscriptions']:
 for key,value in settings.items():
  p=subprocess.run(base+(['--profile',profile] if profile else [])+['config','set','display.platforms.discord.'+key,value],cwd=u.pw_dir,capture_output=True,text=True,timeout=30)
  if p.returncode:raise SystemExit(p.stderr[-300:] or p.stdout[-300:])
 print('Natural final-answer display:',profile or 'coordinator',flush=True)
text='Discord style: speak naturally, warmly and directly, like a thoughtful human teammate. Do useful context and memory checks silently. Never narrate internal operations or say things like let me check your context, I will retrieve your memory, routing to a specialist, MCP, or tool command details in ordinary chat. Skip stock acknowledgments and filler; lead with the useful answer. Do not force slang or imitate typos. Use concise prose appropriate to the conversation. Progress and agent operations belong in the monitor channels. Only mention an unavailable source or missing constraint when it materially affects the answer; ask one clear question when needed. This is a text style preference; voice remains disabled.'
for p in list(Path('/var/lib/personal-agent/.hermes').glob('**/SOUL.md'))+list(Path('/var/lib/personal-agent/codex/agents').glob('*.toml')):
 s=p.read_text()
 if 'Discord style: speak naturally' in s:continue
 if p.suffix=='.toml':
  import json,tomllib
  data=tomllib.loads(s);data['developer_instructions']+='\n\n'+text+'\n'
  s='\n'.join(k+' = '+json.dumps(v) for k,v in data.items())+'\n'
 else:s+='\n\n'+text+'\n'
 p.write_text(s)
sys.path.insert(0,'/opt/personal-agents/app')
from assistant_broker import request
request('memory_record',{'topic':'preferences/communication','text':'Discord replies should sound natural, human, warm and direct. Remove context-check narration, technical tool traces and routine filler. Put agent progress in dedicated monitor channels. Voice remains disabled.','source':'Direct user instruction in this chat on 2026-11-08','confirmed':True,'fact_key':'discord-chat-style','importance':'high'})
subprocess.run(['systemctl','restart','personal-agent-gateway','personal-agent-monitor'],check=True)
print('Style saved and active.')
