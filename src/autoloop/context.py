"""Truthful usage accounting and durable context checkpoints (no /clear)."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from sqlalchemy import Engine, select

from autoloop.database import write_tx
from autoloop.dispatcher import DispatchRejected, Dispatcher
from autoloop.evidence import sha256_canonical
from autoloop.git_snapshot import GitSnapshot, GitSnapshotError, capture_git_snapshot, require_snapshot_match
from autoloop.models import Attempt, Event, UsageSample


_GIT_SHA = re.compile(r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")


class ContextTracker:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.dispatcher = Dispatcher(engine)

    def record_usage(self, *, attempt_id: str, event_id: str, input_tokens: int | None, output_tokens: int | None, context_used_percent: float | None = None, subscription_remaining: int | None = None) -> dict:
        """Accept observed structured values only; None means provider UNKNOWN."""
        if not event_id:
            raise DispatchRejected("MISSING_USAGE_EVENT_ID")
        for value in (input_tokens, output_tokens, subscription_remaining):
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                raise DispatchRejected("INVALID_TOKEN_COUNT")
        if context_used_percent is not None and (not isinstance(context_used_percent, (int, float)) or isinstance(context_used_percent, bool) or not 0 <= context_used_percent <= 100):
            raise DispatchRejected("INVALID_CONTEXT_PERCENT")
        with write_tx(self.engine) as session:
            attempt = session.get(Attempt, attempt_id)
            if attempt is None:
                raise DispatchRejected("UNKNOWN_ATTEMPT")
            existing = session.get(UsageSample, event_id)
            if existing is not None:
                if (existing.attempt_id, existing.input_tokens, existing.output_tokens, existing.context_percent, existing.subscription_remaining) != (attempt_id, input_tokens, output_tokens, context_used_percent, subscription_remaining):
                    raise DispatchRejected("USAGE_EVENT_CONFLICT")
                return {"event_id": event_id, "duplicate": True}
            session.add(UsageSample(id=event_id, attempt_id=attempt_id, input_tokens=input_tokens, output_tokens=output_tokens, context_percent=context_used_percent, subscription_remaining=subscription_remaining))
            return {"event_id": event_id, "duplicate": False}

    def observed_usage(self, attempt_id: str) -> dict:
        with write_tx(self.engine) as session:
            if session.get(Attempt, attempt_id) is None:
                raise DispatchRejected("UNKNOWN_ATTEMPT")
            samples = session.scalars(select(UsageSample).where(UsageSample.attempt_id == attempt_id).order_by(UsageSample.id)).all()
            inputs = [x.input_tokens for x in samples if x.input_tokens is not None]
            outputs = [x.output_tokens for x in samples if x.output_tokens is not None]
            percentages = [x.context_percent for x in samples if x.context_percent is not None]
            quota = [x.subscription_remaining for x in samples if x.subscription_remaining is not None]
            # These are cumulative usage *snapshots*: MAX avoids double-counting
            # repeated provider reports. A future collector can supply deltas
            # with an explicit distinct contract.
            return {"input_tokens": max(inputs) if inputs else None, "output_tokens": max(outputs) if outputs else None, "context_used_percent": percentages[-1] if percentages else None, "subscription_remaining": quota[-1] if quota else None, "samples": len(samples)}

    def checkpoint(self, *, task_id: str, attempt_id: str, checkpoint_id: str, head_sha: str, base_sha: str, worktree: Path, summary: str, next_safe_action: str, open_questions: list[str], qa_evidence_key: str | None = None) -> dict:
        if not checkpoint_id or not summary or not next_safe_action or not _GIT_SHA.fullmatch(head_sha) or not _GIT_SHA.fullmatch(base_sha):
            raise DispatchRejected("INVALID_CHECKPOINT")
        try:
            snapshot = capture_git_snapshot(worktree)
        except GitSnapshotError as exc:
            raise DispatchRejected("UNVERIFIABLE_CHECKPOINT_WORKTREE") from exc
        if snapshot.head_sha != head_sha:
            raise DispatchRejected("CHECKPOINT_HEAD_MISMATCH")
        with write_tx(self.engine) as session:
            task = self.dispatcher._require_task(session, task_id)
            attempt = session.get(Attempt, attempt_id)
            if attempt is None or attempt.task_id != task_id:
                raise DispatchRejected("CHECKPOINT_ATTEMPT_MISMATCH")
            data = {"task_id": task_id, "attempt_id": attempt_id, "head_sha": head_sha, "dirty_tree_sha": snapshot.dirty_tree_sha, "base_sha": base_sha, "acceptance_spec_hash": task.acceptance_spec_hash, "summary": summary, "next_safe_action": next_safe_action, "open_questions": open_questions, "qa_evidence_key": qa_evidence_key}
            digest = sha256_canonical(data)
            for event in session.scalars(select(Event).where(Event.task_id == task_id, Event.event_type == "CHECKPOINT_SAVED")):
                if event.details.get("checkpoint_id") == checkpoint_id:
                    if event.details.get("checkpoint_hash") != digest:
                        raise DispatchRejected("CHECKPOINT_ID_CONFLICT")
                    return {"checkpoint_id": checkpoint_id, "checkpoint_hash": digest, "duplicate": True}
            session.add(Event(task_id=task_id, event_type="CHECKPOINT_SAVED", from_state=task.state, to_state=task.state, task_version=task.version, attempt_id=attempt_id, details={"checkpoint_id": checkpoint_id, "checkpoint_hash": digest, **data}))
            return {"checkpoint_id": checkpoint_id, "checkpoint_hash": digest, "duplicate": False}

    def require_checkpoint_unchanged(self, *, task_id: str, checkpoint_id: str, worktree: Path) -> GitSnapshot:
        """Mandatory preflight before Resume and QA; caller must block on mismatch.

        State transition is intentionally not performed here: states.yaml must
        first define OWNER_INTERVENTION guards and the durable event flow.
        """
        with write_tx(self.engine) as session:
            self.dispatcher._require_task(session, task_id)
            events = session.scalars(select(Event).where(Event.task_id == task_id, Event.event_type == "CHECKPOINT_SAVED")).all()
            matched = [item for item in events if item.details.get("checkpoint_id") == checkpoint_id]
            if len(matched) != 1:
                raise DispatchRejected("CHECKPOINT_NOT_FOUND")
            data = matched[0].details
            if not _GIT_SHA.fullmatch(data.get("head_sha", "")) or not _GIT_SHA.fullmatch(data.get("dirty_tree_sha", "")):
                raise DispatchRejected("CHECKPOINT_MISSING_TREE_HASH")
            expected = GitSnapshot(head_sha=data["head_sha"], dirty_tree_sha=data["dirty_tree_sha"])
        return require_snapshot_match(worktree, expected)

    def context_guidance(self, *, attempt_id: str) -> str:
        measured = self.observed_usage(attempt_id)["context_used_percent"]
        if measured is None:
            return "UNKNOWN"
        policy = self.dispatcher.limits["context"]
        if measured >= policy["prepare_new_session_percent"]:
            return "PREPARE_NEW_SESSION"
        if measured >= policy["checkpoint_suggest_percent"]:
            return "SUGGEST_CHECKPOINT"
        return "CONTINUE"

    def clear_session(self, *, task_id: str, attempt_id: str) -> str:
        """Never silently send /clear or invent a successful compact operation."""
        return "UNSUPPORTED"  # future: require checkpoint and explicit new session
