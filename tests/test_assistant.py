from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from assistant_store import Store
from assistant_broker import Backend
from reminder_scheduler import Scheduler, RetryLater, quiet_end, next_occurrence

UTC = timezone.utc


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def fact(self, text, **kwargs):
        return self.store.remember("health/nutrition", text, "Fictional unit-test user statement", confirmed=True,
                                   valid_from="2026-01-01T00:00:00Z", **kwargs)

    def test_food_recall_includes_health_without_keyword_overlap(self):
        fact = self.fact("The test user reports a clinician-set restriction", importance="critical")
        recalled = self.store.recall("I want a protein shake", at="2026-02-01T12:00:00Z")
        self.assertIn(fact["id"], [r["id"] for r in recalled["matches"]])

    def test_expired_restriction_not_treated_as_current(self):
        self.fact("Temporary test restriction", valid_until="2026-02-01T00:00:00Z")
        self.assertFalse(self.store.recall("protein shake", at="2026-02-02T00:00:00Z")["matches"])

    def test_correction_preserves_historical_truth(self):
        self.fact("Old test rule", fact_key="test-rule")
        self.store.remember("health/nutrition", "Corrected rule", "Test correction", confirmed=True,
                            fact_key="test-rule", valid_from="2026-03-01T00:00:00Z")
        old = self.store.recall("protein shake", at="2026-02-01T12:00:00Z")
        new = self.store.recall("protein shake", at="2026-04-01T12:00:00Z")
        self.assertEqual([r["text"] for r in old["matches"]], ["Old test rule"])
        self.assertEqual([r["text"] for r in new["matches"]], ["Corrected rule"])

    def test_temporary_exception_restores_routine_after_end(self):
        self.store.remember("routine", "Normal test routine", "Test user", confirmed=True, fact_key="routine",
                            valid_from="2026-01-01T00:00:00Z")
        self.store.remember("routine", "One-day exception", "Test user", confirmed=True, fact_key="routine",
                            valid_from="2026-02-01T00:00:00Z", valid_until="2026-02-02T00:00:00Z")
        during = self.store.recall("routine", at="2026-02-01T10:00:00Z")["matches"]
        after = self.store.recall("routine", at="2026-02-03T10:00:00Z")["matches"]
        self.assertEqual([r["text"] for r in during], ["One-day exception"])
        self.assertEqual([r["text"] for r in after], ["Normal test routine"])

    def test_inference_cannot_be_confirmed_or_replace_confirmed_fact(self):
        self.fact("Real test statement", fact_key="test")
        with self.assertRaises(ValueError):
            self.store.remember("health", "Guess", "Webpage", source_type="inference", confirmed=True)
        self.store.remember("health", "Candidate guess", "Inference", source_type="inference", fact_key="test")
        recalled = self.store.recall("protein", at="2026-12-01T00:00:00Z")["matches"]
        self.assertTrue(any(r["text"] == "Real test statement" and r["status"] == "confirmed" for r in recalled))

    def test_review_date_is_visible(self):
        self.fact("Stale test rule", review_after="2026-02-01")
        match = self.store.recall("protein", at="2026-03-01T00:00:00Z")["matches"][0]
        self.assertTrue(match["needs_review"])

    def test_overnight_routine_uses_previous_weekday(self):
        self.store.remember("routine", "Friday-night test routine", "Test statement", confirmed=True,
                            valid_from="2026-01-01T00:00:00Z", recurrence={"weekdays": [4], "start_local": "23:00", "end_local": "02:00"})
        match = self.store.recall("routine", at="2026-02-06T19:30:00Z")["matches"][0]
        self.assertTrue(match["routine_applies_at_query_time"])

    def test_forget_purges_live_text_and_export(self):
        fact = self.fact("Fictional sensitive test fact")
        self.store.forget(fact["id"], "Test owner deletion")
        self.assertFalse(self.store.recall("protein", at="2026-12-01T00:00:00Z")["matches"])
        export = (Path(self.temp.name) / "exports/memory.json").read_text()
        self.assertNotIn("Fictional sensitive test fact", export)


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.sent = []
        outer = self
        class Sender:
            def send(self, text, nonce):
                outer.sent.append((text, nonce))
                return "message-id"
        self.scheduler = Scheduler(self.store, Sender())
        self.when = datetime(2026, 11, 9, 5, 0, tzinfo=UTC)

    def tearDown(self):
        self.temp.cleanup()

    def reminder(self, **kwargs):
        return self.store.add_reminder("Test reminder", self.when.isoformat(), "Test user request", "test-key", **kwargs)

    def test_model_free_send_deduplicates_repeated_ticks_and_requests(self):
        first = self.reminder()
        self.assertEqual(first["id"], self.reminder()["id"])
        self.scheduler.tick(self.when)
        self.scheduler.tick(self.when + timedelta(seconds=30))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.store.reminders()[0]["status"], "sent")

    def test_ambiguous_transport_failure_is_not_blindly_retried(self):
        self.reminder()
        def fail(*args):
            raise TimeoutError("Unknown send outcome")
        self.scheduler.sender.send = fail
        self.scheduler.tick(self.when)
        self.scheduler.tick(self.when + timedelta(minutes=1))
        with self.store.connect() as db:
            item = dict(db.execute("SELECT * FROM outbox").fetchone())
        self.assertEqual(item["status"], "ambiguous")
        self.assertEqual(item["attempts"], 1)

    def test_rate_limit_is_retried(self):
        self.reminder()
        def limited(*args):
            raise RetryLater(60)
        original = self.scheduler.sender.send
        self.scheduler.sender.send = limited
        self.scheduler.tick(self.when)
        self.scheduler.sender.send = original
        self.scheduler.tick(self.when + timedelta(seconds=30))
        self.assertEqual(len(self.sent), 0)
        self.scheduler.tick(self.when + timedelta(seconds=61))
        self.assertEqual(len(self.sent), 1)

    def test_cancel_deferred_reminder_prevents_delivery(self):
        self.when = datetime(2026, 11, 9, 0, 0, tzinfo=UTC)  # 05:30 IST, quiet
        reminder = self.reminder()
        self.scheduler.tick(self.when)
        self.store.change_reminder(reminder["id"], "cancel")
        self.scheduler.tick(self.when + timedelta(hours=5))
        self.assertEqual(self.sent, [])

    def test_recurring_reminder_advances_past_downtime_once(self):
        self.reminder(repeat="daily")
        self.scheduler.tick(self.when + timedelta(days=3))
        row = self.store.reminders()[0]
        self.assertEqual(len(self.sent), 1)
        self.assertGreater(datetime.fromisoformat(row["due_at"]), self.when + timedelta(days=3))

    def test_naive_time_rejected(self):
        with self.assertRaises(ValueError):
            self.store.add_reminder("Test", "2026-11-09T10:00:00", "Test", "naive")

    def test_crash_recovery_marks_unconfirmed_send_ambiguous(self):
        self.store.enqueue("Test", self.when.isoformat(), "interrupted")
        with self.store.connect() as db:
            db.execute("UPDATE outbox SET status='sending'")
        self.scheduler.recover()
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM outbox").fetchone()[0], "ambiguous")


class ProtocolTests(unittest.TestCase):
    def test_mcp_handshake_and_discovery_do_not_require_credentials(self):
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / "app/assistant_mcp.py")]
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]
        run = subprocess.run(command, input="".join(json.dumps(m) + "\n" for m in messages), text=True, capture_output=True, check=True)
        results = [json.loads(line) for line in run.stdout.splitlines()]
        self.assertIn("memory_context", [t["name"] for t in results[1]["result"]["tools"]])


if __name__ == "__main__":
    unittest.main()
