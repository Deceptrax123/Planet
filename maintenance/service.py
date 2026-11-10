"""Root-owned deployment broker. Never executes candidate code as root."""
from datetime import datetime, timezone, timedelta
import hashlib
import inspect
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import queue
import re
import selectors
import socket
import socketserver
import struct
import subprocess
import sys
import tempfile
import threading
import time

STATE=Path('/var/lib/personal-agent-maintenance')
PREFIX=Path('/opt/personal-agents')
WORKSPACE=Path('/var/lib/personal-agent/workspaces/scientific-assistants')
SOCKET='/run/personal-agent-maintenance/broker.sock'
PROTECTED={'backup.py','shared_sync.py','control.py','sitecustomize.py','usercustomize.py'}
UNITS=['personal-agent-gateway','personal-agent-ji-an','personal-agent-data',
       'personal-agent-reminders','personal-agent-mission-control','personal-agent-discord-monitor','personal-agent-research']


def now():return datetime.now(timezone.utc).isoformat()
def digest(value):return hashlib.sha256(value.encode()).hexdigest()


def source_path(value):
    if not isinstance(value,str) or not value or '\\' in value or '\x00' in value:
        raise ValueError('Invalid source path')
    path=PurePosixPath(value)
    if path.is_absolute() or any(p in {'..','.git','node_modules','__pycache__','.codex','.hermes','.ssh','.aws'} for p in path.parts):
        raise ValueError('Path is outside the code project')
    if str(path)!=value or path.suffix in {'.db','.sqlite','.token','.key','.pem','.log','.jsonl'} or path.name.startswith('.env'):
        raise ValueError('Only canonical source files are accepted')
    return path


def destination(value):
    p=source_path(value)
    if len(p.parts)==2 and p.parts[0]=='app' and p.suffix=='.py':
        if p.name in PROTECTED or p.stem in sys.stdlib_module_names:
            return None
        return PREFIX/value
    if len(p.parts)==2 and p.parts[0]=='mission-control' and p.suffix in {'.js','.css','.html'}:
        return PREFIX/value
    if len(p.parts)==2 and p.parts[0]=='whatsapp-bridge' and p.suffix in {'.js','.mjs'}:
        return PREFIX/value
    return None


def atomic(path, content, mode=0o600):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            os.fchmod(stream.fileno(),mode);stream.write(content);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
        directory=os.open(path.parent,os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def read_json(path, default=None):
    try:return json.loads(Path(path).read_text())
    except FileNotFoundError:return default


def capture(command, timeout=180):
    """Drain subprocess output while keeping bounded diagnostic memory."""
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ)
    output=b'';deadline=time.monotonic()+timeout
    try:
        while selector.get_map():
            if time.monotonic()>deadline:
                process.kill();raise TimeoutError('Fixed check command timed out')
            for key,_ in selector.select(.25):
                data=os.read(key.fd,8192)
                if data:output=(output+data)[-60000:]
                else:selector.unregister(key.fileobj)
        return process.wait(timeout=5),output.decode(errors='replace')
    finally:
        selector.close();process.stdout.close()
        if process.poll() is None:process.kill();process.wait()


class Backend:
    def __init__(self, root=STATE):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock();self.jobs=queue.Queue()
        self.active=read_json(self.root/'active.json',{'id':'initial'})
        self.recover()

    def load(self, candidate_id):
        if not isinstance(candidate_id,str) or not re.fullmatch(r'c_[a-f0-9]{24}',candidate_id):
            raise ValueError('Invalid candidate ID')
        result=read_json(self.root/'candidates'/candidate_id/'metadata.json')
        if result is None:raise ValueError('Unknown candidate')
        return result

    def save(self,data):
        data['updated_at']=now()
        atomic(self.root/'candidates'/data['id']/'metadata.json',json.dumps(data,indent=2)+'\n')

    def status(self,candidate_id=None):
        with self.lock:
            if candidate_id:return self.load(candidate_id)
            paths=sorted((self.root/'candidates').glob('*/metadata.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:12]
            return {'workspace':str(WORKSPACE),'active':self.active,
                    'candidates':[read_json(p) for p in paths],'owner_stopped':(self.root/'OWNER_STOPPED').exists(),'recovery_pending':(self.root/'transaction.json').exists(),
                    'scope':'Non-root application, dashboard and WhatsApp bridge code; protected administrator code is excluded',
                    'review_policy':'Two source-bound peer attestations, including Ji An on gpt-6.1-sol; attestations are workflow evidence, not cryptographic proof of independence'}

    def prepare(self,files,summary,commit=''):
        if not isinstance(files,dict) or not 1<=len(files)<=250 or not isinstance(summary,str) or not summary.strip() or len(summary)>1000:
            raise ValueError('Provide a bounded source manifest and change summary')
        if not isinstance(commit,str) or (commit and not re.fullmatch(r'[a-f0-9]{40}',commit)):
            raise ValueError('Invalid local source commit')
        total=0
        for name,content in files.items():
            source_path(name)
            if not isinstance(content,str) or len(content.encode())>1_000_000:raise ValueError('Invalid source content')
            total+=len(content.encode())
        if total>4_000_000:raise ValueError('Source manifest too large')
        required={'app/assistant_broker.py','app/assistant_store.py','app/assistant_mcp.py','mission-control/app.js','tests/test_assistant.py'}
        if not required<=files.keys():raise ValueError('Candidate must include the complete project and baseline regression tests')
        baseline=read_json(self.root/'source-baseline.json',{})
        for name in baseline:
            if name.startswith('tests/') and name not in files:raise ValueError('Baseline tests cannot be omitted')
        fingerprint=digest(json.dumps({'base':self.active['id'],'files':files},sort_keys=True,ensure_ascii=False))
        candidate_id='c_'+fingerprint[:24]
        with self.lock:
            base=self.root/'candidates'/candidate_id
            if (base/'metadata.json').exists():return self.load(candidate_id)
            changes=[];protected=[]
            baseline=read_json(self.root/'source-baseline.json',{})
            for name,content in sorted(files.items()):
                target=destination(name)
                if target:
                    old=target.read_text() if target.exists() else None
                    if old!=content:changes.append({'path':name,'old':old,'new':content})
                elif name.startswith(('maintenance/','systemd/')) or name in {'app/backup.py','app/shared_sync.py','app/control.py'} or (name.startswith('app/') and name.endswith('.py')):
                    if baseline.get(name)!=digest(content):protected.append(name)
            if sum(read_json(p).get('state')=='testing' for p in (self.root/'candidates').glob('*/metadata.json'))>=2:
                raise ValueError('Two checks are already pending; wait for their results')
            tree=base/'tree';tree.mkdir(parents=True)
            build=pwd.getpwnam('personal-agent-build')
            os.chown(base,0,build.pw_gid);base.chmod(0o750)
            for name,content in files.items():
                path=tree/name;path.parent.mkdir(parents=True,exist_ok=True)
                atomic(path,content,0o644)
            for directory in [tree,*[p for p in tree.rglob('*') if p.is_dir()]]:
                os.chown(directory,0,build.pw_gid);directory.chmod(0o750)
            (tree/'whatsapp-bridge/node_modules').mkdir(exist_ok=True)
            data={'id':candidate_id,'digest':fingerprint,'summary':summary,'commit':commit,
                  'base_release':self.active['id'],'state':'testing','created_at':now(),
                  'changed_files':[x['path'] for x in changes],'protected_changes':protected,
                  'reviews':[],'check_log':'','test_passed':False}
            atomic(base/'changes.json',json.dumps(changes))
            self.save(data);self.jobs.put(('check',candidate_id))
            return data

    def candidate_diff(self,candidate_id):
        data=self.load(candidate_id)
        import difflib
        changes=read_json(self.root/'candidates'/candidate_id/'changes.json')
        value=''.join(''.join(difflib.unified_diff((x['old'] or '').splitlines(True),x['new'].splitlines(True),fromfile='a/'+x['path'],tofile='b/'+x['path'])) for x in changes)
        if len(value)>200000:raise ValueError('Diff is large; inspect candidate files individually')
        return {'id':candidate_id,'digest':data['digest'],'diff':value,'protected_changes':data['protected_changes']}

    def candidate_file(self,candidate_id,path):
        self.load(candidate_id);source_path(path)
        target=self.root/'candidates'/candidate_id/'tree'/path
        if not target.is_file():raise ValueError('Candidate file not found')
        value=target.read_text()
        return {'path':path,'content':value,'sha256':digest(value)}

    def review(self,candidate_id,reviewer,model,thread_id,verdict,notes):
        if not all(isinstance(x,str) for x in [reviewer,model,thread_id,verdict,notes]):raise ValueError('Invalid review fields')
        if model!='gpt-6.1-sol' or verdict not in {'approve','request_changes'} or not notes.strip() or len(notes)>4000:
            raise ValueError('Record a substantive GPT-6.1 Sol review, approve or request_changes')
        if not re.fullmatch(r'[A-Za-z0-9_-]{2,60}',reviewer) or not re.fullmatch(r'[a-f0-9-]{32,40}',thread_id):
            raise ValueError('Use the actual reviewer and native Codex thread ID')
        with self.lock:
            data=self.load(candidate_id)
            if data['state'] not in {'ready','review_requested'}:raise ValueError('Wait for successful checks before recording review')
            data['reviews']=[r for r in data['reviews'] if r['reviewer']!=reviewer and r['thread_id']!=thread_id]
            data['reviews'].append({'reviewer':reviewer,'model':model,'thread_id':thread_id,'verdict':verdict,'notes':notes,'at':now(),'digest':data['digest']})
            self.save(data);return data

    def deploy(self,candidate_id):
        with self.lock:
            data=self.load(candidate_id)
            if (self.root/'OWNER_STOPPED').exists():raise ValueError('Owner stopped the application; resume with personal-agent-control start')
            if (self.root/'transaction.json').exists():raise ValueError('Prior transaction recovery must finish first')
            if data['state']=='queued':return data
            if data['state']!='ready' or not data['test_passed']:raise ValueError('Successful isolated tests are required')
            if data['protected_changes']:raise ValueError('Administrator/runtime-policy changes require a separate administrator review: '+', '.join(data['protected_changes']))
            reviews=data['reviews']
            if len(reviews)<2 or any(r['verdict']!='approve' or r['digest']!=data['digest'] for r in reviews) or not any(r['reviewer']=='ji-an' for r in reviews):
                raise ValueError('Two independent source-bound approvals are required, including Ji An on GPT-6.1 Sol')
            if data['base_release']!=self.active['id']:raise ValueError('The installed release changed; prepare the current source again')
            if not data['changed_files']:raise ValueError('No runtime code changes to deploy')
            data['state']='queued';self.save(data);self.jobs.put(('deploy',candidate_id));return data

    def rollback(self,candidate_id):
        with self.lock:
            data=self.load(candidate_id)
            if self.active['id']!=candidate_id or data['state']!='deployed':raise ValueError('Only the currently active managed release can be rolled back')
            data['state']='rollback_queued';self.save(data);self.jobs.put(('rollback',candidate_id));return data

    def recover_pending(self):
        with self.lock:
            journal=read_json(self.root/'transaction.json')
            if not journal:return {'recovery_pending':False}
            data=self.load(journal['candidate_id'])
            self.jobs.put(('recover',data['id']))
            return {'recovery_pending':True,'queued':True,'candidate_id':data['id']}

    def check(self,candidate_id):
        data=self.load(candidate_id);tree=self.root/'candidates'/candidate_id/'tree'
        unit='personal-agent-check-'+candidate_id
        command=['/usr/bin/systemd-run','--quiet','--wait','--pipe','--collect','--unit='+unit,
                 '--uid=personal-agent-build','--working-directory='+str(tree),
                 '--property=NoNewPrivileges=yes','--property=ProtectSystem=strict','--property=ProtectHome=yes',
                 '--property=PrivateNetwork=yes','--property=PrivateTmp=yes','--property=PrivateDevices=yes',
                 '--property=InaccessiblePaths=/var/lib/personal-agent /var/lib/personal-agent-data /var/lib/personal-agent-research /etc/personal-agents /run/personal-agent-data /run/personal-agent-research /run/personal-agent-maintenance',
                 '--property=BindReadOnlyPaths=/opt/personal-agents/whatsapp-bridge/node_modules:'+str(tree/'whatsapp-bridge/node_modules'),
                 '--property=MemoryMax=512M','--property=TasksMax=64','--property=CPUQuota=100%',
                 '--property=RuntimeMaxSec=180','--setenv=HOME=/tmp','--setenv=PYTHONDONTWRITEBYTECODE=1',
                 '--setenv=PYTHONPATH=','/usr/bin/python3','-I',str(PREFIX/'maintenance/run_checks.py'),str(tree)]
        result,log=capture(command,timeout=200)
        with self.lock:
            data=self.load(candidate_id);data['test_passed']=result==0 and 'MAINTENANCE_CHECKS_PASSED' in log
            data['check_log']=log[-30000:];data['state']='ready' if data['test_passed'] else 'failed_checks';self.save(data)
        self.report(data,'Isolated checks passed' if data['test_passed'] else 'Isolated checks failed')

    def idle(self):
        if (self.root/'OWNER_STOPPED').exists():return False
        for directory in [Path('/var/lib/personal-agent/.hermes'),Path('/var/lib/personal-agent/.hermes/profiles/ji-an')]:
            state=read_json(directory/'gateway_state.json',{})
            if state.get('active_agents',0):return False
        return not Path('/var/lib/personal-agent/.hermes/ESTOP').exists() and not (self.root/'OWNER_STOPPED').exists()

    def health(self):
        for unit in UNITS:
            if subprocess.run(['/usr/bin/systemctl','is-active','--quiet',unit]).returncode:return False
        for directory,platforms in [(Path('/var/lib/personal-agent/.hermes'),['discord','whatsapp']),
                                    (Path('/var/lib/personal-agent/.hermes/profiles/ji-an'),['discord'])]:
            state=read_json(directory/'gateway_state.json',{})
            if any(state.get('platforms',{}).get(p,{}).get('state')!='connected' for p in platforms):return False
        # Request-only health probe; do not import replaceable application code as root.
        try:
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                client.settimeout(3);client.connect('/run/personal-agent-data/broker.sock')
                client.sendall(b'{"method":"assistant_status","args":{}}\n')
                with client.makefile('rb') as stream:result=json.loads(stream.readline(1000001))
            return 'result' in result and result['result'].get('voice')=='disabled'
        except (OSError,ValueError):return False

    def write_targets(self,changes,rollback=False):
        for item in changes:
            target=destination(item['path'])
            if target is None:raise ValueError('Protected deployment target')
            # All target parents belong to the root-controlled installation.
            for parent in [target.parent,PREFIX]:
                info=parent.lstat()
                if parent.is_symlink() or info.st_uid!=0 or info.st_mode&0o022:raise ValueError('Unsafe installation directory')
            if target.is_symlink():raise ValueError('Symlink installation target')
            value=item['old'] if rollback else item['new']
            if value is None:target.unlink(missing_ok=True)
            else:atomic(target,value,0o644)

    def stop(self):
        subprocess.run(['/usr/bin/systemctl','stop',*UNITS],check=True,timeout=150)

    def restart(self):
        if (self.root/'OWNER_STOPPED').exists():raise ValueError('The owner stopped the application; do not restart it')
        subprocess.run(['/usr/bin/systemctl','start',*UNITS],check=True,timeout=120)

    def wait_health(self):
        for _ in range(75):
            if (self.root/'OWNER_STOPPED').exists():raise ValueError('Owner stop requested')
            if self.health():return
            time.sleep(1)
        raise ValueError('Post-deployment health check failed')


    def apply(self,candidate_id,rollback=False):
        if (self.root/'transaction.json').exists():
            raise ValueError('Pending recovery must finish before executing another release')
        for _ in range(600):
            if self.idle():break
            time.sleep(1)
        else:raise ValueError('Deployment waits for idle gateways and owner resume; retry later')
        data=self.load(candidate_id)
        changes=read_json(self.root/'candidates'/candidate_id/'changes.json')
        if rollback and (self.active['id']!=candidate_id or data['state']!='rollback_queued'):
            raise ValueError('Rollback is stale; the active release changed since it was queued')
        if not rollback:
            if data['base_release']!=self.active['id']:raise ValueError('Stale candidate')
            for item in changes:
                target=destination(item['path']);old=target.read_text() if target.exists() else None
                if old!=item['old']:raise ValueError('Installed source changed since checks; prepare again')
        if (self.root/'OWNER_STOPPED').exists():raise ValueError('Owner stop requested')
        if (self.root/'transaction.json').exists():raise ValueError('Pending recovery must finish first')
        data['state']='rolling_back' if rollback else 'deploying';self.save(data)
        journal={'candidate_id':candidate_id,'changes':changes,'previous':dict(self.active),'restore_new':rollback}
        atomic(self.root/'transaction.json',json.dumps(journal))
        try:
            self.stop()
            self.write_targets(changes,rollback)
            self.restart()
            self.wait_health()
            self.active={'id':data['base_release'] if rollback else candidate_id,'at':now()}
            atomic(self.root/'active.json',json.dumps(self.active))
            data['state']='rolled_back' if rollback else 'deployed';self.save(data)
            (self.root/'transaction.json').unlink()
            self.report(data,'Rolled back' if rollback else 'Deployed and health checked',notify=True)
        except Exception:
            self.stop()
            self.write_targets(changes,rollback=not rollback)
            stopped=(self.root/'OWNER_STOPPED').exists()
            if not stopped:self.restart();self.wait_health()
            self.active=journal['previous'];atomic(self.root/'active.json',json.dumps(self.active))
            data['state']='interrupted_by_owner_stop' if stopped else ('deployed' if rollback else 'automatically_rolled_back');self.save(data)
            (self.root/'transaction.json').unlink(missing_ok=True)
            self.report(data,'Health check failed; restored the prior code',notify=True)
            raise

    def recover(self):
        journal=read_json(self.root/'transaction.json')
        if journal:
            self.stop()
            self.write_targets(journal['changes'],rollback=not journal.get('restore_new',False))
            self.active=journal['previous'];atomic(self.root/'active.json',json.dumps(self.active))
            if not (self.root/'OWNER_STOPPED').exists():self.restart();self.wait_health()
            (self.root/'transaction.json').unlink()
            data=self.load(journal['candidate_id']);data['state']='interrupted_by_owner_stop' if (self.root/'OWNER_STOPPED').exists() else 'recovered';self.save(data)
        for path in (self.root/'candidates').glob('*/metadata.json'):
            data=read_json(path)
            if data['state'] in {'testing','queued','rollback_queued','deploying','rolling_back'}:
                data['state']='interrupted';self.save(data)

    def report(self,data,summary,notify=False):
        payload={'method':'activity_report','args':{'agent':'self-maintenance','task_id':data['id'],'state':'done' if data['state'] in {'deployed','rolled_back','ready','recovered'} else 'failed','summary':summary+': '+data['summary'],'model':''}}
        try:
            self.data_call(payload)
            if notify:self.data_call({'method':'notify_owner','args':{'text':summary+': '+data['summary'],'event_key':'maintenance:'+data['id']+':'+data['state'],'source':'https://github.com/Deceptrax123/scientific-assistants','reason':'Verified assistant-code maintenance result','expires_at':(datetime.now(timezone.utc)+timedelta(hours=24)).isoformat()}})
        except (OSError,ValueError):pass

    def data_call(self,payload):
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
            client.settimeout(5);client.connect('/run/personal-agent-data/broker.sock')
            client.sendall(json.dumps(payload).encode()+b'\n')
            with client.makefile('rb') as stream:return json.loads(stream.readline(1000001))

    def worker(self):
        while True:
            operation,candidate_id=self.jobs.get()
            try:
                if operation=='check':self.check(candidate_id)
                elif operation=='recover':
                    self.recover();self.report(self.load(candidate_id),'Restored the prior release after interrupted recovery',notify=True)
                else:self.apply(candidate_id,operation=='rollback')
            except Exception as exc:
                with self.lock:
                    data=self.load(candidate_id);data['last_error']=str(exc)[:500]
                    if data['state'] not in {'automatically_rolled_back','interrupted','deployed','interrupted_by_owner_stop'}:data['state']='failed'
                    self.save(data)
            finally:self.jobs.task_done()

    def dispatch(self,method,args):
        if method not in {'status','prepare','review','deploy','rollback','candidate_diff','candidate_file','recover_pending'}:raise ValueError('Unknown maintenance operation')
        fn=getattr(self,method);inspect.signature(fn).bind(**args);return fn(**args)


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(15)
        _,uid,_=struct.unpack('3i',self.connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        if uid not in self.server.allowed_uids:return
        try:
            raw=self.rfile.readline(5_000_001)
            if len(raw)>5_000_000:raise ValueError('Request too large')
            message=json.loads(raw);result={'result':self.server.backend.dispatch(message['method'],message.get('args',{}))}
        except Exception as exc:result={'error':str(exc)[:600]}
        self.wfile.write(json.dumps(result,allow_nan=False).encode()+b'\n')


def main():
    if os.geteuid()!=0:raise SystemExit('Maintenance service must use its administrator unit')
    Path(SOCKET).unlink(missing_ok=True)
    with socketserver.ThreadingUnixStreamServer(SOCKET,Handler) as server:
        server.daemon_threads=True;server.backend=Backend()
        server.allowed_uids={0,pwd.getpwnam('personal-agent').pw_uid}
        os.chmod(SOCKET,0o660);os.chown(SOCKET,0,pwd.getpwnam('personal-agent').pw_gid)
        threading.Thread(target=server.backend.worker,daemon=True).start()
        print('Scoped self-maintenance broker ready',flush=True);server.serve_forever()


if __name__=='__main__':main()
