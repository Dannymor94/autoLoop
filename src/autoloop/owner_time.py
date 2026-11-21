"""Owner-entered active-time evidence, fsynced JSONL with an OS writer lock.

All durations are derived from explicitly paired owner events, never the
timestamps of GitHub comments or the agent's estimated work time.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
from typing import Iterator
from uuid import uuid4


class OwnerTimeRejected(ValueError):
    pass


_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path.with_suffix(path.suffix + ".lock"), os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _read_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with path.open("rb") as source:
        for line in source:
            if not line.endswith(b"\n"):
                raise OwnerTimeRejected("INCOMPLETE_OWNER_TIME_EVENT")
            try:
                event = json.loads(line)
            except ValueError as exc:
                raise OwnerTimeRejected("INVALID_OWNER_TIME_EVENT") from exc
            if not isinstance(event, dict) or not {"event_id", "task_id", "action", "at_utc", "idempotency_key"} <= event.keys():
                raise OwnerTimeRejected("INVALID_OWNER_TIME_EVENT")
            records.append(event)
    return records


def _seconds(value: str) -> float:
    try:
        return datetime.fromisoformat(value).astimezone(timezone.utc).timestamp()
    except (ValueError, TypeError) as exc:
        raise OwnerTimeRejected("INVALID_EVENT_TIMESTAMP") from exc


class OwnerTimeLedger:
    def __init__(self, path: Path):
        self.path = path

    def record(self, *, task_id: str, action: str, idempotency_key: str, now: datetime | None = None) -> dict:
        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id) or action not in {"START", "STOP"} or not idempotency_key:
            raise OwnerTimeRejected("INVALID_OWNER_TIME_COMMAND")
        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            raise OwnerTimeRejected("NAIVE_TIMESTAMP")
        with _locked(self.path):
            events = _read_events(self.path)
            for previous in events:
                if previous["idempotency_key"] == idempotency_key:
                    if previous["action"] != action or previous["task_id"] != task_id:
                        raise OwnerTimeRejected("IDEMPOTENCY_CONFLICT")
                    return previous
            currently_active = False
            for item in events:
                if item["task_id"] == task_id:
                    if item["action"] == "START":
                        currently_active = True
                    elif item["action"] == "STOP":
                        currently_active = False
            if (action == "START" and currently_active) or (action == "STOP" and not currently_active):
                raise OwnerTimeRejected("INVALID_OWNER_TIME_TRANSITION")
            event = {"event_id": str(uuid4()), "idempotency_key": idempotency_key, "task_id": task_id, "action": action, "at_utc": moment.astimezone(timezone.utc).isoformat()}
            raw = (json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            fd = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "ab", buffering=0) as target:
                target.write(raw)
                os.fsync(target.fileno())
            return event

    def summary(self, task_id: str) -> dict:
        if not _TASK_ID.fullmatch(task_id):
            raise OwnerTimeRejected("INVALID_TASK_ID")
        with _locked(self.path):
            events = [e for e in _read_events(self.path) if e["task_id"] == task_id]
        total = 0.0
        started: float | None = None
        for event in events:
            when = _seconds(event["at_utc"])
            if event["action"] == "START" and started is None:
                started = when
            elif event["action"] == "STOP" and started is not None:
                if when < started:
                    raise OwnerTimeRejected("NONMONOTONIC_OWNER_TIME")
                total += when - started
                started = None
            else:
                raise OwnerTimeRejected("INVALID_OWNER_TIME_TRANSITION")
        return {"task_id": task_id, "active_seconds": round(total, 6) if started is None else None, "timer_open": started is not None, "event_count": len(events)}
