"""Private, loopback-only Ji Eun mission control. No inference or hidden reasoning."""
import base64
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
from urllib.parse import urlparse, parse_qs
from assistant_broker import request
from monitor import snapshot as service_snapshot

HOME = Path('/var/lib/personal-agent')
STATIC = Path('/opt/personal-agents/mission-control')
PASSWORD = Path(os.environ.get('CREDENTIALS_DIRECTORY', '/etc/personal-agents')) / 'monitor_password'
PORT = 9120
UUID = re.compile(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}')
_cache = {}


def clean(value, limit=10000):
    value = str(value)
    value = re.sub(r'(?i)(Bearer|Bot)\s+[A-Za-z0-9._-]{12,}', r'\1 [redacted]', value)
    value = re.sub(r'\bsk-[A-Za-z0-9_-]{12,}', '[redacted]', value)
    value = re.sub(r'(?i)(["\']?(?:access_token|refresh_token|bot_token|password|api_key|authorization)["\']?\s*[:=]\s*)["\']?[^\s,"\'}]+', r'\1[redacted]', value)
    return value[:limit]


def tail_events(path):
    """Bounded read of our own service's rollout; never accepts a URL/file from HTTP."""
    path = Path(path).resolve()
    if not path.is_relative_to(HOME / 'codex/sessions') or not path.is_file():
        return []
    info = path.stat()
    key = (info.st_mtime_ns, info.st_size)
    if path in _cache and _cache[path][0] == key:
        return _cache[path][1]
    with path.open('rb') as stream:
        size = stream.seek(0, 2)
        stream.seek(max(0, size - 1500000))
        if size > 1500000:
            stream.readline()
        lines = stream.read().splitlines()
    events = []
    for line in lines:
        try:
            row = json.loads(line)
        except (ValueError, TypeError):
            continue
        p = row.get('payload') or {}
        kind = p.get('type', '')
        at = row.get('timestamp', '')
        if row.get('type') == 'event_msg' and kind in {'task_started', 'task_complete', 'turn_aborted', 'error', 'agent_error'}:
            events.append({'at': at, 'kind': kind, 'text': clean(p.get('message') or kind.replace('_', ' '))})
        elif row.get('type') == 'response_item':
            if kind == 'message' and p.get('role') in {'user', 'assistant'}:
                # Only visible conversation; exclude analysis and imported context.
                if p.get('channel') not in {None, 'final', 'commentary'}:
                    continue
                content = p.get('content') or []
                text = '\n'.join(c.get('text', '') for c in content if c.get('type') in {'input_text', 'output_text', 'text'})
                if p.get('role') == 'user' and ('<system' in text or '# AGENTS.md' in text or '<environment_context>' in text):
                    continue
                if text:
                    events.append({'at': at, 'kind': p['role'], 'text': clean(text)})
            elif kind in {'function_call', 'custom_tool_call', 'function_call_output', 'custom_tool_call_output', 'agent_message'}:
                text = p.get('arguments') or p.get('input') or p.get('output') or p.get('message') or ''
                if not isinstance(text, str):
                    text = json.dumps(text, ensure_ascii=False)
                events.append({'at': at, 'kind': kind, 'tool': clean(p.get('name', '')), 'text': clean(text)})
    result = events[-160:]
    if len(_cache) > 100:
        _cache.clear()
    _cache[path] = (key, result)
    return result


def thread_rows():
    database = HOME / 'codex/state_5.sqlite'
    if not database.exists():
        return []
    with sqlite3.connect('file:' + str(database) + '?mode=ro', uri=True, timeout=2) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute('SELECT id,source,agent_role,agent_nickname,model,title,rollout_path,updated_at FROM threads ORDER BY updated_at DESC LIMIT 60')]


def threads():
    result = []
    profile_roles = {}
    # Match actual Hermes ownership; titles and model names do not identify a bot.
    databases = [HOME / '.hermes/state.db', *sorted((HOME / '.hermes/profiles').glob('*/state.db'))]
    for database in databases:
        try:
            with sqlite3.connect('file:' + str(database) + '?mode=ro', uri=True, timeout=2) as db:
                for profile, config in db.execute('SELECT profile_name,model_config FROM sessions WHERE model_config IS NOT NULL'):
                    try:
                        identifier = json.loads(config).get('codex_thread_id')
                    except (ValueError, TypeError, AttributeError):
                        continue
                    if identifier:
                        profile_roles[identifier] = 'Ji An' if profile == 'ji-an' else (profile if profile and profile != 'default' else 'Ji Eun')
        except sqlite3.Error:
            continue
    for row in thread_rows():
        events = tail_events(row.pop('rollout_path'))
        parent = ''
        try:
            parent = json.loads(row.pop('source')).get('subagent', {}).get('thread_spawn', {}).get('parent_thread_id', '')
        except (ValueError, TypeError):
            row.pop('source', None)
        state = 'unknown'
        for event in events:
            if event['kind'] == 'task_started':
                state = 'working'
            elif event['kind'] == 'task_complete':
                state = 'done'
            elif event['kind'] in {'turn_aborted', 'error', 'agent_error'}:
                state = 'stopped' if event['kind'] == 'turn_aborted' else 'failed'
        row.update(parent_id=parent, state=state, title=clean(row.get('title', ''), 180),
                   role=row.get('agent_role') or profile_roles.get(row['id'], 'Ji Eun'), latest=events[-1] if events else None,
                   event_count=len(events))
        result.append(row)
    return result


def logs(identifier):
    if not UUID.fullmatch(identifier):
        raise ValueError('Invalid agent ID')
    for row in thread_rows():
        if row['id'] == identifier:
            return tail_events(row['rollout_path'])
    raise ValueError('Agent not found')


def task_logs(identifier):
    if not re.fullmatch(r't_[a-f0-9]{8,32}', identifier):
        raise ValueError('Invalid task ID')
    with sqlite3.connect('file:' + str(HOME / '.hermes/kanban.db') + '?mode=ro', uri=True, timeout=2) as db:
        db.row_factory = sqlite3.Row
        row = db.execute('SELECT title,status,result,last_failure_error FROM tasks WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise ValueError('Task not found')
        events = [{'kind':'task', 'at':'', 'text':clean(row['title']) + '\nStatus: ' + row['status']}]
        if row['last_failure_error']:
            events.append({'kind':'last failure', 'at':'', 'text':clean(row['last_failure_error'])})
        if row['result']:
            events.append({'kind':'result', 'at':'', 'text':clean(row['result'])})
        for item in db.execute('SELECT kind,payload,created_at FROM task_events WHERE task_id=? ORDER BY id DESC LIMIT 80', (identifier,)).fetchall()[::-1]:
            from datetime import datetime, timezone
            events.append({'kind':item['kind'], 'at':datetime.fromtimestamp(item['created_at'],timezone.utc).isoformat(), 'text':clean(item['payload'])})
        for item in db.execute('SELECT * FROM task_comments WHERE task_id=? ORDER BY id DESC LIMIT 20', (identifier,)).fetchall()[::-1]:
            events.append({'kind':'handoff/comment', 'at':'', 'text':clean(dict(item))})
    return events


def snapshot():
    try:
        result = service_snapshot()
    except (OSError, ValueError):
        result = {'services': {}, 'activities': [], 'events': [], 'board': [], 'reminders': {}, 'deliveries': [], 'error': 'Data broker unavailable'}
    result['threads'] = threads()
    if result.get('services', {}).get('gateway') != 'active':
        for row in result['threads']:
            if row['state'] == 'working':
                row['state'] = 'unconfirmed'
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = 'JiEunMissionControl/1.0'

    def log_message(self, fmt, *args):
        # No requests, task contents, cookies, or credentials in access logs.
        pass

    def authorized(self):
        if self.headers.get('Host') not in {f'127.0.0.1:{PORT}', f'localhost:{PORT}'}:
            self.reply(403, {'error': 'Unexpected host'})
            return False
        expected = 'Basic ' + base64.b64encode(('ji-eun:' + PASSWORD.read_text().strip()).encode()).decode()
        if not hmac.compare_digest(self.headers.get('Authorization', ''), expected):
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Basic realm="Ji Eun private mission control"')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return False
        return True

    def reply(self, code, data, mime='application/json'):
        raw = json.dumps(data, ensure_ascii=False).encode() if mime == 'application/json' else data
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if not self.authorized():
            return
        url = urlparse(self.path)
        try:
            if url.path == '/api/state':
                self.reply(200, snapshot())
            elif url.path == '/api/logs':
                self.reply(200, {'events': logs(parse_qs(url.query).get('id', [''])[0])})
            elif url.path == '/api/task':
                self.reply(200, {'events': task_logs(parse_qs(url.query).get('id', [''])[0])})
            elif url.path == '/api/research':
                identifier=parse_qs(url.query).get('id',[''])[0]
                if not re.fullmatch(r'r_[a-f0-9]{24}', identifier):
                    raise ValueError('Invalid research task ID')
                row=request('research_task',{'task_id':identifier})
                detail=row.get('detail',{})
                events=[{'kind':'research job','at':row['updated_at'],'text':clean(row['title']+'\n'+row['host']+' · '+row['engine']+' · '+row['state'])}]
                if detail.get('connection_error'):
                    events.append({'kind':'connection','at':row['updated_at'],'text':clean(detail['connection_error'])})
                from datetime import datetime, timezone
                for event in detail.get('events',[]):
                    events.append({'kind':event['kind'],'at':datetime.fromtimestamp(event['at'],timezone.utc).isoformat(),'text':clean(event['text'])})
                self.reply(200,{'events':events})
            elif url.path == '/api/service-log':
                path = HOME / '.hermes/logs/gateway.log'
                with path.open('rb') as stream:
                    stream.seek(max(0, stream.seek(0, 2) - 20000))
                    content = stream.read().decode('utf-8', errors='replace')
                self.reply(200, {'text': clean(content, 20000)})
            elif url.path in {'/', '/index.html', '/app.js', '/styles.css'}:
                name = 'index.html' if url.path == '/' else url.path[1:]
                self.reply(200, (STATIC / name).read_bytes(), {'index.html':'text/html; charset=utf-8', 'app.js':'text/javascript; charset=utf-8', 'styles.css':'text/css; charset=utf-8'}[name])
            else:
                self.reply(404, {'error': 'Not found'})
        except ValueError as exc:
            self.reply(400, {'error': str(exc)})
        except (OSError, sqlite3.Error, subprocess.SubprocessError):
            self.reply(503, {'error': 'Monitor source unavailable; inspect server services'})

    def do_POST(self):
        if not self.authorized():
            return
        if self.headers.get('Origin') not in {f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}'}:
            self.reply(403, {'error': 'Same-origin request required'})
            return
        if self.path != '/api/control':
            self.reply(404, {'error': 'Not found'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 200:
                raise ValueError('Invalid request size')
            action = json.loads(self.rfile.read(length)).get('action')
            if action not in {'pause', 'resume'}:
                raise ValueError('Unknown control')
            result = subprocess.run(['/var/lib/personal-agent/.local/bin/hermes', action], cwd=HOME, capture_output=True, text=True, timeout=30)
            if result.returncode==0 and (HOME/'.config/ji-an-discord.json').exists():
                peer=subprocess.run(['/var/lib/personal-agent/.local/bin/hermes','--profile','ji-an',action],cwd=HOME,capture_output=True,text=True,timeout=30)
                if peer.returncode:result=peer
            self.reply(200 if result.returncode == 0 else 503, {'ok': result.returncode == 0, 'message': clean(result.stdout + result.stderr, 2000)})
        except (ValueError, TypeError):
            self.reply(400, {'error': 'Invalid control request'})
        except subprocess.SubprocessError:
            self.reply(503, {'error': 'Control timed out; inspect server status'})


if __name__ == '__main__':
    server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    server.daemon_threads = True
    print(f'Ji Eun mission control: http://127.0.0.1:{PORT}', flush=True)
    server.serve_forever()
