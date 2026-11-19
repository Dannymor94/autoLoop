"""Exact-SHA and independent-QA gate. This module NEVER calls GitHub merge."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
import re
import uuid
from typing import Protocol

import yaml
from sqlalchemy import Engine, select

from autoloop.database import write_tx
from autoloop.dispatcher import DispatchRejected, Dispatcher
from autoloop.evidence import evidence_key, suite_fingerprint, failure_fingerprint, sha256_canonical
from autoloop.models import Approval, Attempt, Event, Evidence, Lease, QAVerdict, utc_now


_GIT_SHA = re.compile(r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
ROOT = Path(__file__).resolve().parents[2]


class GitRefReader(Protocol):
    """Trusted GitHub adapter, independent of the executor platform."""

    def current_head(self, task_id: str) -> str: ...

    def current_base(self, task_id: str) -> str: ...


@dataclass(frozen=True)
class CIProof:
    run_id: str
    head_sha: str
    base_sha: str
    tested_tree_sha: str
    workflow_ref: str
    conclusion: str
    check_commands: tuple[str, ...]
    lockfile_sha256_by_path: dict[str, str]
    ci_workflow_sha256_by_path: dict[str, str]
    tool_versions: dict[str, str]

    def fingerprint(self) -> str:
        return suite_fingerprint(
            check_commands=list(self.check_commands),
            lockfile_sha256_by_path=self.lockfile_sha256_by_path,
            ci_workflow_sha256_by_path=self.ci_workflow_sha256_by_path,
            tool_versions=self.tool_versions,
        )


@dataclass(frozen=True)
class QAProof:
    session_id: str
    qa_actor: str
    developer_actor: str
    verdict: str
    head_sha: str
    base_sha: str
    tested_tree_sha: str
    fresh_session: bool
    read_only_source: bool
    has_push_credentials: bool
    has_developer_reasoning: bool


class Gatekeeper:
    def __init__(self, engine: Engine, *, refs: GitRefReader) -> None:
        self.engine = engine
        self.refs = refs
        self.dispatcher = Dispatcher(engine)
        protected = yaml.safe_load((ROOT / "contracts" / "protected_paths.yaml").read_text(encoding="utf-8"))
        self.protected_paths = tuple(protected["paths"])

    def _protected(self, paths: list[str]) -> list[str]:
        return [path for path in paths if any(fnmatchcase(path, pattern) for pattern in self.protected_paths)]

    def authorize(self, *, task_id: str, attempt_id: str, ci: CIProof, qa: QAProof, changed_paths: list[str], allow_merge: bool = False) -> str:
        """Record evidence and move VERIFYING -> MERGING, without merging anything.

        CIProof and QAProof MUST come from *trusted adapters* after actual CI
        verification and OS-level QA isolation. Do not expose this method as a
        public endpoint accepting agent-authored JSON.
        """
        if not allow_merge:
            raise DispatchRejected("MERGE_POLICY_DISABLED")
        for sha in (ci.head_sha, ci.base_sha, ci.tested_tree_sha, qa.head_sha, qa.base_sha, qa.tested_tree_sha):
            if not _GIT_SHA.fullmatch(sha):
                raise DispatchRejected("INVALID_SHA")
        if ci.conclusion != "success" or not ci.run_id or not ci.workflow_ref or not ci.check_commands or not ci.ci_workflow_sha256_by_path:
            raise DispatchRejected("CI_PROOF_INCOMPLETE")
        if qa.verdict != "PASS" or not qa.session_id or not qa.qa_actor or qa.qa_actor == qa.developer_actor or not qa.fresh_session or not qa.read_only_source or qa.has_push_credentials or qa.has_developer_reasoning:
            raise DispatchRejected("QA_INDEPENDENCE_NOT_PROVEN")
        if (ci.head_sha, ci.base_sha, ci.tested_tree_sha) != (qa.head_sha, qa.base_sha, qa.tested_tree_sha):
            raise DispatchRejected("QA_CI_SHA_MISMATCH")

        with write_tx(self.engine) as session:
            task = self.dispatcher._require_task(session, task_id)
            attempt = session.get(Attempt, attempt_id)
            if task.state != "VERIFYING" or task.current_attempt_id != attempt_id or attempt is None or attempt.status != "COMPLETED":
                raise DispatchRejected("TASK_NOT_READY_FOR_QA")
            # Ref lookups are executed inside the serialized transaction. A
            # real GitHub merge must still recheck refs at the side-effect
            # boundary and prove the merged tree (AL-104 external integration).
            if self.refs.current_head(task_id) != ci.head_sha:
                raise DispatchRejected("STALE_HEAD_SHA")
            if self.refs.current_base(task_id) != ci.base_sha:
                raise DispatchRejected("STALE_BASE_SHA")
            fingerprint = ci.fingerprint()
            key = evidence_key(project_id=task.project_id, task_id=task.id, acceptance_spec_hash=task.acceptance_spec_hash, head_sha=ci.head_sha, base_sha=ci.base_sha, tested_tree_sha=ci.tested_tree_sha, suite_fingerprint=fingerprint)
            protected = self._protected(changed_paths)
            if protected:
                approval = session.get(Approval, f"protected:{task_id}:{key}")
                if approval is None or approval.scope != "protected_paths" or approval.evidence_key != key:
                    raise DispatchRejected("PROTECTED_PATH_APPROVAL_REQUIRED")
            existing = session.get(Evidence, key)
            if existing is not None and existing.invalidated:
                raise DispatchRejected("EVIDENCE_REVOKED")
            if existing is None:
                session.add(Evidence(key=key, task_id=task.id, head_sha=ci.head_sha, base_sha=ci.base_sha, tested_tree_sha=ci.tested_tree_sha, suite_fingerprint=fingerprint, acceptance_spec_hash=task.acceptance_spec_hash, ci_success=True, qa_verdict="PASS", invalidated=False))
                session.add(QAVerdict(id=str(uuid.uuid4()), evidence_key=key, verdict="PASS", qa_session_id=qa.session_id))
            self.dispatcher._transition(session, task, event="QA_AND_CI_PASS", guards={"head_sha_current", "base_sha_current", "tested_tree_sha_current", "acceptance_spec_current", "suite_fingerprint_current", "independent_qa_pass", "ci_success", "merge_policy_allows"}, attempt_id=attempt_id, details={"evidence_key": key, "ci_run_id": ci.run_id, "qa_session_id": qa.session_id})
            return key

    def grant_protected_paths_approval(self, *, task_id: str, evidence_key_value: str, owner_identity: str) -> None:
        """Internal owner-authenticated entry point; not an executor permission."""
        if not owner_identity or not re.fullmatch(r"[a-f0-9]{64}", evidence_key_value):
            raise DispatchRejected("INVALID_OWNER_APPROVAL")
        with write_tx(self.engine) as session:
            self.dispatcher._require_task(session, task_id)
            session.add(Approval(id=f"protected:{task_id}:{evidence_key_value}", task_id=task_id, scope="protected_paths", granted_by=owner_identity, evidence_key=evidence_key_value))

    def invalidate_if_refs_changed(self, *, task_id: str, key: str, merge_not_started: bool) -> bool:
        """Before any merge side effect, stale evidence returns MERGING to VERIFYING."""
        with write_tx(self.engine) as session:
            task = self.dispatcher._require_task(session, task_id)
            proof = session.get(Evidence, key)
            if proof is None or proof.task_id != task_id:
                raise DispatchRejected("UNKNOWN_EVIDENCE")
            stale = self.refs.current_head(task_id) != proof.head_sha or self.refs.current_base(task_id) != proof.base_sha
            if not stale:
                return False
            if task.state != "MERGING" or not merge_not_started:
                raise DispatchRejected("MERGE_RECONCILIATION_REQUIRED")
            proof.invalidated = True
            self.dispatcher._transition(session, task, event="MERGE_EVIDENCE_STALE", guards={"merge_not_started", "evidence_change_observed", "old_evidence_revoked"}, details={"stale_evidence_key": key})
            return True

    def handle_qa_failure(self, *, task_id: str, attempt_id: str, report_id: str, qa: QAProof, failed_test_node_ids: list[str], normalized_error_code: str, failure_stage: str, repair_worker_id: str) -> dict:
        """Repeat detection and bounded repair in one serialized transaction.

        Must be called by the authenticated independent QA adapter. A repeat
        *report* is idempotent; a repeat failure in a *different attempt*
        escalates immediately, even before the repair limit is exhausted.
        """
        if not report_id or not repair_worker_id:
            raise DispatchRejected("INVALID_QA_FAILURE_INPUT")
        if qa.verdict != "FAIL" or not qa.session_id or qa.qa_actor == qa.developer_actor or not qa.fresh_session or not qa.read_only_source or qa.has_push_credentials or qa.has_developer_reasoning:
            raise DispatchRejected("QA_INDEPENDENCE_NOT_PROVEN")
        fingerprint = failure_fingerprint(sorted_failed_test_node_ids=failed_test_node_ids, normalized_error_code=normalized_error_code, failure_stage=failure_stage)
        report_hash = sha256_canonical({"task_id": task_id, "attempt_id": attempt_id, "qa_session_id": qa.session_id, "fingerprint": fingerprint})
        with write_tx(self.engine) as session:
            # At-least-once QA webhook delivery must not schedule a second run.
            prior_reports = session.scalars(select(Event).where(Event.task_id == task_id, Event.event_type == "QA_FAILURE_RECORDED")).all()
            for previous in prior_reports:
                if previous.details.get("report_id") == report_id:
                    if previous.details.get("report_hash") != report_hash:
                        raise DispatchRejected("QA_REPORT_ID_CONFLICT")
                    return {"task_id": task_id, "result": previous.details["result"], "fingerprint": fingerprint, "duplicate_report": True}
            task = self.dispatcher._require_task(session, task_id)
            attempt = session.get(Attempt, attempt_id)
            if task.state != "VERIFYING" or task.current_attempt_id != attempt_id or attempt is None or attempt.status != "COMPLETED":
                raise DispatchRejected("TASK_NOT_READY_FOR_QA")
            if (qa.head_sha, qa.base_sha) != (self.refs.current_head(task_id), self.refs.current_base(task_id)):
                raise DispatchRejected("STALE_QA_REF")
            if any(previous.details.get("qa_session_id") == qa.session_id and previous.attempt_id != attempt_id for previous in prior_reports):
                raise DispatchRejected("QA_SESSION_REUSED")
            repeated = any(previous.details.get("fingerprint") == fingerprint and previous.attempt_id != attempt_id for previous in prior_reports)
            limit = self.dispatcher.limits["repair"]["max_repair_cycles"]
            if repeated:
                result = "ESCALATED:REPEATED_FAILURE"
            elif task.repair_count >= limit:
                result = "ESCALATED:REPAIR_LIMIT"
            else:
                result = "RETRY"
            session.add(Event(task_id=task_id, event_type="QA_FAILURE_RECORDED", from_state=task.state, to_state=task.state, task_version=task.version, attempt_id=attempt_id, details={"report_id": report_id, "report_hash": report_hash, "fingerprint": fingerprint, "result": result, "qa_session_id": qa.session_id}))
            if result.startswith("ESCALATED:"):
                event = "REPEATED_FAILURE" if repeated else "REPAIR_LIMIT"
                guard = "duplicate_failure_fingerprint" if repeated else "repair_budget_exhausted"
                self.dispatcher._transition(session, task, event=event, guards={guard, "failure_evidence_recorded"}, attempt_id=attempt_id, details={"fingerprint": fingerprint})
                return {"task_id": task_id, "result": result, "fingerprint": fingerprint, "duplicate_report": False}
            lease = session.get(Lease, task_id)
            if lease is None or lease.worker_id is not None:
                raise DispatchRejected("REPAIR_LEASE_NOT_AVAILABLE")
            lease.fencing_token += 1
            lease.worker_id = repair_worker_id
            lease.heartbeat_at = utc_now()
            next_attempt = str(uuid.uuid4())
            session.add(Attempt(id=next_attempt, task_id=task_id, worker_id=repair_worker_id, fencing_token=lease.fencing_token, status="CREATED"))
            task.current_attempt_id = next_attempt
            task.repair_count += 1
            self.dispatcher._transition(session, task, event="START_REPAIR", guards={"qa_failure_recorded", "failure_fingerprint_new", "repair_budget_available", "new_attempt_lease_granted"}, attempt_id=next_attempt, details={"prior_attempt_id": attempt_id, "fingerprint": fingerprint, "repair_count": task.repair_count})
            payload = {"project_id": task.project_id, "task_id": task_id, "attempt_id": next_attempt, "worker_id": repair_worker_id, "fencing_token": lease.fencing_token, "repair_of": attempt_id, "instructions": task.instructions, "instructions_hash": task.instructions_hash, "acceptance_spec_hash": task.acceptance_spec_hash}
            self.dispatcher._create_command(session, task, operation="START", key=f"qa-repair:{report_id}", payload=payload, attempt_id=next_attempt, status="PENDING")
            return {"task_id": task_id, "result": result, "fingerprint": fingerprint, "duplicate_report": False, "next_attempt_id": next_attempt}
