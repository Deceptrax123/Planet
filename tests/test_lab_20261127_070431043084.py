import sqlite3
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from reminder_scheduler import RetryLater, Scheduler


class MemoryStore:
    def __init__(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE reminders (
                id TEXT PRIMARY KEY, text TEXT, due_at TEXT, status TEXT,
                allow_quiet INTEGER, delivery_channel TEXT, repeat TEXT,
                timezone TEXT
            );
            CREATE TABLE outbox (
                id TEXT PRIMARY KEY, reminder_id TEXT, text TEXT, due_at TEXT,
                status TEXT, delivery_channel TEXT, next_attempt TEXT,
                attempts INTEGER DEFAULT 0, last_error TEXT, message_id TEXT,
                sent_at TEXT
            );
            CREATE TABLE notifications (id TEXT PRIMARY KEY, expires_at TEXT, image_url TEXT);
        ''')

    def connect(self):
        return self.db


class RetryOnceSender:
    def __init__(self):
        self.calls = []

    def send(self, text, nonce):
        self.calls.append((text, nonce))
        if len(self.calls) == 1:
            raise RetryLater(120)
        return 'message-id'


class ReminderRetryQuietHoursTest(unittest.TestCase):
    def test_retry_respects_quiet_hours_and_backoff(self):
        # 22:59 in Asia/Kolkata; the retry becomes eligible at 23:01.
        start = datetime(2026, 1, 1, 17, 29, tzinfo=timezone.utc)
        for allow_quiet in (False, True):
            with self.subTest(allow_quiet=allow_quiet):
                store = MemoryStore()
                self.addCleanup(store.db.close)
                with store.connect() as db:
                    db.execute(
                        'INSERT INTO reminders VALUES (?,?,?,?,?,?,?,?)',
                        ('r1', 'Take a break', start.isoformat(), 'pending',
                         allow_quiet, 'discord', 'none', 'Asia/Kolkata'),
                    )
                sender = RetryOnceSender()
                scheduler = Scheduler(store, sender)
                scheduler.tick(start)
                self.assertEqual(len(sender.calls), 1)
                item = store.db.execute('SELECT * FROM outbox').fetchone()
                self.assertEqual(item['status'], 'retry')
                self.assertEqual(item['next_attempt'], (start + timedelta(seconds=120)).isoformat())

                scheduler.tick(start + timedelta(seconds=60))
                self.assertEqual(len(sender.calls), 1, 'backoff must gate retries')
                scheduler.tick(start + timedelta(seconds=120))
                if allow_quiet:
                    self.assertEqual(len(sender.calls), 2)
                    self.assertEqual(store.db.execute('SELECT status FROM outbox').fetchone()[0], 'sent')
                else:
                    self.assertEqual(len(sender.calls), 1, 'retry must wait for quiet hours to end')
                    item = store.db.execute('SELECT * FROM outbox').fetchone()
                    morning = datetime(2026, 1, 2, 3, 30, tzinfo=timezone.utc)
                    self.assertEqual(item['due_at'], morning.isoformat())
                    self.assertEqual(item['next_attempt'], (start + timedelta(seconds=120)).isoformat())
                    scheduler.tick(morning)
                    self.assertEqual(len(sender.calls), 2)
                    self.assertEqual(store.db.execute('SELECT status FROM outbox').fetchone()[0], 'sent')


if __name__ == '__main__':
    unittest.main()
