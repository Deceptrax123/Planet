"""Small owner-account SSH job runner. No cloud credentials or inference keys."""
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

BASE = Path.home() / '.local/state/ji-eun-research'
MODELS = {'gpt-6-luna', 'gpt-6.1-sol', 'gpt-6.1-terra'}
ID = re.compile(r'r_[a-f0-9]{24}')


def write(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value))
    temp.chmod(0o600)
    temp.replace(path)


def job(identifier):
    if not isinstance(identifier, str) or not ID.fullmatch(identifier):
        raise ValueError('Invalid research job ID')
    return BASE / identifier


def project(value):
    p = Path(value).expanduser().resolve(strict=True)
    home = Path.home().resolve()
    if not p.is_dir() or not p.is_relative_to(home) or p == home:
        raise ValueError('Choose a specific project directory inside the SSH account home')
    if any(part.startswith('.') for part in p.relative_to(home).parts):
        raise ValueError('Hidden settings and credential directories are not project workspaces')
    return p


def executable(name):
    for directory in [Path.home()/'.local/bin', Path.home()/'.npm-global/bin', Path('/usr/local/bin'), Path('/usr/bin')]:
        p = directory / name
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return shutil.which(name)


def engine(name):
    path = executable(name)
    if not path:
        return {'installed': False, 'authenticated': False}
    args = [path, 'login', 'status'] if name == 'codex' else [path, 'auth', 'status']
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=20)
        # Claude must use its existing subscription, never a paid API fallback.
        subscription = True
        if name == 'claude' and result.returncode == 0:
            subscription = json.loads(result.stdout).get('authMethod') == 'claude.ai'
        if name == 'codex' and result.returncode == 0:
            subscription = 'chatgpt' in (result.stdout + result.stderr).lower()
        return {'installed': True, 'authenticated': result.returncode == 0 and subscription,
                'subscription_only': subscription}
    except (subprocess.SubprocessError, ValueError):
        return {'installed': True, 'authenticated': False}


def clean(value):
    value = re.sub(r'(?i)(Bearer|Bot)\s+[A-Za-z0-9._-]{12,}', r'\1 [redacted]', str(value))
    value = re.sub(r'\bsk-[A-Za-z0-9_-]{12,}', '[redacted]', value)
    return re.sub(r'(?i)(["\x27]?(?:access_token|refresh_token|api_key|password|authorization)["\x27]?\s*[:=]\s*)["\x27]?[^\s,"\x27}]+', r'\1[redacted]', value)[:12000]


def visible(row):
    """Select visible CLI output only; never expose reasoning/thinking blocks."""
    kind = row.get('type', '')
    if kind.startswith('item.'):
        item = row.get('item') or {}
        t = item.get('type')
        if t == 'agent_message':
            return {'kind': 'assistant', 'text': clean(item.get('text', ''))}
        if t == 'command_execution':
            return {'kind': 'command', 'text': clean(str(item.get('command', ''))+'\n'+str(item.get('aggregated_output', '')))}
        if t in {'file_change', 'mcp_tool_call'}:
            return {'kind': t, 'text': clean(json.dumps(item))}
    if kind in {'assistant', 'user'}:
        blocks = (row.get('message') or {}).get('content') or []
        parts = []
        for b in blocks:
            if b.get('type') == 'text': parts.append(b.get('text', ''))
            elif b.get('type') == 'tool_use': parts.append(b.get('name', '')+' '+json.dumps(b.get('input', {})))
            elif b.get('type') == 'tool_result': parts.append(str(b.get('content', '')))
        if parts: return {'kind': kind, 'text': clean('\n'.join(parts))}
    if kind == 'result':
        return {'kind': 'result', 'text': clean(row.get('result') or row.get('errors') or '')}
    if kind in {'thread.started', 'turn.started', 'turn.completed', 'turn.failed', 'error'}:
        return {'kind': kind, 'text': clean(row.get('error') or kind)}


def dispatch(req, source=''):
    action = req['action']
    if action == 'probe':
        return {'user': os.environ.get('USER'), 'home': str(Path.home()), 'hostname': os.uname().nodename,
                'projects': [str(p) for p in Path.home().iterdir() if p.is_dir() and not p.name.startswith('.')][:50],
                'engines': {n: engine(n) for n in ['codex', 'claude']}}
    d = job(req['job_id'])
    if action == 'submit':
        p = project(req['project'])
        if req['engine'] not in {'codex', 'claude', 'command'} or req['model'] not in MODELS:
            raise ValueError('Unsupported engine/model')
        if req['engine']!='command' and not engine(req['engine'])['authenticated']:
            raise ValueError('Requested engine needs its own subscription login on this server')
        BASE.mkdir(parents=True, exist_ok=True, mode=0o700)
        try: d.mkdir(mode=0o700)
        except FileExistsError:
            return dispatch({'action':'poll','job_id':req['job_id']})
        req['project'] = str(p)
        req['action'] = 'work'
        write(d/'request.json', req)
        (d/'runner.py').write_text(source)
        write(d/'status.json', {'job_id': req['job_id'], 'state': 'queued', 'engine': req['engine'], 'project': str(p)})
        with (d/'runner-error.log').open('ab') as err:
            subprocess.Popen([sys.executable, str(d/'runner.py'), str(d)], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=err, start_new_session=True, close_fds=True)
        return dispatch({'action':'poll','job_id':req['job_id']})
    if action in {'poll', 'cancel'}:
        state = json.loads((d/'status.json').read_text())
        if state['state']=='working':
            try:
                current=Path(f'/proc/{state["pid"]}/stat').read_text().split()[21]
                alive=current==state['process_start']
            except FileNotFoundError:alive=False
            if not alive:
                state.update(state='failed',error='Remote runner exited without a completion record')
                write(d/'status.json',state)
        if action=='cancel' and state['state']=='queued':
            (d/'cancel_requested').touch()
            state['state']='cancelled';write(d/'status.json',state)
        if action == 'cancel' and state['state'] == 'working':
            (d/'cancel_requested').touch()
            pid = state['pid']
            # A pid can be reused: match the kernel process start time before signalling.
            try:
                if Path(f'/proc/{pid}/stat').read_text().split()[21] == state['process_start']:
                    os.killpg(pid, signal.SIGTERM)
                    state['state'] = 'cancelling'
            except ProcessLookupError: pass
            except FileNotFoundError: pass
        events = []
        path = d/'events.jsonl'
        if path.exists():
            with path.open('rb') as f:
                size = f.seek(0, 2); f.seek(max(0, size-200000))
                if size > 200000: f.readline()
                for line in f:
                    try: events.append(json.loads(line))
                    except ValueError: pass
        state['events'] = events[-120:]
        return state
    raise ValueError('Unknown remote operation')


def work(d):
    req = json.loads((d/'request.json').read_text())
    p = project(req['project'])
    binary = executable(req['engine']) if req['engine']!='command' else '/bin/bash'
    prompt = ("Owner-requested task. Read applicable AGENTS.md and CLAUDE.md. Work only on this assignment. "
              "Preserve existing edits and running experiments; do not create paid cloud resources, delete data, "
              "send messages or change credentials. Report exact commands, seeds, data/checkpoint paths, git revision, "
              "metrics, limitations and artifact paths. Keep assigned commands in the foreground under this runner: "
              "do not detach experiments into tmux/nohup or unrelated process groups. Do not invent success.\n\n" + req['prompt'])
    if req['engine'] == 'codex':
        cmd = [binary, 'exec', '--json', '--sandbox', 'workspace-write', '-m', req['model'], '-']
    elif req['engine']=='claude':
        cmd = [binary, '-p', '--output-format', 'stream-json', '--verbose', '--permission-mode', 'acceptEdits',
               '--allowedTools', 'Read,Glob,Grep,Edit,Write,Bash', '--max-turns', '40']
    else:
        # Explicit command from the already-authenticated local Codex teammate.
        # It remains task-scoped and never interpolates into the SSH transport.
        cmd = [binary, '-c', req['prompt']]
    env = os.environ.copy()
    for name in ['OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_OAUTH_TOKEN']:
        env.pop(name, None)
    start = time.time()
    state = {'job_id': req['job_id'], 'state': 'working', 'engine': req['engine'], 'model': req['model'],
             'project': str(p), 'started_at': start, 'pid': os.getpid(),
             'process_start': Path(f'/proc/{os.getpid()}/stat').read_text().split()[21]}
    write(d/'status.json', state)
    if (d/'cancel_requested').exists():
        state.update(state='cancelled',finished_at=time.time());write(d/'status.json',state);return
    try:
        with (d/'engine-error.log').open('ab') as err, (d/'events.jsonl').open('a') as events:
            proc = subprocess.Popen(cmd, cwd=p, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, text=True)
            if req['engine']!='command':proc.stdin.write(prompt)
            proc.stdin.close()
            # A separate watchdog enforces the requested wall-clock limit even during silent output.
            import threading
            expired = threading.Event()
            def timeout():
                expired.set()
                timed=dict(state,state='timed_out',finished_at=time.time())
                write(d/'status.json',timed)
                try: os.killpg(os.getpgrp(), signal.SIGTERM)
                except ProcessLookupError: pass
            timer = threading.Timer(req['timeout_minutes']*60, timeout); timer.daemon=True; timer.start()
            failed = False
            for line in iter(lambda:proc.stdout.readline(65536),''):
                if req['engine']=='command':
                    events.write(json.dumps({'kind':'output','text':clean(line.rstrip()),'at':time.time()})+'\n');events.flush()
                    continue
                try:
                    row = json.loads(line)
                    if row.get('type') in {'turn.failed', 'error'} or row.get('is_error'): failed = True
                    event = visible(row)
                    if event:
                        event['at'] = time.time(); events.write(json.dumps(event)+'\n'); events.flush()
                except ValueError: pass
            code = proc.wait(); timer.cancel()
            if code != 0:
                with (d/'engine-error.log').open('rb') as log:
                    size=log.seek(0,2);log.seek(max(0,size-12000));diagnostic=log.read().decode(errors='replace')
                if diagnostic:
                    events.write(json.dumps({'kind':'error','text':clean(diagnostic),'at':time.time()})+'\n');events.flush()
            state.update(state='done' if code == 0 and not failed else 'failed', exit_code=code, finished_at=time.time())
    except Exception as e:
        state.update(state='failed', error=type(e).__name__, finished_at=time.time())
    write(d/'status.json', state)


if __name__ == '__main__':
    directory = Path(sys.argv[1]).resolve()
    # SIGTERM records an actual cancelled state before ending the entire job group.
    def stopped(signum, frame):
        state = json.loads((directory/'status.json').read_text())
        state.update(state='timed_out' if state.get('state')=='timed_out' else 'cancelled', finished_at=time.time())
        write(directory/'status.json', state)
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, stopped)
    try:work(directory)
    except Exception as exc:
        state=json.loads((directory/'status.json').read_text())
        state.update(state='failed',error=type(exc).__name__,finished_at=time.time())
        write(directory/'status.json',state)
