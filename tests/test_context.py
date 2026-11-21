from __future__ import annotations

import sys
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autoloop.context import ContextTracker  # noqa: E402
from autoloop.database import create_database_engine, migrate, sqlite_url  # noqa: E402
from autoloop.dispatcher import DispatchRejected, Dispatcher  # noqa: E402
from autoloop.git_snapshot import OwnerInterventionDetected  # noqa: E402


class ContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        url = sqlite_url(Path(self.temp.name) / "context.sqlite")
        migrate(url)
        self.engine = create_database_engine(url)
        self.dispatcher = Dispatcher(self.engine)
        self.dispatcher.add_project(project_id="P", name="Pilot")
        self.dispatcher.add_plan(plan_id="PL", project_id="P", spec_hash="a" * 64)
        self.dispatcher.add_task(task_id="A", plan_id="PL", title="Task", acceptance_spec_hash="b" * 64)
        self.claim = self.dispatcher.claim_next(worker_id="worker", idempotency_key="tick")
        self.tracker = ContextTracker(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temp.cleanup()

    def test_unknown_quota_and_usage_not_fabricated(self) -> None:
        result = self.tracker.observed_usage(self.claim["attempt_id"])
        self.assertIsNone(result["subscription_remaining"])
        self.assertIsNone(result["context_used_percent"])
        self.assertEqual(self.tracker.context_guidance(attempt_id=self.claim["attempt_id"]), "UNKNOWN")

    def test_structured_token_samples_are_idempotent(self) -> None:
        values = dict(attempt_id=self.claim["attempt_id"], event_id="turn-completed-1", input_tokens=123, output_tokens=40, context_used_percent=65)
        self.assertFalse(self.tracker.record_usage(**values)["duplicate"])
        self.assertTrue(self.tracker.record_usage(**values)["duplicate"])
        observed = self.tracker.observed_usage(self.claim["attempt_id"])
        self.assertEqual((observed["input_tokens"], observed["output_tokens"], observed["samples"]), (123, 40, 1))
        self.assertIsNone(observed["subscription_remaining"])
        self.assertEqual(self.tracker.context_guidance(attempt_id=self.claim["attempt_id"]), "SUGGEST_CHECKPOINT")
        self.tracker.record_usage(attempt_id=self.claim["attempt_id"], event_id="turn-completed-2", input_tokens=300, output_tokens=120, context_used_percent=80)
        self.assertEqual(self.tracker.context_guidance(attempt_id=self.claim["attempt_id"]), "PREPARE_NEW_SESSION")

    def test_usage_duplicate_with_different_data_rejected(self) -> None:
        self.tracker.record_usage(attempt_id=self.claim["attempt_id"], event_id="x", input_tokens=1, output_tokens=1)
        with self.assertRaisesRegex(DispatchRejected, "USAGE_EVENT_CONFLICT"):
            self.tracker.record_usage(attempt_id=self.claim["attempt_id"], event_id="x", input_tokens=2, output_tokens=1)

    def test_negative_token_metrics_fail(self) -> None:
        with self.assertRaisesRegex(DispatchRejected, "INVALID_TOKEN_COUNT"):
            self.tracker.record_usage(attempt_id=self.claim["attempt_id"], event_id="x", input_tokens=-1, output_tokens=0)
        with self.assertRaisesRegex(DispatchRejected, "INVALID_CONTEXT_PERCENT"):
            self.tracker.record_usage(attempt_id=self.claim["attempt_id"], event_id="x", input_tokens=0, output_tokens=0, context_used_percent=101)

    def test_checkpoint_hash_binds_sha_and_is_idempotent(self) -> None:
        repo = Path(self.temp.name) / "git-worktree"
        repo.mkdir()
        def git(*command: str) -> str:
            return subprocess.run(["git", "-C", str(repo), *command], check=True, text=True, capture_output=True).stdout.strip()
        git("init", "-q")
        git("config", "user.email", "fixture@example.invalid")
        git("config", "user.name", "Fixture")
        (repo / "file.txt").write_text("baseline", encoding="utf-8")
        git("add", "file.txt")
        git("commit", "-qm", "baseline")
        args = dict(task_id="A", attempt_id=self.claim["attempt_id"], checkpoint_id="checkpoint-001", head_sha=git("rev-parse", "HEAD"), base_sha="b" * 40, worktree=repo, summary="Implemented function", next_safe_action="Run QA", open_questions=["review SHA"])
        first = self.tracker.checkpoint(**args)
        self.assertFalse(first["duplicate"])
        self.assertTrue(self.tracker.checkpoint(**args)["duplicate"])
        self.tracker.require_checkpoint_unchanged(task_id="A", checkpoint_id="checkpoint-001", worktree=repo)
        (repo / "file.txt").write_text("changed by owner", encoding="utf-8")
        with self.assertRaises(OwnerInterventionDetected):
            self.tracker.require_checkpoint_unchanged(task_id="A", checkpoint_id="checkpoint-001", worktree=repo)
        with self.assertRaisesRegex(DispatchRejected, "CHECKPOINT_ID_CONFLICT"):
            self.tracker.checkpoint(**dict(args, base_sha="f" * 40))

    def test_clear_not_faked(self) -> None:
        self.assertEqual(self.tracker.clear_session(task_id="A", attempt_id=self.claim["attempt_id"]), "UNSUPPORTED")


if __name__ == "__main__":
    unittest.main()
