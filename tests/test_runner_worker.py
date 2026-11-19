from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autoloop.database import create_database_engine, migrate, sqlite_url  # noqa: E402
from autoloop.dispatcher import DispatchRejected, Dispatcher  # noqa: E402
from autoloop.models import Outbox, RunnerSession  # noqa: E402
from autoloop.runner import MockAdapter  # noqa: E402
from autoloop.runner_worker import RunnerWorker  # noqa: E402


class RunnerWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        url = sqlite_url(base / "worker.sqlite")
        migrate(url)
        self.engine = create_database_engine(url)
        self.dispatcher = Dispatcher(self.engine)
        self.dispatcher.add_project(project_id="P", name="Pilot")
        self.dispatcher.add_plan(plan_id="PL", project_id="P", spec_hash="a" * 64)
        self.dispatcher.add_task(task_id="A", plan_id="PL", title="Bounded instructions", acceptance_spec_hash="b" * 64)
        self.claim = self.dispatcher.claim_next(worker_id="mock", idempotency_key="tick")
        self.worktree = base / "worktree"
        self.worktree.mkdir()
        subprocess.run(["git", "init", "-q", str(self.worktree)], check=True, capture_output=True)
        self.worker = RunnerWorker(self.engine)
        self.adapter = MockAdapter(allowed_worktree_root=base)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temp.cleanup()

    def test_start_delivery_is_idempotent_and_not_a_task_done(self) -> None:
        first = self.worker.deliver_start(request_id=self.claim["request_id"], adapter=self.adapter, worktree=self.worktree)
        self.assertEqual(first["status"], "COMPLETED")
        self.assertFalse(first["duplicate_delivery"])
        self.assertTrue(self.worker.deliver_start(request_id=self.claim["request_id"], adapter=self.adapter, worktree=self.worktree)["duplicate_delivery"])
        self.assertEqual(self.dispatcher.get_task("A")["state"], "RUNNING")
        self.assertEqual(self.dispatcher.pending_outbox(), [])

    def test_crash_after_reservation_blocks_automatic_retry(self) -> None:
        with Session(self.engine) as session:
            session.add(RunnerSession(id=self.claim["request_id"], attempt_id=self.claim["attempt_id"], status="STARTING"))
            session.commit()
        with self.assertRaisesRegex(DispatchRejected, "DELIVERY_OUTCOME_UNKNOWN"):
            self.worker.deliver_start(request_id=self.claim["request_id"], adapter=self.adapter, worktree=self.worktree)
        self.assertEqual(len(self.dispatcher.pending_outbox()), 1)

    def test_tampered_outbox_payload_cannot_launch(self) -> None:
        with Session(self.engine) as session:
            msg = session.scalar(select(Outbox).where(Outbox.request_id == self.claim["request_id"]))
            msg.payload = {**msg.payload, "instructions": "TAMPERED"}
            session.commit()
        with self.assertRaisesRegex(DispatchRejected, "PAYLOAD_HASH_MISMATCH"):
            self.worker.deliver_start(request_id=self.claim["request_id"], adapter=self.adapter, worktree=self.worktree)
        with Session(self.engine) as session:
            self.assertIsNone(session.get(RunnerSession, self.claim["request_id"]))


if __name__ == "__main__":
    unittest.main()
