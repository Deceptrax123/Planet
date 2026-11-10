"""Portable, temporal personal memory and durable reminder state (stdlib only)."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import uuid
import ipaddress
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

UTC = timezone.utc
TOPICS = {"health", "nutrition", "routine", "preferences", "schedule", "work", "research", "subscriptions", "relationships", "identity"}


def now_iso():
    return datetime.now(UTC).isoformat()


def instant(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Supply an ISO datetime with an explicit UTC offset; do not guess the timezone.")
    return result.astimezone(UTC).isoformat()


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".write-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Store:
    def __init__(self, state, shared=None):
        self.root = Path(state)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "assistant.sqlite"
        self.shared = Path(shared) if shared else None
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS memory (
              id TEXT PRIMARY KEY, fact_key TEXT, topic TEXT NOT NULL, text TEXT NOT NULL,
              tags TEXT NOT NULL, source TEXT NOT NULL, source_type TEXT NOT NULL,
              confidence REAL NOT NULL, status TEXT NOT NULL, importance TEXT NOT NULL,
              valid_from TEXT NOT NULL, valid_until TEXT, observed_at TEXT NOT NULL,
              review_after TEXT, supersedes TEXT, timezone TEXT NOT NULL,
              sensitivity TEXT NOT NULL, recurrence TEXT NOT NULL DEFAULT '{}');
            CREATE INDEX IF NOT EXISTS memory_topic_time ON memory(topic,valid_from,valid_until);
            CREATE TABLE IF NOT EXISTS forgotten (id TEXT PRIMARY KEY, forgotten_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit (
              id INTEGER PRIMARY KEY, record_id TEXT, action TEXT, at TEXT, source TEXT);
            CREATE TABLE IF NOT EXISTS reminders (
              id TEXT PRIMARY KEY, idem_key TEXT UNIQUE NOT NULL, text TEXT NOT NULL,
              due_at TEXT NOT NULL, timezone TEXT NOT NULL, repeat TEXT NOT NULL,
              status TEXT NOT NULL, source TEXT NOT NULL, allow_quiet INTEGER NOT NULL,
              event_provider TEXT, event_calendar TEXT, event_id TEXT, event_start TEXT,
              offset_minutes INTEGER, last_error TEXT, created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS reminders_due ON reminders(status,due_at);
            CREATE TABLE IF NOT EXISTS outbox (
              id TEXT PRIMARY KEY, reminder_id TEXT, text TEXT NOT NULL, due_at TEXT NOT NULL,
              status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
              next_attempt TEXT, message_id TEXT, last_error TEXT, sent_at TEXT);
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS mutations (
              key TEXT PRIMARY KEY, status TEXT NOT NULL, result TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS notifications (
              id TEXT PRIMARY KEY, event_key TEXT UNIQUE NOT NULL, source TEXT NOT NULL,
              priority TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'update', image_url TEXT);
            """)
            columns = {r[1] for r in db.execute("PRAGMA table_info(notifications)")}
            if "kind" not in columns:
                db.execute("ALTER TABLE notifications ADD COLUMN kind TEXT NOT NULL DEFAULT 'update'")
            if "image_url" not in columns:
                db.execute("ALTER TABLE notifications ADD COLUMN image_url TEXT")
            for table in ['reminders', 'outbox']:
                if 'delivery_channel' not in {r[1] for r in db.execute('PRAGMA table_info('+table+')')}:
                    db.execute('ALTER TABLE '+table+" ADD COLUMN delivery_channel TEXT NOT NULL DEFAULT 'discord'")
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def export(self):
        with self.connect() as db:
            memories = [dict(row) for row in db.execute("SELECT * FROM memory ORDER BY observed_at")]
            forgotten = [dict(row) for row in db.execute("SELECT * FROM forgotten")]
        atomic_json(self.root / "exports" / "memory.json", {
            "schema_version": 1, "exported_at": now_iso(), "records": memories, "forgotten": forgotten,
        })

    def remember(self, topic, text, source, source_type="user", confirmed=False,
                 tags=None, confidence=0.8, importance="normal", fact_key=None,
                 valid_from=None, valid_until=None, review_after=None,
                 supersedes=None, timezone_name="Asia/Kolkata", recurrence=None):
        if type(confirmed) is not bool:
            raise ValueError("confirmed must be a boolean.")
        if topic.split("/")[0] not in TOPICS:
            raise ValueError("Unknown topic; choose " + ", ".join(sorted(TOPICS)))
        if not 1 <= len(text.strip()) <= 4000 or not 1 <= len(source.strip()) <= 1500:
            raise ValueError("Memory needs concise text and its exact source.")
        if source_type not in {"user", "email", "calendar", "document", "inference"}:
            raise ValueError("Invalid source type.")
        if confirmed and source_type != "user":
            raise ValueError("Only direct user statements may be stored as user-confirmed.")
        if importance not in {"normal", "high", "critical"} or not 0 <= confidence <= 1:
            raise ValueError("Invalid importance or confidence.")
        ZoneInfo(timezone_name)
        start = instant(valid_from) if valid_from else now_iso()
        end = instant(valid_until) if valid_until else None
        if end and end <= start:
            raise ValueError("valid_until must be after valid_from.")
        if review_after:
            datetime.fromisoformat(review_after)
        rule = recurrence or {}
        if set(rule) - {"weekdays", "start_local", "end_local"}:
            raise ValueError("Routine rules accept weekdays and local start/end times only.")
        if "weekdays" in rule and (not isinstance(rule["weekdays"], list) or not all(type(x) is int and 0 <= x <= 6 for x in rule["weekdays"])):
            raise ValueError("weekdays must be a list of Monday=0 through Sunday=6.")
        for key in ["start_local", "end_local"]:
            if key in rule and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", rule[key]):
                raise ValueError("Routine local times must be HH:MM.")
        if bool(rule.get("start_local")) != bool(rule.get("end_local")):
            raise ValueError("Supply both routine start_local and end_local, or neither.")
        record_id = "m_" + uuid.uuid4().hex[:20]
        status = "confirmed" if confirmed else "candidate"
        observed = now_iso()
        with self.connect() as db:
            # Candidates cannot displace confirmed health facts or other accepted knowledge.
            replace = []
            if confirmed:
                if supersedes:
                    previous = db.execute("SELECT * FROM memory WHERE id=?", (supersedes,)).fetchone()
                    if previous is None:
                        raise ValueError("Unknown memory ID to correct.")
                    replace = [previous]
                elif fact_key:
                    replace = db.execute("SELECT * FROM memory WHERE fact_key=? AND status='confirmed' AND (valid_until IS NULL OR valid_until>?)", (fact_key, start)).fetchall()
                for old in replace:
                    if old["valid_from"] > start:
                        raise ValueError("Correction precedes an existing future record; correct that record explicitly.")
                    old_end = min(old["valid_until"], start) if old["valid_until"] else start
                    # A temporary exception preserves the older routine after the exception ends.
                    if end and old["valid_from"] < end and (not old["valid_until"] or old["valid_until"] > end):
                        tail = dict(old)
                        tail["id"] = "m_" + uuid.uuid4().hex[:20]
                        tail["valid_from"] = end
                        tail["observed_at"] = observed
                        columns = list(tail)
                        db.execute("INSERT INTO memory (" + ",".join(columns) + ") VALUES (" + ",".join("?" for _ in columns) + ")", [tail[k] for k in columns])
                    db.execute("UPDATE memory SET valid_until=? WHERE id=?", (old_end, old["id"]))
            values = (record_id, fact_key, topic, text.strip(), json.dumps(tags or []), source.strip(), source_type,
                      confidence, status, importance, start, end, observed, review_after, supersedes,
                      timezone_name, "health" if topic.startswith("health") else "personal", json.dumps(rule))
            db.execute("INSERT INTO memory VALUES (" + ",".join("?" for _ in values) + ")", values)
            db.execute("INSERT INTO audit(record_id,action,at,source) VALUES (?,?,?,?)", (record_id, "record", observed, source))
        self.export()
        return {"id": record_id, "status": status, "valid_from": start, "valid_until": end}

    def forget(self, record_id, source):
        if not record_id or not source:
            raise ValueError("Memory ID and user's deletion request source are required.")
        with self.connect() as db:
            # Purge content and audit source, retaining only a content-free tombstone.
            db.execute("DELETE FROM memory WHERE id=?", (record_id,))
            db.execute("DELETE FROM audit WHERE record_id=?", (record_id,))
            db.execute("INSERT OR REPLACE INTO forgotten VALUES (?,?)", (record_id, now_iso()))
        self.export()
        return {"forgotten": record_id, "note": "Removed from live recall and current export. Existing protected backups age out under retention; upstream shared-memory archives require separate cleanup."}

    def recall(self, query, topics=None, at=None, include_candidates=True, limit=12):
        if not 1 <= limit <= 30:
            raise ValueError("limit must be 1..30")
        when = instant(at) if at else now_iso()
        keywords = set(re.findall(r"[\w]+", query.casefold())) - {"i", "a", "the", "want", "to", "my", "me", "for", "of", "what", "is", "and"}
        hinted = set(topics or [])
        if re.search(r"protein|shake|food|eat|meal|diet|drink|supplement|whey|smoothie|restaurant|lunch|dinner|breakfast|snack|hungry|hunger|calorie|allerg", query, re.I):
            hinted.update({"health", "nutrition", "routine", "preferences"})
        if re.search(r"remind|schedule|calendar|meeting|today|tomorrow|routine|brief", query, re.I):
            hinted.update({"routine", "schedule", "work", "preferences"})
        if re.search(r"paper|science|scientific|research|experiment", query, re.I):
            hinted.update({"research", "work"})
        with self.connect() as db:
            forgotten = {r[0] for r in db.execute("SELECT id FROM forgotten")}
            rows = [dict(r) for r in db.execute("SELECT * FROM memory WHERE valid_from<=? AND (valid_until IS NULL OR valid_until>?)", (when, when))]
        if self.shared and (self.shared / "records.json").is_file():
            for item in json.loads((self.shared / "records.json").read_text(encoding="utf-8")):
                if item.get("status") != "accepted" or not isinstance(item.get("text"), str):
                    continue
                if item.get("created_at", "") > when:
                    continue
                rows.append({"id": item["id"], "topic": item["topic"], "text": item["text"],
                             "tags": "[]", "status": "confirmed", "source": item["source"], "source_type": "document",
                             "confidence": 0.8, "importance": "high" if item.get("importance") == "high" else "normal",
                             "review_after": item.get("review_after"), "observed_at": item["created_at"],
                             "timezone": "Asia/Kolkata", "recurrence": "{}"})
        scored = []
        for row in rows:
            if row["id"] in forgotten or (row["status"] == "candidate" and not include_candidates):
                continue
            local = datetime.fromisoformat(when).astimezone(ZoneInfo(row.get("timezone", "Asia/Kolkata")))
            rule = json.loads(row.get("recurrence", "{}"))
            start, end = rule.get("start_local"), rule.get("end_local")
            local_time = local.strftime("%H:%M")
            # For overnight windows, after-midnight activity belongs to the prior routine day.
            routine_day = local - timedelta(days=1) if start and start > end and local_time < end else local
            in_window = (not start or (start <= local_time < end if start <= end else local_time >= start or local_time < end))
            applies_now = in_window and ("weekdays" not in rule or routine_day.weekday() in rule["weekdays"])
            # Keep routines in context for planning ahead, explicitly label whether they apply now.
            haystack = (row["topic"] + " " + row["text"] + " " + row["tags"]).casefold()
            hits = sum(1 for word in keywords if word in haystack)
            topic_match = any(row["topic"] == t or row["topic"].startswith(t + "/") for t in hinted)
            critical = row["importance"] == "critical" and row["status"] == "confirmed"
            if not hits and not topic_match and not critical:
                continue
            stale = bool(row.get("review_after") and row["review_after"][:10] < when[:10])
            row["needs_review"] = stale
            row["routine_applies_at_query_time"] = applies_now if rule else None
            score = hits * 3 + topic_match * 5 + critical * 50 + (row["status"] == "confirmed") * 3 - stale * 2
            scored.append((score, row))
        scored.sort(key=lambda pair: (pair[0], pair[1]["observed_at"]), reverse=True)
        return {"as_of": when, "matches": [r for _, r in scored[:limit]],
                "policy": "Confirmed facts are evidence, not absolute vetoes. Candidates require verification. Explain relevant conflicts; do not invent medical contraindications. Check validity, routine time and needs_review."}

    def add_reminder(self, text, due_at, source, idempotency_key, timezone_name="Asia/Kolkata", repeat="none", allow_quiet=False,
                     event_provider=None, event_calendar=None, event_id=None, event_start=None, offset_minutes=None, delivery_channel='discord'):
        if type(allow_quiet) is not bool:
            raise ValueError('allow_quiet must be a boolean.')
        if delivery_channel not in {'discord','whatsapp'}:
            raise ValueError('Choose discord or whatsapp for delivery_channel.')
        due = instant(due_at)
        ZoneInfo(timezone_name)
        if not text.strip() or len(text) > 1600 or not source or not idempotency_key:
            raise ValueError("Reminder text, source and idempotency key are required.")
        if repeat not in {"none", "daily", "weekdays", "weekly"}:
            raise ValueError("Supported reminder repeat values: none, daily, weekdays, weekly.")
        if event_provider and (event_provider != "google" or not all([event_calendar, event_id, event_start]) or repeat != "none"):
            raise ValueError("Event reminders currently require one specific Google event occurrence and repeat=none.")
        record_id = "r_" + uuid.uuid4().hex[:20]
        with self.connect() as db:
            existing = db.execute("SELECT * FROM reminders WHERE idem_key=?", (idempotency_key,)).fetchone()
            if existing:
                if existing["text"] != text or existing["source"] != source or existing["timezone"] != timezone_name or existing["repeat"] != repeat or existing['delivery_channel'] != delivery_channel:
                    raise ValueError("Idempotency key already belongs to a different request.")
                return dict(existing)
            db.execute("INSERT INTO reminders(id,idem_key,text,due_at,timezone,repeat,status,source,allow_quiet,event_provider,event_calendar,event_id,event_start,offset_minutes,last_error,created_at,delivery_channel) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (record_id, idempotency_key, text, due, timezone_name, repeat, "pending", source, bool(allow_quiet),
                        event_provider, event_calendar, event_id, instant(event_start) if event_start else None,
                        offset_minutes, None, now_iso(), delivery_channel))
        return {"id": record_id, "due_at": due, "timezone": timezone_name, "status": "pending", "repeat": repeat, 'delivery_channel':delivery_channel}

    def reminders(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM reminders ORDER BY due_at DESC LIMIT 100")]

    def change_reminder(self, reminder_id, action, due_at=None):
        if action not in {"cancel", "done", "snooze"}:
            raise ValueError("action must be cancel, done, or snooze")
        with self.connect() as db:
            row = db.execute("SELECT * FROM reminders WHERE id=?", (reminder_id,)).fetchone()
            if not row:
                raise ValueError("Unknown reminder")
            if db.execute("SELECT 1 FROM outbox WHERE reminder_id=? AND status='sending'", (reminder_id,)).fetchone():
                raise ValueError("A send is in flight; wait for its result before changing this reminder.")
            db.execute("UPDATE outbox SET status='cancelled' WHERE reminder_id=? AND status IN ('pending','retry')", (reminder_id,))
            if action == "snooze":
                if not due_at:
                    raise ValueError("snooze requires due_at")
                db.execute("UPDATE reminders SET status='pending',due_at=?,last_error=NULL WHERE id=?", (instant(due_at), reminder_id))
            else:
                db.execute("UPDATE reminders SET status=? WHERE id=?", ("cancelled" if action == "cancel" else "done", reminder_id))
        return {"id": reminder_id, "action": action}

    def enqueue(self, text, due_at, key, reminder_id=None):
        item_id = hashlib.sha256(key.encode()).hexdigest()[:24]
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO outbox(id,reminder_id,text,due_at,status) VALUES (?,?,?,?,?)",
                       (item_id, reminder_id, text, instant(due_at), "pending"))
        return item_id

    def notify_owner(self, text, event_key, source, reason, expires_at, priority="important", kind="update", image_url=None, delivery_channel='discord'):
        """Owner-authorized anytime outreach with event deduplication and expiry."""
        if delivery_channel not in {'discord','whatsapp'}:
            raise ValueError('Choose discord or whatsapp for delivery_channel.')
        if priority not in {"important", "urgent"}:
            raise ValueError("Use important or urgent for actionable notifications.")
        if not text.strip() or len(text) > 1500 or not 1 <= len(event_key) <= 240 or not reason.strip() or len(reason) > 500:
            raise ValueError("Provide concise text, a stable source event key and why it matters now.")
        if kind not in {"update", "conversation"}:
            raise ValueError("Use update or conversation.")
        if kind == "conversation" and priority != "important":
            raise ValueError("Casual conversation cannot claim urgent priority.")
        if (kind == "update" and not source.startswith("https://")) or len(source) > 1500:
            raise ValueError("Provide the verified source link; do not fabricate evidence.")
        if image_url:
            url = urlparse(image_url)
            host = url.hostname or ""
            if len(image_url) > 2000 or any(c.isspace() for c in image_url) or url.scheme != "https" or url.username or url.password or "." not in host or host.endswith((".local", ".internal", ".localhost")) or url.port not in {None,443}:
                raise ValueError("Use a public HTTPS image URL without credentials.")
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                address = None
            if address and not address.is_global:
                raise ValueError("Private image addresses are not allowed.")
        now = datetime.fromisoformat(now_iso())
        expires = datetime.fromisoformat(instant(expires_at))
        if not now < expires <= now + timedelta(days=1):
            raise ValueError("Expiry must be in the next 24 hours.")
        item_id = hashlib.sha256(("proactive:" + event_key).encode()).hexdigest()[:24]
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT id FROM notifications WHERE event_key=?", (event_key,)).fetchone()
            if previous:
                return {"status": "duplicate", "id": previous[0]}
            content = text.strip() + ("\n" + source if source.startswith("https://") else "")
            db.execute("INSERT INTO notifications(id,event_key,source,priority,reason,created_at,expires_at,kind,image_url) VALUES (?,?,?,?,?,?,?,?,?)", (item_id, event_key, source, priority, reason, now.isoformat(), expires.isoformat(), kind, image_url))
            db.execute("INSERT INTO outbox(id,text,due_at,status,delivery_channel) VALUES (?,?,?,?,?)", (item_id, content, now.isoformat(), "pending", delivery_channel))
        return {"status": "queued", "id": item_id, "expires_at": expires.isoformat()}
