"""Enable only catalog-annotated read-only Notion/Slack tools for the assistant."""
import sys,json
from pathlib import Path
import tomllib
sys.path.insert(0,'/opt/personal-agents/app')
from codex_rpc import CodexRPC
APPS={'asdk_app_69c18c28f1188191bf5b8445c4ab0a2e':'Notion','asdk_app_69a1d78e929881919bba0dbda1f6436d':'Slack'}
c=CodexRPC(cwd='/var/lib/personal-agent/workspaces')
try:
 result=c.call('mcpServerStatus/list',{},timeout=60)
 allowed={a:[] for a in APPS}
 for server in result.get('data',[]):
  if server.get('name')!='codex_apps':continue
  for tool in server.get('tools',{}).values():
   meta=tool.get('_meta',{});app=meta.get('connector_id')
   if app in allowed and tool.get('annotations',{}).get('readOnlyHint') is True:
    name=meta.get('_codex_apps',{}).get('resource_uri','').rsplit('/',1)[-1]
    if name:
     allowed[app].append(name)
     allowed[app].append(tool['name'])
 p=Path('/var/lib/personal-agent/codex/config.toml');s=p.read_text();current=tomllib.loads(s)
 for app,names in allowed.items():
  if not names:raise SystemExit('No read-only catalog for '+APPS[app])
  if app in current.get('apps',{}):
   names=[n for n in names if n not in current['apps'][app].get('tools',{})]
   for name in sorted(set(names)):
    s+='\n[apps.'+app+'.tools.'+json.dumps(name)+']\nenabled = true\n'
   print(APPS[app]+': added '+str(len(set(names)))+' qualified read-only tool aliases.')
   continue
  s+='\n[apps.'+app+']\nenabled = true\ndefault_tools_enabled = false\ndefault_tools_approval_mode = "writes"\ndestructive_enabled = false\n'
  for name in sorted(set(names)):
   s+='\n[apps.'+app+'.tools.'+json.dumps(name)+']\nenabled = true\n'
  print(APPS[app]+': '+str(len(set(names)))+' read-only tools; all other tools disabled.')
 tomllib.loads(s)
 p.write_text(s)
finally:c.close()
