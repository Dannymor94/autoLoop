"""AL-102 invariant tests against real SQLAlchemy + migrated SQLite/WAL."""

from __future__ import annotations

import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import inspect, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autoloop.database import create_database_engine, migrate, sqlite_url  # noqa: E402
from autoloop.dispatcher import DispatchRejected, Dispatcher  # noqa: E402


class DispatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "dispatcher.sqlite"
        self.url = sqlite_url(self.db_path)
        migrate(self.url)
        self.engine = create_database_engine(self.url)
        self.dispatcher = Dispatcher(self.engine)
        self.dispatcher.add_project(project_id="P", name="Pilot")
        self.dispatcher.add_plan(plan_id="PL", project_id="P", spec_hash="a" * 64)
        self.dispatcher.add_task(task_id="A", plan_id="PL", title="Test", acceptance_spec_hash="b" * 64)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temp.cleanup()

    def test_real_migration_and_wal(self) -> None:
        names = inspect(self.engine).get_table_names()
        self.assertGreaterEqual(len(names), 15)  # 14 business tables + alembic_version
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text("PRAGMA journal_mode")).scalar(), "wal")
            self.assertEqual(conn.execute(text("PRAGMA foreign_keys")).scalar(), 1)
            self.assertEqual(conn.execute(text("SELECT version_num FROM alembic_version")).scalar(), "0001")

    def test_claim_atomic_with_outbox_and_dispatcher_generated_request_id(self) -> None:
        first = self.dispatcher.claim_next(worker_id="w1", idempotency_key="tick-1")
        self.assertEqual(first["task_id"], "A")
        self.assertEqual(first["fencing_token"], 1)
        self.assertEqual(self.dispatcher.get_task("A")["state"], "RUNNING")
        outbox = self.dispatcher.pending_outbox(task_id="A")
        self.assertEqual(len(outbox), 1)
        self.assertEqual(outbox[0]["request_id"], first["request_id"])
        self.assertEqual(outbox[0]["payload"]["fencing_token"], first["fencing_token"])
        self.assertEqual(self.dispatcher.claim_next(worker_id="w1", idempotency_key="tick-1"), first)
        self.assertIsNone(self.dispatcher.claim_next(worker_id="w2", idempotency_key="tick-2"))
        self.assertEqual([e["event"] for e in self.dispatcher.events_for("A")], ["TASK_CREATED", "CLAIM_ATTEMPT"])

    def test_stop_pending_then_confirmed_and_resume(self) -> None:
        claim = self.dispatcher.claim_next(worker_id="w", idempotency_key="tick")
        stop = self.dispatcher.request_stop(task_id="A", idempotency_key="stop-1")
        self.assertEqual(stop["status"], "STOP_PENDING")
        self.assertEqual(self.dispatcher.get_task("A")["state"], "RUNNING")
        self.assertEqual(stop, self.dispatcher.request_stop(task_id="A", idempotency_key="stop-1"))
        self.assertEqual(stop["request_id"], self.dispatcher.request_stop(task_id="A", idempotency_key="stop-from-other-phone")["request_id"])
        with self.assertRaisesRegex(DispatchRejected, "INVALID_CHECKPOINT_HASH"):
            self.dispatcher.confirm_stop(request_id=stop["request_id"], task_id="A", attempt_id=claim["attempt_id"], fencing_token=1, checkpoint_hash="x")
        stopped = self.dispatcher.confirm_stop(request_id=stop["request_id"], task_id="A", attempt_id=claim["attempt_id"], fencing_token=1, checkpoint_hash="e" * 64)
        self.assertEqual((stopped["state"], stopped["reason"]), ("BLOCKED", "OWNER_STOP"))
        self.assertEqual(self.dispatcher.request_stop(task_id="A", idempotency_key="stop-1")["status"], "CONFIRMED")
        self.assertEqual(self.dispatcher.confirm_stop(request_id=stop["request_id"], task_id="A", attempt_id=claim["attempt_id"], fencing_token=1, checkpoint_hash="e" * 64), stopped)
        with self.assertRaisesRegex(DispatchRejected, "STOP_RECEIPT_CONFLICT"):
            self.dispatcher.confirm_stop(request_id=stop["request_id"], task_id="A", attempt_id=claim["attempt_id"], fencing_token=1, checkpoint_hash="d" * 64)
        resumed = self.dispatcher.resume_owner_stop(task_id="A", idempotency_key="resume-1")
        self.assertEqual((resumed["state"], resumed["reason"]), ("READY", None))
        self.assertEqual(resumed, self.dispatcher.resume_owner_stop(task_id="A", idempotency_key="resume-1"))
        next_claim = self.dispatcher.claim_next(worker_id="w2", idempotency_key="tick-2")
        self.assertEqual(next_claim["fencing_token"], 2)
        self.assertNotEqual(next_claim["attempt_id"], claim["attempt_id"])

    def test_runner_completion_only_reaches_verifying(self) -> None:
        claim = self.dispatcher.claim_next(worker_id="w", idempotency_key="tick")
        report = self.dispatcher.runner_completed(task_id="A", attempt_id=claim["attempt_id"], fencing_token=1, artifact_hash="f" * 64)
        self.assertEqual(report["state"], "VERIFYING")
        self.assertEqual(self.dispatcher.runner_completed(task_id="A", attempt_id=claim["attempt_id"], fencing_token=1, artifact_hash="f" * 64), report)
        self.assertNotEqual(report["state"], "DONE")

    def test_outbox_delivery_requires_exact_payload_hash(self) -> None:
        self.dispatcher.claim_next(worker_id="w", idempotency_key="tick")
        message = self.dispatcher.pending_outbox()[0]
        with self.assertRaisesRegex(DispatchRejected, "OUTBOX_HASH_MISMATCH"):
            self.dispatcher.acknowledge_delivery(request_id=message["request_id"], payload_digest="bad")
        self.dispatcher.acknowledge_delivery(request_id=message["request_id"], payload_digest=message["payload_hash"])
        self.assertEqual(self.dispatcher.pending_outbox(), [])

    def test_orphan_requires_quiescence_and_rejects_stale_fence(self) -> None:
        claim = self.dispatcher.claim_next(worker_id="dead-worker", idempotency_key="tick")
        with self.assertRaisesRegex(DispatchRejected, "RUNNER_QUIESCENCE_NOT_CONFIRMED"):
            self.dispatcher.mark_orphaned(task_id="A", expected_fence=1)
        blocked = self.dispatcher.mark_orphaned(task_id="A", expected_fence=1, runner_quiescence_confirmed=True)
        self.assertEqual((blocked["state"], blocked["reason"]), ("BLOCKED", "RUNNER_OUTCOME_UNKNOWN"))
        with self.assertRaisesRegex(DispatchRejected, "STALE_FENCING_TOKEN"):
            self.dispatcher.heartbeat(task_id="A", attempt_id=claim["attempt_id"], fencing_token=1)
        self.assertIsNone(self.dispatcher.claim_next(worker_id="w2", idempotency_key="new-tick"))

    def test_dependency_stays_blocked(self) -> None:
        self.dispatcher.add_task(task_id="B", plan_id="PL", title="Dependent", acceptance_spec_hash="c" * 64, dependency_ids=["A"])
        self.assertEqual(self.dispatcher.get_task("B")["state"], "BLOCKED")
        claim = self.dispatcher.claim_next(worker_id="w", idempotency_key="tick")
        self.assertEqual(claim["task_id"], "A")
        self.assertIsNone(self.dispatcher.claim_next(worker_id="other", idempotency_key="tick2"))

    def test_idempotency_key_not_reusable_for_other_operation(self) -> None:
        self.dispatcher.claim_next(worker_id="w", idempotency_key="same")
        with self.assertRaisesRegex(DispatchRejected, "IDEMPOTENCY_CONFLICT"):
            self.dispatcher.request_stop(task_id="A", idempotency_key="same")

    def test_killed_dispatcher_preserves_claim_and_outbox(self) -> None:
        source = """
import os,signal,sys
sys.path.insert(0, sys.argv[2])
from autoloop.database import create_database_engine, sqlite_url
from autoloop.dispatcher import Dispatcher
from pathlib import Path
d = Dispatcher(create_database_engine(sqlite_url(Path(sys.argv[1]))))
d.claim_next(worker_id='child', idempotency_key='child-tick')
os.kill(os.getpid(),signal.SIGKILL)
"""
        result = subprocess.run([sys.executable, "-c", source, str(self.db_path), str(ROOT / "src")], capture_output=True, check=False)
        self.assertEqual(result.returncode, -signal.SIGKILL)
        self.assertEqual(self.dispatcher.get_task("A")["state"], "RUNNING")
        self.assertEqual(len(self.dispatcher.pending_outbox()), 1)
        self.assertIsNone(self.dispatcher.claim_next(worker_id="another", idempotency_key="new"))


if __name__ == "__main__":
    unittest.main()
