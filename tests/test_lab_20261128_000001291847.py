import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from reminder_scheduler import RetryLater, Scheduler

UTC = timezone.utc
EVENING = datetime(2026, 1, 5, 17, 29, tzinfo=UTC)  # 22:59 India
NIGHT = EVENING + timedelta(minutes=2)
MORNING = datetime(2026, 1, 6, 3, 30, tzinfo=UTC)  # 09:00 India


class SQLiteStore:
    def __init__(self, path):
        self.path = path

    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db


class Sender:
    def __init__(self, retry_first=False):
        self.retry_first = retry_first
        self.calls = []

    def send(self, text, nonce, image_url=None):
        self.calls.append((text, nonce, image_url))
        if self.retry_first and len(self.calls) == 1:
            raise RetryLater(120)
        return 'message-id'


class QuietHoursTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SQLiteStore(str(Path(self.temp.name) / 'scheduler.sqlite'))
        with self.store.connect() as db:
            db.executescript('''
                CREATE TABLE reminders (
                    id TEXT PRIMARY KEY, text TEXT, due_at TEXT,
                    status TEXT, allow_quiet INTEGER,
                    delivery_channel TEXT, repeat TEXT, timezone TEXT
                );
                CREATE TABLE outbox (
                    id TEXT PRIMARY KEY, reminder_id TEXT, text TEXT,
                    due_at TEXT, status TEXT, delivery_channel TEXT,
                    next_attempt TEXT, attempts INTEGER DEFAULT 0,
                    last_error TEXT, message_id TEXT, sent_at TEXT
                );
                CREATE TABLE notifications (
                    id TEXT PRIMARY KEY, expires_at TEXT, image_url TEXT
                );
            ''')

    def reminder(self, allow_quiet=False):
        with self.store.connect() as db:
            db.execute('INSERT INTO reminders VALUES (?,?,?,?,?,?,?,?)',
                       ('reminder', 'Check appointment', EVENING.isoformat(),
                        'pending', int(allow_quiet), 'discord', 'none',
                        'Asia/Kolkata'))

    def item(self):
        with self.store.connect() as db:
            return dict(db.execute('SELECT * FROM outbox').fetchone())

    def test_retry_is_deferred_until_morning(self):
        self.reminder()
        sender = Sender(retry_first=True)
        scheduler = Scheduler(self.store, sender)
        scheduler.tick(EVENING)
        before = self.item()
        self.assertEqual(before['status'], 'retry')
        self.assertEqual(before['next_attempt'], NIGHT.isoformat())
        scheduler.tick(NIGHT)
        deferred = self.item()
        self.assertEqual(len(sender.calls), 1)
        self.assertEqual(deferred['due_at'], MORNING.isoformat())
        for field in ('status', 'attempts', 'next_attempt', 'last_error'):
            self.assertEqual(deferred[field], before[field])
        scheduler.tick(MORNING - timedelta(seconds=1))
        self.assertEqual(len(sender.calls), 1)
        scheduler.tick(MORNING)
        self.assertEqual(len(sender.calls), 2)
        self.assertEqual(self.item()['status'], 'sent')

    def test_allow_quiet_permits_night_retry(self):
        self.reminder(allow_quiet=True)
        sender = Sender(retry_first=True)
        scheduler = Scheduler(self.store, sender)
        scheduler.tick(EVENING)
        scheduler.tick(NIGHT)
        self.assertEqual(len(sender.calls), 2)
        self.assertEqual(self.item()['status'], 'sent')

    def test_delayed_pending_delivery_preserves_later_retry_deadline(self):
        self.reminder()
        later = MORNING + timedelta(minutes=30)
        with self.store.connect() as db:
            db.execute("UPDATE reminders SET status='queued'")
            db.execute('''INSERT INTO outbox
                (id, reminder_id, text, due_at, status, delivery_channel)
                VALUES (?,?,?,?,?,?)''',
                ('delayed', 'reminder', 'Check appointment',
                 EVENING.isoformat(), 'pending', 'discord'))
        sender = Sender()
        scheduler = Scheduler(self.store, sender)
        scheduler.tick(NIGHT)
        self.assertEqual(sender.calls, [])
        self.assertEqual(self.item()['due_at'], MORNING.isoformat())
        with self.store.connect() as db:
            db.execute('UPDATE outbox SET next_attempt=?', (later.isoformat(),))
        scheduler.tick(MORNING)
        self.assertEqual(sender.calls, [])
        self.assertEqual(self.item()['next_attempt'], later.isoformat())
        scheduler.tick(later)
        self.assertEqual(len(sender.calls), 1)
        self.assertEqual(self.item()['status'], 'sent')

    def test_notifications_keep_night_delivery_and_expiration_behavior(self):
        with self.store.connect() as db:
            for item_id, expires in [('active', MORNING), ('expired', NIGHT)]:
                db.execute('''INSERT INTO outbox
                    (id, text, due_at, status, delivery_channel)
                    VALUES (?,?,?,?,?)''',
                    (item_id, item_id, EVENING.isoformat(), 'pending', 'discord'))
                db.execute('INSERT INTO notifications VALUES (?,?,?)',
                           (item_id, expires.isoformat(), 'https://example.invalid/image.png'))
        sender = Sender()
        Scheduler(self.store, sender).tick(NIGHT)
        self.assertEqual(sender.calls, [('active', 'active', 'https://example.invalid/image.png')])
        with self.store.connect() as db:
            statuses = dict(db.execute('SELECT id,status FROM outbox').fetchall())
        self.assertEqual(statuses, {'active': 'sent', 'expired': 'cancelled'})


if __name__ == '__main__':
    unittest.main()
