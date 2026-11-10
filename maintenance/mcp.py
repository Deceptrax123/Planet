"""Unprivileged source tools and client for the administrator-owned deploy broker."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
from protocol import request

WORKSPACE=Path('/var/lib/personal-agent/workspaces/scientific-assistants')
EXTENSIONS={'.py','.js','.mjs','.css','.html','.md','.txt','.json','.toml','.yaml','.yml','.service','.timer'}
SKIP={'.git','.venv','venv','node_modules','__pycache__','.hermes','.codex','.ssh','.aws'}

def path_for(name):
    if not isinstance(name,str) or not name or '\\' in name or '\x00' in name:raise ValueError('Invalid project path')
    p=PurePosixPath(name)
    if p.is_absolute() or str(p)!=name or '..' in p.parts or any(x in SKIP for x in p.parts):raise ValueError('Path must be inside the source project')
    if p.suffix not in EXTENSIONS and name!='.gitignore':raise ValueError('Only source/documentation files are supported')
    if any(x.startswith('.') for x in p.parts) and name!='.gitignore':raise ValueError('Hidden configuration is excluded')
    target=WORKSPACE/name
    # This runs as the agent, never root. Reject symlinks even if they resolve inside.
    for part in [target,*target.parents]:
        if part==WORKSPACE.parent:break
        if part.is_symlink():raise ValueError('Symlinks are excluded from source tools')
    if not target.resolve().is_relative_to(WORKSPACE.resolve()):raise ValueError('Path escapes workspace')
    return target


def source_files():
    result={}
    for path in WORKSPACE.rglob('*'):
        name=path.relative_to(WORKSPACE).as_posix()
        if any(p in SKIP for p in path.relative_to(WORKSPACE).parts):continue
        if path.is_symlink():raise ValueError('Source symlinks are excluded')
        if not path.is_file():continue
        try:target=path_for(name)
        except ValueError:continue
        if target.stat().st_size>1_000_000:raise ValueError('Source file is too large: '+name)
        result[name]=target.read_text()
    return result


def execute(name,args):
    if name=='self_code_status':return request('status',args)
    if name=='self_code_list':return {'workspace':str(WORKSPACE),'files':sorted(source_files())}
    if name=='self_code_read':
        path=path_for(args['path']);value=path.read_text()
        return {'path':args['path'],'content':value,'sha256':hashlib.sha256(value.encode()).hexdigest()}
    if name=='self_code_write':
        path=path_for(args['path']);content=args['content'];expected=args.get('expected_sha256')
        if not isinstance(content,str) or len(content.encode())>1_000_000:raise ValueError('Invalid source content')
        current=hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ''
        if expected is not None and current!=expected:raise ValueError('Source changed; reread before editing')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content)
        return {'path':args['path'],'sha256':hashlib.sha256(content.encode()).hexdigest(),'deployed':False}
    if name=='self_code_prepare':
        commit=subprocess.run(['/usr/bin/git','-C',str(WORKSPACE),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
        return request('prepare',{'files':source_files(),'summary':args['summary'],'commit':commit},timeout=60)
    if name=='self_code_commit':
        message=args['message']
        if not isinstance(message,str) or not message.strip() or len(message)>500:raise ValueError('Provide a concise commit message')
        files=source_files()
        subprocess.run(['/usr/bin/git','-C',str(WORKSPACE),'add','--',*files],check=True,capture_output=True)
        result=subprocess.run(['/usr/bin/git','-C',str(WORKSPACE),'commit','-m',message],capture_output=True,text=True)
        return {'returncode':result.returncode,'output':(result.stdout+result.stderr)[-4000:],'pushed':False}
    methods={'self_code_recover':'recover_pending','self_code_diff':'candidate_diff','self_code_candidate_read':'candidate_file','self_code_review':'review','self_code_deploy':'deploy','self_code_rollback':'rollback'}
    if name in methods:return request(methods[name],args)
    raise ValueError('Unknown maintenance tool')


def spec(name,description,properties=None,required=None,read=False):
    return {'name':name,'description':description,'inputSchema':{'type':'object','properties':properties or {},'required':required or [],'additionalProperties':False},'annotations':{'readOnlyHint':read,'openWorldHint':False}}
S={'type':'string'};C={'candidate_id':S}
TOOLS=[
    spec('self_code_list','List source and test paths in the writable project. Useful when shell tools are unavailable.',read=True),
    spec('self_code_status','Inspect the real writable source workspace, candidate tests/reviews, deployment and rollback status. Application code can be improved autonomously within the owner-authorized task. No sudo or /root access is needed.',C,read=True),
    spec('self_code_read','Read project source. Use returned sha256 for edits. Paths are relative to the maintained workspace.',{'path':S},['path'],True),
    spec('self_code_write','Edit/add project source or tests in the writable checkout. Changes are staged source only; use prepare, peer review and deploy to update runtime.',{'path':S,'content':S,'expected_sha256':S},['path','content']),
    spec('self_code_commit','Commit reviewed local source history. This does not push to GitHub or deploy.',{'message':S},['message']),
    spec('self_code_prepare','Freeze current source into an immutable candidate and run fixed isolated Python/Node regression checks. Poll status; inspect actual check_log. Failed tests cannot deploy.',{'summary':S},['summary']),
    spec('self_code_diff','Read the exact immutable runtime diff for peer review.',C,['candidate_id'],True),
    spec('self_code_candidate_read','Read a source/test file from the exact immutable candidate under review.',{**C,'path':S},['candidate_id','path'],True),
    spec('self_code_review','Record a substantive source-bound GPT-6.1 Sol review. Use the actual reviewer native thread ID and truthful verdict. Two distinct reviewers including ji-an must approve; do not impersonate them.',{**C,'reviewer':S,'model':{'type':'string','enum':['gpt-6.1-sol']},'thread_id':S,'verdict':{'type':'string','enum':['approve','request_changes']},'notes':S},['candidate_id','reviewer','model','thread_id','verdict','notes']),
    spec('self_code_deploy','Queue a tested, peer-approved application release. Waits for idle gateways, restarts affected services, checks health and restores prior code on failure. It cannot change administrator code, service permissions or credentials. Report the eventual actual status.',C,['candidate_id']),
    spec('self_code_recover','Retry restoration of an interrupted deployment using its existing journal. Cannot choose arbitrary code or target paths. Poll status for actual recovery; owner stop remains effective.'),
    spec('self_code_rollback','Restore the previous code of the currently active managed release. Observe final status; do not assume that queued means complete.',C,['candidate_id']),
]
INSTRUCTIONS='The owner authorizes autonomous fixes and new application capabilities. Your writable project is '+str(WORKSPACE)+'. Use these tools if shell access is unavailable. Inspect source and evidence, add meaningful regressions, prepare an immutable candidate, obtain two actual independent Sol reviews including Ji An, then deploy and verify status. Never claim completion while only staged or queued. Keep progress in activity monitoring and give the owner the verified result. New credentials, cloud spend, system privileges, destructive work and messaging others still need their applicable owner authorization. Administrator/service policy is protected. No paid inference fallback; Claude and voice remain deferred.'

def handle(message):
    if not isinstance(message,dict):raise ValueError('Expected a JSON-RPC object')
    method=message.get('method');params=message.get('params',{})
    if not isinstance(params,dict):raise ValueError('Expected object params')
    if method=='initialize':return {'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'assistant-maintenance','version':'1.0.0'},'instructions':INSTRUCTIONS}
    if method=='ping':return {}
    if method=='tools/list':return {'tools':TOOLS}
    if method!='tools/call':raise ValueError('Unsupported method')
    name=params.get('name');tool=next((t for t in TOOLS if t['name']==name),None);args=params.get('arguments',{})
    if tool is None or not isinstance(args,dict):raise ValueError('Unknown tool or invalid arguments')
    schema=tool['inputSchema']
    if set(args)-set(schema['properties']) or set(schema['required'])-set(args):raise ValueError('Missing or unexpected arguments')
    for key,value in args.items():
        if not isinstance(value,str):raise ValueError(key+' must be a string')
        enum=schema['properties'][key].get('enum')
        if enum and value not in enum:raise ValueError('Unsupported '+key)
    try:return {'content':[{'type':'text','text':json.dumps(execute(name,args),ensure_ascii=False)}]}
    except (OSError,ValueError,subprocess.SubprocessError) as exc:return {'isError':True,'content':[{'type':'text','text':str(exc)[:1000]}]}


def main():
    for raw in sys.stdin.buffer:
        identifier=None
        try:
            if len(raw)>2_000_000:raise ValueError('Request too large')
            message=json.loads(raw)
            if not isinstance(message,dict):raise ValueError('Expected object')
            identifier=message.get('id')
            if identifier is None:continue
            output={'jsonrpc':'2.0','id':identifier,'result':handle(message)}
        except Exception as exc:output={'jsonrpc':'2.0','id':identifier,'error':{'code':-32602,'message':str(exc)[:1000]}}
        print(json.dumps(output,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
