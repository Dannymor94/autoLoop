"""One-writer, model-free durable dispatcher with fenced attempts and outbox."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from autoloop.database import write_tx
from autoloop.models import (
    Attempt,
    CommandReceipt,
    Event,
    Lease,
    Outbox,
    Plan,
    Project,
    Task,
    TaskDependency,
    utc_now,
)


CONTRACT_ROOT = Path(__file__).resolve().parents[2] / "contracts"
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


class DispatchRejected(ValueError):
    """Fail-closed domain rejection; not a retriable LLM error."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def payload_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


class Dispatcher:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.graph = yaml.safe_load((CONTRACT_ROOT / "states.yaml").read_text(encoding="utf-8"))
        self.limits = yaml.safe_load((CONTRACT_ROOT / "limits.yaml").read_text(encoding="utf-8"))

    def _transition(self, session: Session, task: Task, *, event: str, guards: set[str], attempt_id: str | None = None, details: dict | None = None) -> None:
        matches = [t for t in self.graph["transitions"] if t["from"] == task.state and t["event"] == event]
        if len(matches) != 1:
            raise DispatchRejected(f"ILLEGAL_TRANSITION:{task.state}/{event}")
        missing = set(matches[0]["guards"]) - guards
        if missing:
            raise DispatchRejected("GUARDS_NOT_PROVEN:" + ",".join(sorted(missing)))
        previous = task.state
        task.state = matches[0]["to"]
        task.version += 1
        session.add(Event(task_id=task.id, event_type=event, from_state=previous, to_state=task.state, task_version=task.version, attempt_id=attempt_id, details=details or {}))

    def _require_task(self, session: Session, task_id: str) -> Task:
        task = session.get(Task, task_id)
        if task is None:
            raise DispatchRejected("UNKNOWN_TASK")
        return task

    def _dependencies_done(self, session: Session, task: Task) -> bool:
        if not task.dependency_ids:
            return True
        dependencies = session.scalars(select(Task).where(Task.id.in_(task.dependency_ids))).all()
        return len(dependencies) == len(task.dependency_ids) and all(dep.state == "DONE" for dep in dependencies)

    def add_project(self, *, project_id: str, name: str, repo_url: str | None = None) -> None:
        if not project_id or not name:
            raise DispatchRejected("INVALID_PROJECT")
        with write_tx(self.engine) as session:
            if session.get(Project, project_id) is not None:
                raise DispatchRejected("DUPLICATE_PROJECT")
            session.add(Project(id=project_id, name=name, repo_url=repo_url))

    def add_plan(self, *, plan_id: str, project_id: str, spec_hash: str) -> None:
        if not _SHA256.fullmatch(spec_hash):
            raise DispatchRejected("INVALID_SPEC_HASH")
        with write_tx(self.engine) as session:
            if session.get(Project, project_id) is None:
                raise DispatchRejected("UNKNOWN_PROJECT")
            if session.get(Plan, plan_id) is not None:
                raise DispatchRejected("DUPLICATE_PLAN")
            session.add(Plan(id=plan_id, project_id=project_id, spec_hash=spec_hash))

    def add_task(self, *, task_id: str, plan_id: str, title: str, acceptance_spec_hash: str, dependency_ids: list[str] | None = None, instructions: str | None = None) -> None:
        deps = sorted(set(dependency_ids or []))
        instructions = title if instructions is None else instructions
        if not _SHA256.fullmatch(acceptance_spec_hash) or task_id in deps or not title or not instructions:
            raise DispatchRejected("INVALID_TASK")
        with write_tx(self.engine) as session:
            plan = session.get(Plan, plan_id)
            if plan is None:
                raise DispatchRejected("UNKNOWN_PLAN")
            if session.get(Task, task_id) is not None:
                raise DispatchRejected("DUPLICATE_TASK")
            for dep_id in deps:
                predecessor = self._require_task(session, dep_id)
                if predecessor.project_id != plan.project_id:
                    raise DispatchRejected("CROSS_PROJECT_DEPENDENCY")
            task = Task(id=task_id, project_id=plan.project_id, plan_id=plan_id, title=title, instructions=instructions, instructions_hash=hashlib.sha256(instructions.encode("utf-8")).hexdigest(), acceptance_spec_hash=acceptance_spec_hash, dependency_ids=deps, state="READY", version=0, repair_count=0)
            session.add(task)
            session.flush()
            for dep_id in deps:
                session.add(TaskDependency(task_id=task_id, depends_on_id=dep_id))
            session.add(Event(task_id=task.id, event_type="TASK_CREATED", from_state=None, to_state="READY", task_version=0, details={"plan_id": plan_id}))
            if not self._dependencies_done(session, task):
                self._transition(session, task, event="DEPENDENCY_BLOCKED", guards={"dependency_blocked_reason_recorded"}, details={"reason": "DEPENDENCY_WAIT"})
                task.block_reason = "DEPENDENCY_WAIT"

    def get_task(self, task_id: str) -> dict:
        with Session(self.engine) as session:
            task = self._require_task(session, task_id)
            return self._snapshot(task)

    @staticmethod
    def _snapshot(task: Task) -> dict:
        return {"task_id": task.id, "project_id": task.project_id, "state": task.state, "version": task.version, "reason": task.block_reason, "repair_count": task.repair_count, "attempt_id": task.current_attempt_id}

    def list_tasks(self, *, project_id: str | None = None) -> list[dict]:
        with Session(self.engine) as session:
            query = select(Task).order_by(Task.created_at, Task.id)
            if project_id is not None:
                query = query.where(Task.project_id == project_id)
            return [self._snapshot(task) for task in session.scalars(query).all()]

    def _existing_command(self, session: Session, *, key: str, operation: str, task_id: str | None = None, digest: str | None = None) -> CommandReceipt | None:
        existing = session.scalar(select(CommandReceipt).where(CommandReceipt.idempotency_key == key))
        if existing is not None and (existing.operation != operation or (task_id is not None and existing.task_id != task_id) or (digest is not None and existing.payload_hash != digest)):
            raise DispatchRejected("IDEMPOTENCY_CONFLICT")
        return existing

    def _create_command(self, session: Session, task: Task, *, operation: str, key: str, payload: dict, attempt_id: str, status: str) -> CommandReceipt:
        request_id = str(uuid.uuid4())  # never generated by a CLI runner
        digest = payload_hash(payload)
        receipt = CommandReceipt(request_id=request_id, idempotency_key=key, task_id=task.id, operation=operation, payload_hash=digest, status=status, result={"attempt_id": attempt_id, "task_id": task.id, **({"fencing_token": payload["fencing_token"]} if "fencing_token" in payload else {})})
        session.add(receipt)
        session.add(Outbox(id=str(uuid.uuid4()), task_id=task.id, attempt_id=attempt_id, request_id=request_id, operation=operation, payload=payload, payload_hash=digest, status="PENDING", delivery_attempts=0))
        return receipt

    def claim_next(self, *, worker_id: str, idempotency_key: str) -> dict | None:
        """Atomically claim one task, assign fence and publish one durable command."""
        if not worker_id or not idempotency_key:
            raise DispatchRejected("INVALID_CLAIM")
        with write_tx(self.engine) as session:
            existing = self._existing_command(session, key=idempotency_key, operation="START")
            if existing is not None:
                return {"request_id": existing.request_id, **existing.result}
            for task in session.scalars(select(Task).where(Task.state == "READY").order_by(Task.created_at, Task.id)).all():
                if not self._dependencies_done(session, task):
                    continue
                lease = session.get(Lease, task.id)
                if lease is None:
                    lease = Lease(task_id=task.id, fencing_token=0, worker_id=None)
                    session.add(lease)
                if lease.worker_id is not None:
                    continue
                lease.fencing_token += 1
                lease.worker_id = worker_id
                lease.heartbeat_at = utc_now()
                attempt_id = str(uuid.uuid4())
                session.add(Attempt(id=attempt_id, task_id=task.id, worker_id=worker_id, fencing_token=lease.fencing_token, status="CREATED"))
                task.current_attempt_id = attempt_id
                self._transition(session, task, event="CLAIM_ATTEMPT", guards={"dependencies_done", "lease_granted", "fencing_token_valid"}, attempt_id=attempt_id)
                payload = {"project_id": task.project_id, "task_id": task.id, "attempt_id": attempt_id, "fencing_token": lease.fencing_token, "worker_id": worker_id, "instructions": task.instructions, "instructions_hash": task.instructions_hash, "acceptance_spec_hash": task.acceptance_spec_hash}
                receipt = self._create_command(session, task, operation="START", key=idempotency_key, payload=payload, attempt_id=attempt_id, status="PENDING")
                return {"request_id": receipt.request_id, "task_id": task.id, "attempt_id": attempt_id, "fencing_token": lease.fencing_token}
            return None

    def heartbeat(self, *, task_id: str, attempt_id: str, fencing_token: int) -> None:
        with write_tx(self.engine) as session:
            self._validate_attempt(session, task_id=task_id, attempt_id=attempt_id, fencing_token=fencing_token)
            session.get(Lease, task_id).heartbeat_at = utc_now()

    def _validate_attempt(self, session: Session, *, task_id: str, attempt_id: str, fencing_token: int) -> tuple[Task, Attempt, Lease]:
        task = self._require_task(session, task_id)
        attempt = session.get(Attempt, attempt_id)
        lease = session.get(Lease, task_id)
        if attempt is None or lease is None or attempt.task_id != task_id or task.current_attempt_id != attempt_id or attempt.fencing_token != fencing_token or lease.fencing_token != fencing_token or lease.worker_id != attempt.worker_id:
            raise DispatchRejected("STALE_FENCING_TOKEN")
        return task, attempt, lease

    def runner_completed(self, *, task_id: str, attempt_id: str, fencing_token: int, artifact_hash: str) -> dict:
        if not _SHA256.fullmatch(artifact_hash):
            raise DispatchRejected("INVALID_ARTIFACT_HASH")
        with write_tx(self.engine) as session:
            task = self._require_task(session, task_id)
            prior = session.get(Attempt, attempt_id)
            if prior is not None and prior.task_id == task_id and prior.fencing_token == fencing_token and prior.status == "COMPLETED" and prior.outcome_hash == artifact_hash and task.current_attempt_id == attempt_id and task.state == "VERIFYING":
                return self._snapshot(task)
            task, attempt, lease = self._validate_attempt(session, task_id=task_id, attempt_id=attempt_id, fencing_token=fencing_token)
            if task.state != "RUNNING":
                raise DispatchRejected("TASK_NOT_RUNNING")
            attempt.status = "COMPLETED"
            attempt.outcome_hash = artifact_hash
            lease.worker_id = None
            lease.heartbeat_at = None
            self._transition(session, task, event="EXECUTION_FINISHED", guards={"runner_exit_observed", "attempt_artifacts_recorded", "lease_fencing_valid"}, attempt_id=attempt_id)
            return self._snapshot(task)

    def request_stop(self, *, task_id: str, idempotency_key: str) -> dict:
        with write_tx(self.engine) as session:
            existing = self._existing_command(session, key=idempotency_key, operation="STOP", task_id=task_id)
            if existing is not None:
                return {"request_id": existing.request_id, "status": existing.status, "task_state": self._require_task(session, task_id).state}
            task = self._require_task(session, task_id)
            if task.state != "RUNNING" or task.current_attempt_id is None:
                raise DispatchRejected("TASK_NOT_RUNNING")
            for queued in session.scalars(select(CommandReceipt).where(CommandReceipt.task_id == task_id, CommandReceipt.operation == "STOP", CommandReceipt.status == "STOP_PENDING")):
                if queued.result.get("attempt_id") == task.current_attempt_id:
                    return {"request_id": queued.request_id, "status": queued.status, "task_state": task.state}
            payload = {"project_id": task.project_id, "task_id": task.id, "attempt_id": task.current_attempt_id, "operation": "STOP"}
            digest = payload_hash(payload)
            receipt = self._create_command(session, task, operation="STOP", key=idempotency_key, payload=payload, attempt_id=task.current_attempt_id, status="STOP_PENDING")
            return {"request_id": receipt.request_id, "status": receipt.status, "task_state": task.state}

    def confirm_stop(self, *, request_id: str, task_id: str, attempt_id: str, fencing_token: int, checkpoint_hash: str) -> dict:
        if not _SHA256.fullmatch(checkpoint_hash):
            raise DispatchRejected("INVALID_CHECKPOINT_HASH")
        with write_tx(self.engine) as session:
            receipt = session.get(CommandReceipt, request_id)
            if receipt is None or receipt.operation != "STOP" or receipt.task_id != task_id or receipt.result.get("attempt_id") != attempt_id:
                raise DispatchRejected("UNKNOWN_STOP_COMMAND")
            if receipt.status == "CONFIRMED":
                task = self._require_task(session, task_id)
                if task.state == "BLOCKED" and task.block_reason == "OWNER_STOP" and receipt.result.get("checkpoint_hash") == checkpoint_hash:
                    return self._snapshot(task)
                raise DispatchRejected("STOP_RECEIPT_CONFLICT")
            if receipt.status != "STOP_PENDING":
                raise DispatchRejected("STOP_NOT_PENDING")
            task, attempt, lease = self._validate_attempt(session, task_id=task_id, attempt_id=attempt_id, fencing_token=fencing_token)
            if task.state != "RUNNING":
                raise DispatchRejected("TASK_NOT_RUNNING")
            lease.worker_id = None
            lease.heartbeat_at = None
            attempt.status = "INTERRUPTED"
            attempt.outcome_hash = checkpoint_hash
            task.block_reason = "OWNER_STOP"
            self._transition(session, task, event="OWNER_STOP_CONFIRMED", guards={"runner_stop_confirmed", "checkpoint_recorded", "block_reason_owner_stop"}, attempt_id=attempt_id, details={"checkpoint_hash": checkpoint_hash})
            receipt.status = "CONFIRMED"
            receipt.result = {**receipt.result, "checkpoint_hash": checkpoint_hash}
            return self._snapshot(task)

    def resume_owner_stop(self, *, task_id: str, idempotency_key: str) -> dict:
        with write_tx(self.engine) as session:
            existing = self._existing_command(session, key=idempotency_key, operation="RESUME", task_id=task_id)
            if existing is not None:
                return dict(existing.result)
            task = self._require_task(session, task_id)
            if task.state != "BLOCKED" or task.block_reason != "OWNER_STOP":
                raise DispatchRejected("NOT_OWNER_STOP")
            lease = session.get(Lease, task.id)
            if lease is not None and lease.worker_id is not None:
                raise DispatchRejected("LEASE_STILL_ACTIVE")
            if not self._dependencies_done(session, task):
                raise DispatchRejected("DEPENDENCIES_NOT_DONE")
            self._transition(session, task, event="RESUME_OWNER_STOP", guards={"block_reason_owner_stop", "runner_stop_confirmed", "dependencies_done", "no_active_lease"})
            task.block_reason = None
            task.current_attempt_id = None
            receipt = CommandReceipt(request_id=str(uuid.uuid4()), idempotency_key=idempotency_key, task_id=task_id, operation="RESUME", payload_hash=payload_hash({"task_id": task_id, "operation": "RESUME"}), status="CONFIRMED", result=self._snapshot(task))
            session.add(receipt)
            return dict(receipt.result)

    def mark_orphaned(self, *, task_id: str, expected_fence: int, runner_quiescence_confirmed: bool = False) -> dict:
        """Unknown runner outcome blocks the task; never automatically rerun it."""
        if not runner_quiescence_confirmed:
            raise DispatchRejected("RUNNER_QUIESCENCE_NOT_CONFIRMED")
        with write_tx(self.engine) as session:
            task = self._require_task(session, task_id)
            lease = session.get(Lease, task_id)
            if task.state != "RUNNING" or lease is None or lease.fencing_token != expected_fence or lease.worker_id is None:
                raise DispatchRejected("RECOVERY_FENCE_MISMATCH")
            lease.fencing_token += 1
            lease.worker_id = None
            lease.heartbeat_at = None
            task.block_reason = "RUNNER_OUTCOME_UNKNOWN"
            self._transition(session, task, event="EXECUTION_BLOCKED", guards={"runner_quiesced", "blocking_reason_recorded"}, attempt_id=task.current_attempt_id, details={"reason": "RUNNER_OUTCOME_UNKNOWN", "requires_reconciliation": True})
            return self._snapshot(task)

    def pending_outbox(self, *, task_id: str | None = None) -> list[dict]:
        with Session(self.engine) as session:
            query = select(Outbox).where(Outbox.status == "PENDING").order_by(Outbox.request_id)
            if task_id is not None:
                query = query.where(Outbox.task_id == task_id)
            return [{"request_id": x.request_id, "task_id": x.task_id, "attempt_id": x.attempt_id, "operation": x.operation, "payload_hash": x.payload_hash, "payload": x.payload} for x in session.scalars(query)]

    def acknowledge_delivery(self, *, request_id: str, payload_digest: str) -> None:
        with write_tx(self.engine) as session:
            outbox = session.scalar(select(Outbox).where(Outbox.request_id == request_id))
            if outbox is None or outbox.payload_hash != payload_digest:
                raise DispatchRejected("OUTBOX_HASH_MISMATCH")
            outbox.status = "DELIVERED"
            receipt = session.get(CommandReceipt, request_id)
            if receipt is not None and receipt.status == "PENDING":
                receipt.status = "DELIVERED"

    def events_for(self, task_id: str) -> list[dict]:
        with Session(self.engine) as session:
            self._require_task(session, task_id)
            return [{"seq": event.seq, "event": event.event_type, "from": event.from_state, "to": event.to_state, "version": event.task_version, "attempt_id": event.attempt_id} for event in session.scalars(select(Event).where(Event.task_id == task_id).order_by(Event.seq))]
