"""Isolated GCP/SSH broker. MCP clients cannot read its login or private SSH keys."""
import argparse
from datetime import datetime, timezone
import inspect
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import socketserver
import sqlite3
import struct
import subprocess
import threading
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from assistant_broker import request

HOME = Path('/var/lib/personal-agent-research')
SOCKET = '/run/personal-agent-research/broker.sock'
SDK = '/opt/personal-agents/google-cloud-sdk/bin/gcloud'
PROFILE = 'researcher-invoker-srinitish'
PROJECT = 'avid-renderer-503311-n6'
SUBJECT = 'srinitishsri@gmail.com'
POOL = 'lossfunk-researchers'
CLAUDE_DEFERRED = True  # Owner explicitly deferred Claude Code on 2026-11-09.
HOSTS = {
    'petase-design': {'instance': 'petase-design', 'zone': 'us-central1-c', 'id': '8765957881121335422', 'user': 'srinitish_srinivasan', 'last_known_ip': '34.121.229.120'},
    'agent-simulation-sandbox-nitish': {'instance': 'agent-simulation-sandbox-nitish', 'zone': 'us-central1-a', 'id': '556680880449317363', 'user': 'srinitish_srinivasan', 'last_known_ip': '136.111.160.40'},
}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class Backend:
    def __init__(self, home=HOME):
        self.home = Path(home)
        (self.home/'state').mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.job_locks = defaultdict(threading.RLock)
        self.auth_cache = (0, 'login_required')
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS tasks (
              id TEXT PRIMARY KEY, host TEXT, engine TEXT, model TEXT, project TEXT, title TEXT,
              parent_id TEXT, state TEXT, detail TEXT, updated_at TEXT, request TEXT);
              CREATE TABLE IF NOT EXISTS hosts (name TEXT PRIMARY KEY, state TEXT, detail TEXT, updated_at TEXT);''')
            db.execute('CREATE TABLE IF NOT EXISTS notifications (task_id TEXT,state TEXT,PRIMARY KEY(task_id,state))')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.home/'state/research.sqlite', timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:yield db
        finally:db.close()

    def cloud(self, args, timeout=50):
        env = os.environ.copy()
        env.update(HOME=str(self.home), CLOUDSDK_CONFIG=str(self.home/'.config/gcloud'),
                   CLOUDSDK_CORE_DISABLE_PROMPTS='1', CLOUDSDK_CORE_DISABLE_USAGE_REPORTING='1')
        p = subprocess.run([SDK, '--configuration='+PROFILE, '--project='+PROJECT, '--quiet', *args],
                           env=env, capture_output=True, text=True, timeout=timeout)
        if p.returncode:
            # Do not return raw credential-bearing provider output to MCP/Discord.
            raise ValueError('GCP operation failed; renew the dedicated research login or inspect private setup diagnostics')
        return p.stdout.strip()

    def identity(self, token=False):
        account = self.cloud(['config', 'get-value', 'account'])
        prefix = f'//iam.googleapis.com/locations/global/workforcePools/{POOL}/subject/'
        principal=account.removeprefix('principal:')
        # AWS emits this confirmed Gmail address with an uppercase S. Gmail mailbox
        # identity is case-insensitive; the workforce pool/path must still match exactly.
        if not principal.startswith(prefix) or principal[len(prefix):].casefold() != SUBJECT.casefold():
            raise ValueError('Research login is missing or does not match the owner workforce identity')
        if token:
            # Validity check only: token stays in this private process and is never returned or logged.
            self.cloud(['auth', 'print-access-token'])
        return account

    def research_status(self):
        checked, auth = self.auth_cache
        if time.monotonic()-checked > 60:
            try:
                self.identity(token=True)
                auth = 'authenticated'
            except (ValueError, OSError, subprocess.SubprocessError):
                auth = 'login_required'
            self.auth_cache = (time.monotonic(), auth)
        with self.db() as db:
            hosts = {r['name']: dict(r) for r in db.execute('SELECT * FROM hosts')}
            tasks = [dict(r) for r in db.execute('SELECT id,host,engine,model,project,title,parent_id,state,updated_at FROM tasks ORDER BY updated_at DESC LIMIT 40')]
        return {'auth': auth, 'profile': PROFILE, 'claude_code': 'deferred_by_owner' if CLAUDE_DEFERRED else 'available_if_authenticated', 'session_policy': 'Workforce login expires after eight hours; renew interactively',
                'hosts': [dict(name=name, **meta, **{k:v for k,v in hosts.get(name, {}).items() if k!='name'}) for name, meta in HOSTS.items()], 'tasks': tasks}

    def remote(self, name, payload):
        if name not in HOSTS:
            raise ValueError('Unknown server; add owner-authorized servers to the administrator allowlist first')
        self.identity(token=True)
        h = HOSTS[name]
        data = json.loads(self.cloud(['compute', 'instances', 'describe', h['instance'], '--zone='+h['zone'], '--format=json']))
        if str(data.get('id')) != h['id']:
            raise ValueError('GCP instance identity changed; administrator verification required')
        if data.get('status') != 'RUNNING':
            raise ValueError('Server is not running; no VM start or provisioning was attempted')
        helper = Path(__file__).with_name('research_remote.py').read_text()
        loader = 'import sys,json;r=json.load(sys.stdin);s=r.pop("_helper");n={"__name__":"ji_eun_remote"};exec(compile(s,"<ji-eun-helper>","exec"),n);print(json.dumps(n["dispatch"](r,s)))'
        command = 'python3 -c ' + shlex.quote(loader)
        env = os.environ.copy()
        env.update(HOME=str(self.home), CLOUDSDK_CONFIG=str(self.home/'.config/gcloud'), CLOUDSDK_CORE_DISABLE_PROMPTS='1', CLOUDSDK_CORE_DISABLE_USAGE_REPORTING='1')
        args = [SDK, '--configuration='+PROFILE, '--project='+PROJECT, '--quiet', 'compute', 'ssh',
                h['user']+'@'+h['instance'], '--zone='+h['zone'],
                '--ssh-key-file='+str(self.home/'.ssh/google_compute_engine'), '--strict-host-key-checking=yes',
                '--ssh-flag=-oBatchMode=yes', '--ssh-flag=-oConnectTimeout=12', '--ssh-flag=-oServerAliveInterval=10',
                '--ssh-flag=-oIdentitiesOnly=yes', '--ssh-flag=-oUserKnownHostsFile='+str(self.home/'.ssh/google_compute_known_hosts'),
                '--command='+command]
        p = subprocess.run(args, input=json.dumps(dict(payload, _helper=helper)), env=env,
                           capture_output=True, text=True, timeout=100)
        if p.returncode:
            raise ValueError('SSH/helper operation failed; check login, trusted host keys, reachability and engine authentication in the private setup console')
        try: return json.loads(p.stdout)
        except ValueError: raise ValueError('Remote helper did not return a valid response') from None

    def report(self, task, summary):
        try:
            state = task['state'] if task['state'] in {'working','done','failed','waiting'} else 'waiting'
            request('activity_report', {'agent': 'Ji An / '+task['engine'], 'task_id': task['id'],
                    'parent_id': task.get('parent_id', ''), 'state': state, 'model': task['model'],
                    'summary': summary[:600]})
        except (OSError, ValueError): pass

    def research_probe(self, host):
        try:
            result = self.remote(host, {'action':'probe'})
            state = 'ready'
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            result = {'error': str(exc)[:300]}; state = 'stopped' if 'Server is not running' in str(exc) else 'unavailable'
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO hosts VALUES (?,?,?,?)', (host, state, json.dumps(result), timestamp()))
        return dict(state=state, **result)

    def research_submit(self, host, project, prompt, title, owner_request, idempotency_key,
                        engine='codex', model='gpt-6.1-sol', parent_id='', timeout_minutes=60, notify_completion=True):
        if host not in HOSTS or engine not in {'codex', 'claude', 'command'}:
            raise ValueError('Unknown host or engine')
        if engine == 'claude' and CLAUDE_DEFERRED:
            raise ValueError('Claude Code is deferred by the owner. Use Codex; do not request Claude sign-in until the owner resumes it.')
        if model not in {'gpt-6-luna','gpt-6.1-sol','gpt-6.1-terra'}:
            raise ValueError('Unsupported Codex model')
        if not all(isinstance(v,str) and v.strip() for v in [project,prompt,title,owner_request,idempotency_key]):
            raise ValueError('Project, task, title, direct owner-request evidence and idempotency key are required')
        if len(prompt)>30000 or len(title)>180 or len(owner_request)>3000 or len(idempotency_key)>180:
            raise ValueError('Research request too large')
        if not isinstance(timeout_minutes,int) or not 1<=timeout_minutes<=1440:
            raise ValueError('Wall-clock limit must be 1..1440 minutes')
        if not isinstance(notify_completion,bool):raise ValueError('notify_completion must be boolean')
        import hashlib
        identifier = 'r_'+hashlib.sha256(idempotency_key.encode()).hexdigest()[:24]
        payload = dict(action='submit',job_id=identifier,project=project,prompt=prompt,engine=engine,model=model,timeout_minutes=timeout_minutes,owner_request=owner_request,notify_completion=notify_completion)
        with self.lock, self.db() as db:
            old = db.execute('SELECT * FROM tasks WHERE id=?', (identifier,)).fetchone()
            if old:
                if json.loads(old['request']) != payload or old['host'] != host:
                    raise ValueError('Idempotency key already belongs to a different task')
                return {k:old[k] for k in ['id','state','host','engine','title']}
            count = db.execute("SELECT count(*) FROM tasks WHERE state IN ('queued','starting','working','waiting','submitting','connection_lost','cancelling')").fetchone()[0]
            if count>=2: raise ValueError('Two research jobs are already outstanding; inspect them before adding more')
            # Persist before dispatch: restart must never silently duplicate a submitted experiment.
            db.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?)', (identifier,host,engine,model,project,title,parent_id,'queued','{}',timestamp(),json.dumps(payload)))
        return {'id': identifier, 'state':'queued', 'host':host, 'engine':engine, 'title':title}

    def research_task(self, task_id, refresh=False):
        with self.db() as db:
            row=db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
            if row is None: raise ValueError('Unknown research task')
        if refresh and row['state']!='queued':
            with self.job_locks[task_id]:
                detail=self.remote(row['host'],{'action':'poll','job_id':task_id})
                with self.db() as db:
                    db.execute('UPDATE tasks SET state=?,detail=?,updated_at=? WHERE id=?',(detail['state'],json.dumps(detail),timestamp(),task_id))
            return self.research_task(task_id)
        result={k:row[k] for k in ['id','host','engine','model','title','project','parent_id','state','updated_at']}
        result.update(detail=json.loads(row['detail']))
        return result

    def research_cancel(self, task_id):
        with self.job_locks[task_id]:
            return self.cancel_locked(task_id)

    def research_retry(self, task_id):
        with self.job_locks[task_id], self.db() as db:
            task=self.research_task(task_id)
            if task['state']!='connection_lost':
                raise ValueError('Only disconnected tasks can be retried; use a new explicit task for a failed experiment')
            detail=task['detail'];detail['connection_failures']=0
            db.execute("UPDATE tasks SET state='submitting',detail=?,updated_at=? WHERE id=?",(json.dumps(detail),timestamp(),task_id))
        return self.research_task(task_id)

    def cancel_locked(self, task_id):
        task = self.research_task(task_id)
        if task['state'] in {'done','failed','cancelled','timed_out'}: return task
        if task['state']=='queued':
            detail={'state':'cancelled','events':[]}
        else:
            detail=self.remote(task['host'], {'action':'cancel','job_id':task_id})
        with self.db() as db:
            db.execute('UPDATE tasks SET state=?, detail=?, updated_at=? WHERE id=?', (detail['state'],json.dumps(detail),timestamp(),task_id))
        return self.research_task(task_id)

    def tick(self):
        with self.db() as db:
            rows=[dict(r) for r in db.execute("SELECT * FROM tasks WHERE state IN ('queued','starting','submitting','working','waiting','cancelling')")]
        for task in rows:
            with self.job_locks[task['id']]:
                fresh=self.research_task(task['id'])
                if fresh['state'] in {'cancelled','done','failed','timed_out'}:continue
                self.tick_task(task)
        self.notify_pending()

    def notify_pending(self):
        with self.db() as db:
            rows=[dict(r) for r in db.execute("SELECT id,state,request FROM tasks WHERE state IN ('done','failed','timed_out','connection_lost') AND NOT EXISTS (SELECT 1 FROM notifications n WHERE n.task_id=tasks.id AND n.state=tasks.state)")]
        for task in rows:
            if not json.loads(task['request']).get('notify_completion',False):continue
            try:
                result=request('research_event',{'task_id':task['id']})
                if result.get('status') in {'queued','duplicate'}:
                    with self.db() as db:db.execute('INSERT OR IGNORE INTO notifications VALUES (?,?)',(task['id'],task['state']))
            except (OSError,ValueError):pass

    def tick_task(self, task):
        try:
            # Retrying submitting is safe: the remote job directory is keyed by the durable ID.
            if task['state'] in {'queued','submitting'}:
                with self.db() as db: db.execute("UPDATE tasks SET state='submitting' WHERE id=?",(task['id'],))
                result=self.remote(task['host'],json.loads(task['request']))
            else:
                result=self.remote(task['host'],{'action':'poll','job_id':task['id']})
            state=result['state']
            if state=='queued':state='starting'
            result.pop('connection_error',None)
            result['connection_failures']=0
        except (ValueError,OSError,subprocess.SubprocessError) as exc:
            # Keep submission ambiguity distinct from experiment failure; never invent completion.
            state='submitting' if task['state'] in {'queued','submitting'} else 'waiting'
            result=json.loads(task['detail'])
            result['connection_error']=str(exc)[:300]
            result['connection_failures']=result.get('connection_failures',0)+1
            if result['connection_failures']>=3:state='connection_lost'
        with self.db() as db:
            db.execute('UPDATE tasks SET state=?,detail=?,updated_at=? WHERE id=?',(state,json.dumps(result),timestamp(),task['id']))
        if state!=task['state']:
            task['state']=state
            self.report(task,task['title']+' on '+task['host']+': '+state)

    def dispatch(self, method, args):
        if method not in {'research_status','research_probe','research_submit','research_task','research_cancel','research_retry'}:
            raise ValueError('Unknown research tool')
        fn=getattr(self,method);inspect.signature(fn).bind(**args)
        return fn(**args)


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(120)
        _,uid,_=struct.unpack('3i',self.connection.getsockopt(__import__('socket').SOL_SOCKET,__import__('socket').SO_PEERCRED,12))
        if uid not in self.server.allowed_uids:return
        try:
            raw=self.rfile.readline(100001)
            if len(raw)>100000: raise ValueError('Request too large')
            message=json.loads(raw)
            result={'result':self.server.backend.dispatch(message['method'],message.get('args',{}))}
        except (ValueError,TypeError,KeyError,OSError,subprocess.SubprocessError) as exc:
            result={'error':str(exc)[:300]}
        self.wfile.write(json.dumps(result).encode()+b'\n')


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads=True


def main():
    backend=Backend()
    path=Path(SOCKET)
    if path.exists():path.unlink()
    with Server(SOCKET,Handler) as server:
        server.backend=backend
        server.allowed_uids={0,os.getuid(),pwd.getpwnam('personal-agent').pw_uid,pwd.getpwnam('personal-agent-data').pw_uid}
        os.chmod(path,0o660);os.chown(path,-1,pwd.getpwnam('personal-agent').pw_gid)
        def worker():
            while True:
                try:backend.tick()
                except Exception as exc:print('Research worker error: '+type(exc).__name__,flush=True)
                time.sleep(30)
        threading.Thread(target=worker,daemon=True).start()
        print('Research SSH broker ready',flush=True)
        server.serve_forever()


if __name__=='__main__':main()
