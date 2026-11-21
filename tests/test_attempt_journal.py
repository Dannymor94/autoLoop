from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autoloop.attempt_journal import (  # noqa: E402
    AttemptJournalError,
    recover_attempt_log,
    seal_attempt_log,
)


class AttemptJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.log = Path(self.temp.name) / "a.jsonl"
        self.receipt = Path(self.temp.name) / "a.receipt.json"

    def tearDown(self):
        self.temp.cleanup()

    def write_events(self, *events):
        self.log.write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")

    def test_durable_completion_survives_database_crash(self):
        self.write_events({"type": "thread.started", "thread_id": "t"}, {"type": "turn.completed", "usage": {"input_tokens": 8}})
        saved = seal_attempt_log(log_path=self.log, receipt_path=self.receipt, request_id="req", provider="codex", exit_code=0)
        self.assertEqual(recover_attempt_log(log_path=self.log, receipt_path=self.receipt), saved)
        self.assertEqual(seal_attempt_log(log_path=self.log, receipt_path=self.receipt, request_id="req", provider="codex", exit_code=0), saved)

    def test_no_receipt_is_unknown_even_with_final_event(self):
        self.write_events({"type": "turn.completed"})
        self.assertIsNone(recover_attempt_log(log_path=self.log, receipt_path=self.receipt))

    def test_truncated_log_fails_closed(self):
        self.log.write_bytes(b'{"type":"turn.completed"}')
        with self.assertRaisesRegex(AttemptJournalError, "INCOMPLETE_JSONL_LINE"):
            seal_attempt_log(log_path=self.log, receipt_path=self.receipt, request_id="req", provider="codex", exit_code=0)
        self.assertIsNone(recover_attempt_log(log_path=self.log, receipt_path=self.receipt))

    def test_post_receipt_tampering_is_unknown(self):
        self.write_events({"type": "turn.completed"})
        seal_attempt_log(log_path=self.log, receipt_path=self.receipt, request_id="req", provider="codex", exit_code=0)
        self.write_events({"type": "turn.failed"})
        self.assertIsNone(recover_attempt_log(log_path=self.log, receipt_path=self.receipt))

    def test_failed_process_still_has_valid_receipt_not_pass(self):
        self.write_events({"type": "turn.failed"})
        data = seal_attempt_log(log_path=self.log, receipt_path=self.receipt, request_id="req", provider="codex", exit_code=1)
        self.assertEqual(data["exit_code"], 1)
        self.assertEqual(data["terminal_event"], "turn.failed")

    def test_symlink_receipt_is_rejected(self):
        self.write_events({"type": "turn.completed"})
        external = Path(self.temp.name) / "other"
        external.write_text("untouched", encoding="utf-8")
        self.receipt.symlink_to(external)
        with self.assertRaisesRegex(AttemptJournalError, "UNTRUSTED_JOURNAL_SYMLINK"):
            seal_attempt_log(log_path=self.log, receipt_path=self.receipt, request_id="req", provider="codex", exit_code=0)
        self.assertEqual(external.read_text(encoding="utf-8"), "untouched")


if __name__ == "__main__":
    unittest.main()
