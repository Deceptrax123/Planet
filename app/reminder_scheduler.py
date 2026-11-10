"""Deterministic reminder dispatcher; no model or Google credentials required."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import signal
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo
from assistant_store import Store, now_iso
from whatsapp_delivery import WhatsApp, WhatsAppUnavailable

UTC = timezone.utc
OWNER = "562571259758772254"


def quiet_end(when, allow=False):
    local = when.astimezone(ZoneInfo("Asia/Kolkata"))
    if allow or 9 <= local.hour < 23:
        return when
    if local.hour >= 23:
        local += timedelta(days=1)
    return local.replace(hour=9, minute=0, second=0, microsecond=0).astimezone(UTC)


def next_occurrence(row, after):
    if row["repeat"] == "none":
        return None
    local = datetime.fromisoformat(row["due_at"]).astimezone(ZoneInfo(row["timezone"]))
    increment = timedelta(days=7 if row["repeat"] == "weekly" else 1)
    while local.astimezone(UTC) <= after or (row["repeat"] == "weekdays" and local.weekday() > 4):
        local += increment
    # ZoneInfo recomputes UTC offsets across DST transitions.
    return local.astimezone(UTC).isoformat()


class RetryLater(Exception):
    def __init__(self, seconds):
        self.seconds = min(3600, max(1, float(seconds)))


class Discord:
    def __init__(self, token, store):
        self.token, self.store = token, store

    def api(self, path, body):
        request = urllib.request.Request("https://discord.com/api/v10" + path,
            data=json.dumps(body).encode(), headers={"Authorization": "Bot " + self.token,
            "Content-Type": "application/json", "User-Agent": "PersonalAssistant/1.0"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                try:
                    payload = json.load(exc)
                    seconds = payload.get("retry_after", 30)
                except (ValueError, TypeError):
                    seconds = 30
                raise RetryLater(seconds) from None
            # Error bodies can contain user content; keep only the status.
            raise RuntimeError(f"Discord HTTP {exc.code}") from None

    def send(self, text, nonce, image_url=None):
        with self.store.connect() as db:
            row = db.execute("SELECT value FROM metadata WHERE key='discord_dm_channel'").fetchone()
        channel = row[0] if row else None
        if not channel:
            channel = self.api("/users/@me/channels", {"recipient_id": OWNER})["id"]
            with self.store.connect() as db:
                db.execute("INSERT OR REPLACE INTO metadata VALUES ('discord_dm_channel',?)", (channel,))
        body = {"content": text[:1950], "nonce": nonce, "enforce_nonce": True, "allowed_mentions": {"parse": []}}
        if image_url:
            body["embeds"] = [{"image": {"url": image_url}}]
        response = self.api(f"/channels/{channel}/messages", body)
        return response["id"]


class Scheduler:
    def __init__(self, store, sender, whatsapp_sender=None):
        self.store, self.sender, self.whatsapp_sender = store, sender, whatsapp_sender

    def recover(self):
        # A crash after sending but before commit is not proof the message failed.
        with self.store.connect() as db:
            db.execute("UPDATE outbox SET status='ambiguous',last_error='Interrupted while sending; reconcile before retry' WHERE status='sending'")

    def tick(self, at=None):
        when = at or datetime.now(UTC)
        stamp = when.isoformat()
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM reminders WHERE status='pending' AND due_at<=?", (stamp,)).fetchall()
        for row in rows:
            end = quiet_end(when, row["allow_quiet"])
            content = f"Reminder [{row['id']}]: {row['text']}"
            if when - datetime.fromisoformat(row["due_at"]) > timedelta(minutes=10):
                content += "\nThis became due earlier; delivery was deferred or the service was offline."
            key = row["id"] + ":" + row["due_at"]
            with self.store.connect() as db:
                # Claim the reminder and outbox item together; snooze/cancel cannot race a partial enqueue.
                db.execute("BEGIN IMMEDIATE")
                current = db.execute("SELECT status,due_at FROM reminders WHERE id=?", (row["id"],)).fetchone()
                if current["status"] != "pending" or current["due_at"] != row["due_at"]:
                    continue
                import hashlib
                item_id = hashlib.sha256(key.encode()).hexdigest()[:24]
                db.execute("INSERT OR IGNORE INTO outbox(id,reminder_id,text,due_at,status,delivery_channel) VALUES (?,?,?,?,?,?)", (item_id, row["id"], content, end.isoformat(), "pending", row['delivery_channel']))
                db.execute("UPDATE reminders SET status='queued' WHERE id=?", (row["id"],))
        with self.store.connect() as db:
            items = db.execute("SELECT * FROM outbox WHERE status IN ('pending','retry') AND due_at<=? AND (next_attempt IS NULL OR next_attempt<=?) ORDER BY due_at LIMIT 10", (stamp, stamp)).fetchall()
        for item in items:
            with self.store.connect() as db:
                notification = db.execute("SELECT expires_at,image_url FROM notifications WHERE id=?", (item["id"],)).fetchone()
                if notification:
                    if datetime.fromisoformat(notification[0]) <= when:
                        db.execute("UPDATE outbox SET status='cancelled',last_error='Proactive alert expired before eligible delivery' WHERE id=? AND status IN ('pending','retry')", (item["id"],))
                        continue
            with self.store.connect() as db:
                claimed = db.execute("UPDATE outbox SET status='sending',attempts=attempts+1 WHERE id=? AND status IN ('pending','retry')", (item["id"],)).rowcount
            if not claimed:
                continue
            try:
                sender = self.sender
                if item['delivery_channel'] == 'whatsapp':
                    if self.whatsapp_sender is None:
                        raise RetryLater(60)
                    sender = self.whatsapp_sender
                if notification and notification["image_url"]:
                    message_id = sender.send(item["text"], item["id"], image_url=notification["image_url"])
                else:
                    message_id = sender.send(item["text"], item["id"])
            except (RetryLater, WhatsAppUnavailable) as exc:
                # Offline WhatsApp is a known pre-send failure, not an ambiguous send.
                status = 'retry' if item['delivery_channel'] == 'whatsapp' else ("failed" if item["attempts"] >= 4 else "retry")
                with self.store.connect() as db:
                    db.execute("UPDATE outbox SET status=?,next_attempt=?,last_error=? WHERE id=?", (status, (when + timedelta(seconds=exc.seconds)).isoformat(), 'WhatsApp unavailable before sending' if item['delivery_channel']=='whatsapp' else 'Discord rate limit', item["id"]))
                continue
            except Exception as exc:
                status = "failed" if str(exc).startswith("Discord HTTP 4") else "ambiguous"
                with self.store.connect() as db:
                    db.execute("UPDATE outbox SET status=?,last_error=? WHERE id=?", (status, str(exc)[:120], item["id"]))
                continue
            with self.store.connect() as db:
                db.execute("UPDATE outbox SET status='sent',message_id=?,sent_at=?,last_error=NULL WHERE id=?", (message_id, stamp, item["id"]))
                if item["reminder_id"]:
                    row = db.execute("SELECT * FROM reminders WHERE id=?", (item["reminder_id"],)).fetchone()
                    # A cancelled/snoozed reminder is not resurrected by a late send completion.
                    if row and row["status"] == "queued":
                        following = next_occurrence(row, when)
                        if following:
                            db.execute("UPDATE reminders SET due_at=?,status='pending' WHERE id=?", (following, row["id"]))
                        else:
                            db.execute("UPDATE reminders SET status='sent' WHERE id=?", (row["id"],))


def main():
    token_path = Path(os.environ["CREDENTIALS_DIRECTORY"]) / "discord_token"
    token = token_path.read_text(encoding="utf-8").strip()
    store = Store("/var/lib/personal-agent-data")
    scheduler = Scheduler(store, Discord(token, store), WhatsApp())
    scheduler.recover()
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print("Reminder scheduler ready; India-time quiet hours 23:00–09:00", flush=True)
    while not stopping:
        try:
            scheduler.tick()
        except (OSError, sqlite3.Error):
            print("Reminder scheduler state error; retrying next tick", file=sys.stderr, flush=True)
        for _ in range(15):
            if stopping:
                break
            time.sleep(1)


if __name__ == "__main__":
    main()
