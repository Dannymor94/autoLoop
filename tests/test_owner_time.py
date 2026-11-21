from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autoloop.owner_time import OwnerTimeLedger, OwnerTimeRejected  # noqa: E402


class OwnerTimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "ledger.jsonl"
        self.ledger = OwnerTimeLedger(self.path)
        self.start = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_timers_and_idempotency(self):
        first = self.ledger.record(task_id="AL-1", action="START", idempotency_key="a", now=self.start)
        self.assertEqual(self.ledger.record(task_id="AL-1", action="START", idempotency_key="a", now=self.start + timedelta(minutes=5)), first)
        self.assertIsNone(self.ledger.summary("AL-1")["active_seconds"])
        self.ledger.record(task_id="AL-1", action="STOP", idempotency_key="b", now=self.start + timedelta(minutes=7))
        self.assertEqual(self.ledger.summary("AL-1")["active_seconds"], 420)
        self.assertEqual(len(self.path.read_text().splitlines()), 2)

    def test_no_fake_minutes_if_stop_missing(self):
        self.ledger.record(task_id="AL-1", action="START", idempotency_key="a", now=self.start)
        self.assertTrue(self.ledger.summary("AL-1")["timer_open"])
        self.assertIsNone(self.ledger.summary("AL-1")["active_seconds"])

    def test_duplicate_and_unpaired_stop_are_rejected(self):
        with self.assertRaisesRegex(OwnerTimeRejected, "INVALID_OWNER_TIME_TRANSITION"):
            self.ledger.record(task_id="AL-1", action="STOP", idempotency_key="z", now=self.start)
        self.ledger.record(task_id="AL-1", action="START", idempotency_key="a", now=self.start)
        with self.assertRaisesRegex(OwnerTimeRejected, "INVALID_OWNER_TIME_TRANSITION"):
            self.ledger.record(task_id="AL-1", action="START", idempotency_key="b", now=self.start)
        with self.assertRaisesRegex(OwnerTimeRejected, "IDEMPOTENCY_CONFLICT"):
            self.ledger.record(task_id="AL-2", action="STOP", idempotency_key="a", now=self.start)

    def test_corrupted_or_reverse_clock_never_reports_savings(self):
        self.ledger.record(task_id="AL-1", action="START", idempotency_key="a", now=self.start)
        self.ledger.record(task_id="AL-1", action="STOP", idempotency_key="b", now=self.start - timedelta(minutes=1))
        with self.assertRaisesRegex(OwnerTimeRejected, "NONMONOTONIC_OWNER_TIME"):
            self.ledger.summary("AL-1")
        with self.path.open("ab") as handle:
            handle.write(b'{"truncated":true')
        with self.assertRaisesRegex(OwnerTimeRejected, "INCOMPLETE_OWNER_TIME_EVENT"):
            self.ledger.summary("AL-1")

    def test_cli_time_command_needs_no_database(self):
        cli = [sys.executable, "-m", "autoloop", "time"]
        env = dict(__import__("os").environ, PYTHONPATH=str(ROOT / "src"))
        self.assertEqual(subprocess.run(cli + ["start", "AL-2", "--ledger", str(self.path), "--key", "one"], env=env, capture_output=True).returncode, 0)
        out = subprocess.run(cli + ["summary", "AL-2", "--ledger", str(self.path)], env=env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0)
        self.assertEqual(json.loads(out.stdout)["active_seconds"], None)


if __name__ == "__main__":
    unittest.main()
