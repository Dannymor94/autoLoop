"""Crash-safe completion receipts for headless CLI JSONL logs.

The caller must observe process exit before sealing a log. A receipt can be
recovered after the dispatcher dies before writing its SQLite result row.
No receipt means UNKNOWN, even if a terminal-looking event is present.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from tempfile import mkstemp
from typing import Any


class AttemptJournalError(RuntimeError):
    pass


def _inspect_jsonl(log_path: Path, *, provider: str) -> dict[str, Any]:
    terminal_types = {
        "codex": {"turn.completed", "turn.failed"},
        "claude": {"result"},
    }
    if provider not in terminal_types:
        raise AttemptJournalError("UNRECOGNIZED_PROVIDER")
    digest = hashlib.sha256()
    event_count = 0
    terminal: str | None = None
    try:
        with log_path.open("rb") as source:
            for raw_line in source:
                digest.update(raw_line)
                if not raw_line.endswith(b"\n"):
                    raise AttemptJournalError("INCOMPLETE_JSONL_LINE")
                try:
                    event = json.loads(raw_line)
                except (ValueError, UnicodeDecodeError) as exc:
                    raise AttemptJournalError("INVALID_JSONL_EVENT") from exc
                if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                    raise AttemptJournalError("INVALID_JSONL_EVENT")
                event_count += 1
                if event["type"] in terminal_types[provider]:
                    if terminal is not None:
                        raise AttemptJournalError("DUPLICATE_TERMINAL_EVENT")
                    terminal = event["type"]
    except OSError as exc:
        raise AttemptJournalError("UNREADABLE_ATTEMPT_LOG") from exc
    if terminal is None:
        raise AttemptJournalError("MISSING_TERMINAL_EVENT")
    return {"log_sha256": digest.hexdigest(), "event_count": event_count, "terminal_event": terminal}


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def seal_attempt_log(*, log_path: Path, receipt_path: Path, request_id: str, provider: str, exit_code: int, fencing_token: int | None = None, command_sha256: str | None = None) -> dict[str, Any]:
    """Durably write log before an atomic receipt, preceding any DB result."""
    if not isinstance(exit_code, int) or isinstance(exit_code, bool) or not request_id:
        raise AttemptJournalError("INVALID_PROCESS_COMPLETION")
    if log_path.is_symlink() or receipt_path.is_symlink():
        raise AttemptJournalError("UNTRUSTED_JOURNAL_SYMLINK")
    with log_path.open("rb") as source:
        os.fsync(source.fileno())
    _fsync_directory(log_path.parent)
    result = _inspect_jsonl(log_path, provider=provider)
    receipt = {"version": 1, "request_id": request_id, "provider": provider, "exit_code": exit_code, **result}
    if fencing_token is not None:
        if isinstance(fencing_token, bool) or not isinstance(fencing_token, int) or fencing_token < 1:
            raise AttemptJournalError("INVALID_FENCE")
        receipt["fencing_token"] = fencing_token
    if command_sha256 is not None:
        if len(command_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in command_sha256):
            raise AttemptJournalError("INVALID_COMMAND_SHA")
        receipt["command_sha256"] = command_sha256
    payload = (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    receipt_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if receipt_path.exists():
        if recover_attempt_log(log_path=log_path, receipt_path=receipt_path) != receipt:
            raise AttemptJournalError("COMPLETION_RECEIPT_CONFLICT")
        return receipt
    fd, temp_name = mkstemp(prefix=".receipt-", dir=receipt_path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        # link() is atomic and will not overwrite an existing receipt.
        os.link(temp_name, receipt_path)
        _fsync_directory(receipt_path.parent)
    except FileExistsError as exc:
        raise AttemptJournalError("CONCURRENT_COMPLETION_RECEIPT") from exc
    finally:
        Path(temp_name).unlink(missing_ok=True)
    return receipt


def recover_attempt_log(*, log_path: Path, receipt_path: Path) -> dict[str, Any] | None:
    """Return complete verified receipt, or None (= UNKNOWN).

    Recovery never infers a successful process exit from a raw JSONL footer.
    """
    try:
        stored = json.loads(receipt_path.read_text(encoding="utf-8"))
        if not isinstance(stored, dict) or stored.get("version") != 1:
            return None
        observed = _inspect_jsonl(log_path, provider=stored["provider"])
        if not isinstance(stored.get("exit_code"), int) or isinstance(stored["exit_code"], bool):
            return None
        if any(stored.get(key) != value for key, value in observed.items()):
            return None
        if not isinstance(stored.get("request_id"), str) or not stored["request_id"]:
            return None
        return stored
    except (OSError, ValueError, TypeError, KeyError, AttemptJournalError):
        return None
