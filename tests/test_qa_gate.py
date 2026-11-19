"""AL-104 negative SHA and independent QA gates with trusted fake Git refs."""

from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autoloop.database import create_database_engine, migrate, sqlite_url  # noqa: E402
from autoloop.dispatcher import DispatchRejected, Dispatcher  # noqa: E402
from autoloop.evidence import evidence_key  # noqa: E402
from autoloop.models import Evidence, QAVerdict  # noqa: E402
from autoloop.qa import CIProof, Gatekeeper, QAProof  # noqa: E402


class FakeRefs:
    head = "a" * 40
    base = "b" * 40

    def current_head(self, _task_id: str) -> str:
        return self.head

    def current_base(self, _task_id: str) -> str:
        return self.base


class QAGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        url = sqlite_url(Path(self.temp.name) / "qa.sqlite")
        migrate(url)
        self.engine = create_database_engine(url)
        self.dispatcher = Dispatcher(self.engine)
        self.dispatcher.add_project(project_id="P", name="Pilot")
        self.dispatcher.add_plan(plan_id="PL", project_id="P", spec_hash="f" * 64)
        self.dispatcher.add_task(task_id="A", plan_id="PL", title="QA Task", acceptance_spec_hash="e" * 64)
        self.refs = FakeRefs()
        self.gate = Gatekeeper(self.engine, refs=self.refs)
        self.claim = self.dispatcher.claim_next(worker_id="developer", idempotency_key="start")
        self.dispatcher.runner_completed(task_id="A", attempt_id=self.claim["attempt_id"], fencing_token=1, artifact_hash="d" * 64)
        self.ci = CIProof(run_id="run-123", head_sha="a" * 40, base_sha="b" * 40, tested_tree_sha="c" * 40, workflow_ref="refs/pull/1/merge", conclusion="success", check_commands=("python -m unittest",), lockfile_sha256_by_path={"requirements-dev.txt": "1" * 64}, ci_workflow_sha256_by_path={".github/workflows/contracts-check.yml": "2" * 64}, tool_versions={"python": "3.12"})
        self.qa = QAProof(session_id="qa-fresh-001", qa_actor="codex-qa", developer_actor="claude-dev", verdict="PASS", head_sha="a" * 40, base_sha="b" * 40, tested_tree_sha="c" * 40, fresh_session=True, read_only_source=True, has_push_credentials=False, has_developer_reasoning=False)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temp.cleanup()

    def authorize(self, *, ci: CIProof | None = None, qa: QAProof | None = None, paths: list[str] | None = None, allow: bool = True) -> str:
        return self.gate.authorize(task_id="A", attempt_id=self.claim["attempt_id"], ci=ci or self.ci, qa=qa or self.qa, changed_paths=paths if paths is not None else ["src/toy_app.py"], allow_merge=allow)

    def test_positive_evidence_authorizes_only_merging(self) -> None:
        key = self.authorize()
        self.assertEqual(self.dispatcher.get_task("A")["state"], "MERGING")
        self.assertEqual(key, evidence_key(project_id="P", task_id="A", acceptance_spec_hash="e" * 64, head_sha="a" * 40, base_sha="b" * 40, tested_tree_sha="c" * 40, suite_fingerprint=self.ci.fingerprint()))
        with Session(self.engine) as session:
            self.assertIsNotNone(session.get(Evidence, key))
            self.assertEqual(len(session.scalars(select(QAVerdict)).all()), 1)

    def test_no_merge_without_policy(self) -> None:
        with self.assertRaisesRegex(DispatchRejected, "MERGE_POLICY_DISABLED"):
            self.authorize(allow=False)
        self.assertEqual(self.dispatcher.get_task("A")["state"], "VERIFYING")

    def test_stale_base_sha_is_rejected_with_unchanged_head(self) -> None:
        self.refs.base = "f" * 40
        with self.assertRaisesRegex(DispatchRejected, "STALE_BASE_SHA"):
            self.authorize()
        self.assertEqual(self.dispatcher.get_task("A")["state"], "VERIFYING")

    def test_stale_head_sha_is_rejected(self) -> None:
        self.refs.head = "f" * 40
        with self.assertRaisesRegex(DispatchRejected, "STALE_HEAD_SHA"):
            self.authorize()

    def test_qa_push_credentials_deny_pass(self) -> None:
        with self.assertRaisesRegex(DispatchRejected, "QA_INDEPENDENCE_NOT_PROVEN"):
            self.authorize(qa=replace(self.qa, has_push_credentials=True))

    def test_qa_non_fresh_or_developer_context_deny_pass(self) -> None:
        for altered in (replace(self.qa, fresh_session=False), replace(self.qa, has_developer_reasoning=True), replace(self.qa, qa_actor="claude-dev"), replace(self.qa, read_only_source=False)):
            with self.subTest(qa=altered):
                with self.assertRaisesRegex(DispatchRejected, "QA_INDEPENDENCE_NOT_PROVEN"):
                    self.authorize(qa=altered)

    def test_ci_failure_or_mismatched_tree_denies_pass(self) -> None:
        with self.assertRaisesRegex(DispatchRejected, "CI_PROOF_INCOMPLETE"):
            self.authorize(ci=replace(self.ci, conclusion="failure"))
        with self.assertRaisesRegex(DispatchRejected, "QA_CI_SHA_MISMATCH"):
            self.authorize(ci=replace(self.ci, tested_tree_sha="9" * 40))

    def test_protected_path_needs_owner_approval(self) -> None:
        with self.assertRaisesRegex(DispatchRejected, "PROTECTED_PATH_APPROVAL_REQUIRED"):
            self.authorize(paths=["contracts/states.yaml"])
        key = evidence_key(project_id="P", task_id="A", acceptance_spec_hash="e" * 64, head_sha="a" * 40, base_sha="b" * 40, tested_tree_sha="c" * 40, suite_fingerprint=self.ci.fingerprint())
        self.gate.grant_protected_paths_approval(task_id="A", evidence_key_value=key, owner_identity="owner")
        self.assertEqual(self.authorize(paths=["contracts/states.yaml"]), key)

    def test_base_drift_before_merge_revokes_pass_and_returns_to_verifying(self) -> None:
        key = self.authorize()
        self.refs.base = "f" * 40
        self.assertTrue(self.gate.invalidate_if_refs_changed(task_id="A", key=key, merge_not_started=True))
        self.assertEqual(self.dispatcher.get_task("A")["state"], "VERIFYING")
        with Session(self.engine) as session:
            self.assertTrue(session.get(Evidence, key).invalidated)
        with self.assertRaisesRegex(DispatchRejected, "EVIDENCE_REVOKED"):
            self.refs.base = "b" * 40
            self.authorize()

    def test_unconfirmed_merge_start_prevents_stale_reverification(self) -> None:
        key = self.authorize()
        self.refs.base = "f" * 40
        with self.assertRaisesRegex(DispatchRejected, "MERGE_RECONCILIATION_REQUIRED"):
            self.gate.invalidate_if_refs_changed(task_id="A", key=key, merge_not_started=False)

    def fail(self, *, report_id: str, code: str, qa_session_id: str, attempt_id: str | None = None) -> dict:
        return self.gate.handle_qa_failure(task_id="A", attempt_id=attempt_id or self.dispatcher.get_task("A")["attempt_id"], report_id=report_id, qa=replace(self.qa, session_id=qa_session_id, verdict="FAIL"), failed_test_node_ids=["test_slug.py::test_ascii"], normalized_error_code=code, failure_stage="TEST", repair_worker_id="repair-worker")

    def test_first_qa_failure_schedules_one_fenced_repair(self) -> None:
        result = self.fail(report_id="r1", code="ASSERTION_ERROR", qa_session_id="qa-session-1")
        self.assertEqual(result["result"], "RETRY")
        self.assertEqual(self.dispatcher.get_task("A")["repair_count"], 1)
        self.assertEqual(self.dispatcher.get_task("A")["state"], "RUNNING")
        self.assertEqual(len(self.dispatcher.pending_outbox()), 2)
        duplicate = self.fail(report_id="r1", code="ASSERTION_ERROR", qa_session_id="qa-session-1", attempt_id=self.claim["attempt_id"])
        self.assertTrue(duplicate["duplicate_report"])
        self.assertEqual(self.dispatcher.get_task("A")["repair_count"], 1)

    def test_repeated_failure_across_attempts_escalates_immediately(self) -> None:
        self.fail(report_id="r1", code="ASSERTION_ERROR", qa_session_id="qa-session-1")
        next_attempt = self.dispatcher.get_task("A")["attempt_id"]
        self.dispatcher.runner_completed(task_id="A", attempt_id=next_attempt, fencing_token=2, artifact_hash="d" * 64)
        result = self.fail(report_id="r2", code="ASSERTION_ERROR", qa_session_id="qa-session-2")
        self.assertEqual(result["result"], "ESCALATED:REPEATED_FAILURE")
        self.assertEqual(self.dispatcher.get_task("A")["state"], "ESCALATED")
        self.assertEqual(self.dispatcher.get_task("A")["repair_count"], 1)

    def test_repair_limit_is_persistent_across_attempts(self) -> None:
        self.fail(report_id="r1", code="ASSERTION_ERROR", qa_session_id="qa-session-1")
        self.dispatcher.runner_completed(task_id="A", attempt_id=self.dispatcher.get_task("A")["attempt_id"], fencing_token=2, artifact_hash="d" * 64)
        self.fail(report_id="r2", code="TYPE_ERROR", qa_session_id="qa-session-2")
        self.dispatcher.runner_completed(task_id="A", attempt_id=self.dispatcher.get_task("A")["attempt_id"], fencing_token=3, artifact_hash="d" * 64)
        result = self.fail(report_id="r3", code="VALUE_ERROR", qa_session_id="qa-session-3")
        self.assertEqual(result["result"], "ESCALATED:REPAIR_LIMIT")
        self.assertEqual(self.dispatcher.get_task("A")["repair_count"], 2)

    def test_qa_session_cannot_be_reused_for_new_attempt(self) -> None:
        self.fail(report_id="r1", code="ASSERTION_ERROR", qa_session_id="qa-same")
        self.dispatcher.runner_completed(task_id="A", attempt_id=self.dispatcher.get_task("A")["attempt_id"], fencing_token=2, artifact_hash="d" * 64)
        with self.assertRaisesRegex(DispatchRejected, "QA_SESSION_REUSED"):
            self.fail(report_id="r2", code="TYPE_ERROR", qa_session_id="qa-same")

    def test_duplicate_qa_report_cannot_change_fingerprint(self) -> None:
        self.fail(report_id="r1", code="ASSERTION_ERROR", qa_session_id="qa-same")
        with self.assertRaisesRegex(DispatchRejected, "QA_REPORT_ID_CONFLICT"):
            self.fail(report_id="r1", code="TYPE_ERROR", qa_session_id="qa-same", attempt_id=self.claim["attempt_id"])


if __name__ == "__main__":
    unittest.main()
