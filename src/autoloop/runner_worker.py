"""Durable outbox handoff; fail closed across uncertain external starts."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, select

from autoloop.database import write_tx
from autoloop.dispatcher import DispatchRejected, Dispatcher
from autoloop.models import Outbox, RunnerSession
from autoloop.runner import CodexCliAdapter, MockAdapter, RunnerCommand


class RunnerWorker:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.dispatcher = Dispatcher(engine)

    def deliver_start(self, *, request_id: str, adapter: MockAdapter | CodexCliAdapter, worktree: Path, model: str | None = None) -> dict:
        """Never replay a START whose outcome is uncertain after a crash."""
        with write_tx(self.engine) as session:
            outbox = session.scalar(select(Outbox).where(Outbox.request_id == request_id))
            if outbox is None or outbox.operation != "START":
                raise DispatchRejected("UNKNOWN_START_COMMAND")
            existing = session.get(RunnerSession, request_id)
            if existing is not None:
                if outbox.status == "DELIVERED" and existing.status in {"COMPLETED", "RUNNING"}:
                    return {"request_id": request_id, "status": existing.status, "duplicate_delivery": True}
                raise DispatchRejected("DELIVERY_OUTCOME_UNKNOWN")
            command = RunnerCommand(request_id=request_id, payload=outbox.payload, payload_hash=outbox.payload_hash, worktree=worktree, model=model)
            # Validate before reserving the runner slot; no external API is called.
            from autoloop.runner import validate_command
            validate_command(command, allowed_worktree_root=adapter.root)
            session.add(RunnerSession(id=request_id, attempt_id=outbox.attempt_id, status="STARTING"))

        # Intentionally do not retry on exception: a crash or timeout between
        # spawn and acknowledgement can have started an external process.
        if isinstance(adapter, MockAdapter):
            result = adapter.execute(command)
            status = "COMPLETED"
            runner_pid = None
        else:
            adapter.launch(command)
            status = "RUNNING"
            runner_pid = adapter.active[request_id].pid

        with write_tx(self.engine) as session:
            record = session.get(RunnerSession, request_id)
            outbox = session.scalar(select(Outbox).where(Outbox.request_id == request_id))
            if record is None or record.status != "STARTING" or outbox is None:
                raise DispatchRejected("RUNNER_SESSION_RACE")
            record.status = status
            record.pid = runner_pid
            outbox.status = "DELIVERED"
        return {"request_id": request_id, "status": status, "duplicate_delivery": False}
