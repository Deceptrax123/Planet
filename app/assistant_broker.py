"""Local Unix-socket MCP backend; memory is outside agent-writable workspaces."""
import argparse
import inspect
import json
import os
from pathlib import Path
import pwd
import socket
import socketserver
import struct
import sys
from datetime import datetime, timezone, timedelta
from assistant_store import Store, now_iso

SOCKET = "/run/personal-agent-data/broker.sock"
STATE = "/var/lib/personal-agent-data"


class Backend:
    def __init__(self, state=STATE, shared="/var/lib/personal-agent-data/shared-memory"):
        self.store = Store(state, shared)
        with self.store.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS activities (
              agent TEXT, task_id TEXT, parent_id TEXT, state TEXT NOT NULL,
              summary TEXT NOT NULL, model TEXT, updated_at TEXT NOT NULL,
              PRIMARY KEY(agent,task_id));
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY, agent TEXT, task_id TEXT, event TEXT,
              summary TEXT, at TEXT NOT NULL);
            """)

    def activity_report(self, agent, task_id, state, summary, model="", parent_id=""):
        if state not in {"working", "waiting", "done", "failed", "idle", "tool"}:
            raise ValueError("Unknown activity state")
        if not agent or not task_id or len(summary) > 600:
            raise ValueError("Agent, task ID and a summary up to 600 characters are required")
        with self.store.connect() as db:
            db.execute("INSERT OR REPLACE INTO activities VALUES (?,?,?,?,?,?,?)", (agent[:80], task_id[:160], parent_id[:160], state, summary, model[:100], now_iso()))
            db.execute("INSERT INTO events(agent,task_id,event,summary,at) VALUES (?,?,?,?,?)", (agent[:80], task_id[:160], state, summary, now_iso()))
            db.execute("DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 10000)")
        return {"recorded": True}

    def assistant_status(self):
        from whatsapp_delivery import status as whatsapp_status
        with self.store.connect() as db:
            activities = [dict(r) for r in db.execute("SELECT * FROM activities ORDER BY updated_at DESC LIMIT 40")]
            events = [dict(r) for r in db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 30")]
            deliveries = [dict(r) for r in db.execute("SELECT id,reminder_id,delivery_channel,status,attempts,last_error,sent_at FROM outbox ORDER BY due_at DESC LIMIT 20")]
            counts = dict(db.execute("SELECT status,count(*) FROM reminders GROUP BY status").fetchall())
        return {"at": now_iso(), "activities": activities, "events": events, "reminders": counts, "deliveries": deliveries, 'whatsapp':whatsapp_status(),
                "timezone": "Asia/Kolkata", "quiet_hours": "23:00–09:00", "quiet_hours_apply_to": "standalone reminders",
                "proactive_conversations": "Any time; no prescribed frequency, cooldown or quota; event deduplication and expiry apply", "voice": "disabled"}

    def delivery_history(self, limit=10):
        if not 1 <= limit <= 30:
            raise ValueError("limit must be 1..30")
        with self.store.connect() as db:
            return [dict(r) for r in db.execute("SELECT id,reminder_id,delivery_channel,text,due_at,status,message_id,last_error,sent_at FROM outbox ORDER BY due_at DESC LIMIT ?", (limit,))]

    def research_event(self, task_id):
        # Read task state from the isolated broker; callers cannot supply a fake outcome.
        task=request('research_task',{'task_id':task_id},socket_path='/run/personal-agent-research/broker.sock')
        state=task['state']
        wording={'done':'The run has finished. Ji An can review the recorded output.',
                 'failed':'The run hit an error. Its diagnostics are in the monitor.',
                 'timed_out':'The run reached its time limit.',
                 'connection_lost':'I lost the connection. The remote job may still be running; its outcome is unconfirmed.'}
        if state not in wording:return {'status':'no_alert'}
        return self.store.notify_owner(text=task['title']+' on '+task['host']+': '+wording[state],
            event_key='research:'+task_id+':'+state,
            source='https://discord.com/channels/1248530615662284810/1569058485033894160',
            reason='Verified lifecycle change of the owner-requested research task '+task_id,
            expires_at=(datetime.now(timezone.utc)+timedelta(hours=24)).isoformat())

    def dispatch(self, method, args):
        if method in {'research_status','research_probe','research_submit','research_task','research_cancel','research_retry'}:
            return request(method, args, socket_path='/run/personal-agent-research/broker.sock', timeout=120)
        methods = {
            "memory_context": self.store.recall, "memory_record": self.store.remember,
            "memory_forget": self.store.forget, "reminder_create": self.store.add_reminder,
            "reminder_list": self.store.reminders, "reminder_change": self.store.change_reminder,
            "activity_report": self.activity_report, "assistant_status": self.assistant_status,
            "delivery_history": self.delivery_history,
            "notify_owner": self.store.notify_owner,
            'research_event':self.research_event,
        }
        if method not in methods:
            raise ValueError("Unknown tool")
        signature = inspect.signature(methods[method])
        signature.bind(**args)
        return methods[method](**args)


def request(method, args=None, socket_path=SOCKET, timeout=10):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(socket_path)
        client.sendall(json.dumps({"method": method, "args": args or {}}).encode() + b"\n")
        with client.makefile("rb") as stream:
            data = stream.readline(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError("Broker response too large")
        result = json.loads(data)
        if "error" in result:
            raise ValueError(result["error"])
        return result["result"]


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(10)
        _, uid, _ = struct.unpack("3i", self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        research_uid = getattr(self.server, 'research_uid', None)
        if uid not in self.server.allowed_uids and uid != research_uid:
            return
        raw = self.rfile.readline(1_000_001)
        try:
            if len(raw) > 1_000_000:
                raise ValueError("Request too large")
            data = json.loads(raw)
            if uid == research_uid and data.get('method') not in {'activity_report','research_event'}:
                raise ValueError('Research service may only report its progress to the memory broker')
            result = {"result": self.server.backend.dispatch(data["method"], data.get("args", {}))}
        except (ValueError, TypeError, KeyError) as exc:
            result = {"error": str(exc)[:300]}
        except Exception as exc:
            # No private record content or provider credentials in error logs.
            print("Broker operation failed: " + type(exc).__name__, file=sys.stderr, flush=True)
            result = {"error": "Local data operation failed; inspect service status."}
        self.wfile.write(json.dumps(result, ensure_ascii=False).encode() + b"\n")


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default=SOCKET)
    parser.add_argument("--state", default=STATE)
    parser.add_argument("--shared", default=STATE + "/shared-memory")
    args = parser.parse_args()
    path = Path(args.socket)
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    with Server(str(path), Handler) as server:
        server.backend = Backend(args.state, args.shared)
        server.allowed_uids = {0, os.getuid(), pwd.getpwnam("personal-agent").pw_uid}
        try: server.research_uid = pwd.getpwnam('personal-agent-research').pw_uid
        except KeyError: server.research_uid = None
        os.chmod(path, 0o660)
        os.chown(path, -1, pwd.getpwnam("personal-agent").pw_gid)
        print("Personal data broker ready", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
