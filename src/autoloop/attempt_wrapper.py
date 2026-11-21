"""One-attempt, no-respawn, durable subprocess wrapper (POSIX/macOS).

Wrapper process must be launched in a detached session by its dispatcher.
The CLI child inherits the flock descriptor. If the wrapper is SIGKILLed,
the child still prevents a duplicate start until it exits; without a sealed
receipt the outcome is UNKNOWN, never automatically retried.

Process evidence is not task QA/CI approval. SQLite reconciliation must still
validate fencing, Git identities and canonical state transitions.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
from typing import Any, Callable
from uuid import UUID

from autoloop.attempt_journal import AttemptJournalError, recover_attempt_log, seal_attempt_log
from autoloop.billing_guard import BillingModeRejected, subscription_preflight


class AttemptRejected(RuntimeError):
    pass


_SHA = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class AttemptSpec:
    attempt_id: str
    request_id: str
    fencing_token: int
    provider: str
    worktree: Path
    prompt_path: Path
    prompt_sha256: str
    timeout_seconds: int
    grace_seconds: int
    max_turns: int
    model: str | None
    command_sha256: str


def load_attempt_spec(path: Path, *, expected_sha256: str, allowed_worktree_root: Path) -> AttemptSpec:
    if not _SHA.fullmatch(expected_sha256) or path.is_symlink() or not path.is_file():
        raise AttemptRejected("INVALID_PINNED_MANIFEST")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise AttemptRejected("COMMAND_HASH_MISMATCH")
    try:
        item = json.loads(raw)
    except ValueError as exc:
        raise AttemptRejected("INVALID_MANIFEST_JSON") from exc
    required = {"version", "attempt_id", "request_id", "fencing_token", "provider", "worktree", "prompt_path", "prompt_sha256", "timeout_seconds", "grace_seconds", "max_turns", "model"}
    if not isinstance(item, dict) or item.keys() != required or item["version"] != 1:
        raise AttemptRejected("INVALID_MANIFEST_SCHEMA")
    for key in ("attempt_id", "request_id"):
        try:
            if str(UUID(item[key])) != item[key]:
                raise ValueError("noncanonical UUID")
        except (TypeError, AttributeError, ValueError) as exc:
            raise AttemptRejected("INVALID_ATTEMPT_ID") from exc
    for key, minimum, maximum in (("fencing_token", 1, 2**63-1), ("timeout_seconds", 1, 86400), ("grace_seconds", 1, 60), ("max_turns", 1, 1000)):
        val = item[key]
        if isinstance(val, bool) or not isinstance(val, int) or not minimum <= val <= maximum:
            raise AttemptRejected("INVALID_BUDGET_OR_FENCE")
    if item["provider"] not in {"codex", "claude"} or not _SHA.fullmatch(str(item["prompt_sha256"])):
        raise AttemptRejected("INVALID_PROVIDER_OR_PROMPT_HASH")
    if item["model"] is not None and (not isinstance(item["model"], str) or not re.fullmatch(r"[a-zA-Z0-9._-]{1,80}", item["model"])):
        raise AttemptRejected("INVALID_MODEL")
    root = allowed_worktree_root.resolve(strict=True)
    worktree = Path(item["worktree"]).resolve(strict=True)
    if not worktree.is_relative_to(root) or worktree == root or not (worktree / ".git").exists():
        raise AttemptRejected("WORKTREE_NOT_ISOLATED")
    prompt = Path(item["prompt_path"])
    if prompt.is_symlink() or not prompt.is_file() or not prompt.is_absolute():
        raise AttemptRejected("INVALID_PROMPT_PATH")
    if hashlib.sha256(prompt.read_bytes()).hexdigest() != item["prompt_sha256"]:
        raise AttemptRejected("PROMPT_HASH_MISMATCH")
    if prompt.stat().st_size > 32768:
        raise AttemptRejected("PROMPT_TOO_LARGE")
    return AttemptSpec(attempt_id=item["attempt_id"], request_id=item["request_id"], fencing_token=item["fencing_token"], provider=item["provider"], worktree=worktree, prompt_path=prompt, prompt_sha256=item["prompt_sha256"], timeout_seconds=item["timeout_seconds"], grace_seconds=item["grace_seconds"], max_turns=item["max_turns"], model=item["model"], command_sha256=expected_sha256)


def vendor_command(spec: AttemptSpec) -> list[str]:
    if spec.provider == "codex":
        argv = ["codex", "exec", "--json", "--sandbox", "workspace-write", "--cd", str(spec.worktree)]
        if spec.model:
            argv += ["--model", spec.model]
        return argv + ["-"]
    argv = ["claude", "-p", "--output-format", "stream-json", "--verbose", "--max-turns", str(spec.max_turns)]
    if spec.model:
        argv += ["--model", spec.model]
    return argv


def _atomic_marker(path: Path, data: dict[str, Any]) -> None:
    payload = (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
    finally:
        parent = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)


def _acquire_lock(path: Path) -> int:
    if path.is_symlink():
        raise AttemptRejected("LOCK_SYMLINK")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(fd)
        raise AttemptRejected("ATTEMPT_ALREADY_RUNNING") from exc
    return fd


def _terminate_group(proc: subprocess.Popen[bytes], grace_seconds: int) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()


def run_attempt(spec: AttemptSpec, *, attempts_root: Path, env: dict[str, str], argv: list[str] | None = None, on_started: Callable[[subprocess.Popen[bytes]], None] | None = None) -> dict[str, Any] | None:
    """Launch once and seal an exit receipt; None means uncertain/failed.

    ``argv`` is injected only by offline tests. Production dispatch uses
    vendor_command and an already validated subscription environment.
    """
    root = attempts_root.resolve(strict=True)
    attempt_dir = root / spec.attempt_id
    if attempt_dir.is_symlink():
        raise AttemptRejected("ATTEMPT_DIR_SYMLINK")
    attempt_dir.mkdir(mode=0o700, exist_ok=True)
    lock_fd = _acquire_lock(attempt_dir / "attempt.lock")
    try:
        marker = attempt_dir / "attempt.started"
        receipt = attempt_dir / "attempt.exit"
        stdout = attempt_dir / "stdout.jsonl"
        stderr = attempt_dir / "stderr.log"
        if any(p.exists() or p.is_symlink() for p in (marker, receipt, stdout, stderr)):
            raise AttemptRejected("ATTEMPT_MAY_HAVE_STARTED")
        # At-most-once launch intent survives even a crash *before* Popen.
        _atomic_marker(marker, {"attempt_id": spec.attempt_id, "request_id": spec.request_id, "fencing_token": spec.fencing_token, "command_sha256": spec.command_sha256})
        if spec.prompt_path.is_symlink():
            raise AttemptRejected("PROMPT_CHANGED_BEFORE_START")
        prompt_fd = os.open(spec.prompt_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(prompt_fd, "rb") as prompt, stdout.open("xb") as output, stderr.open("xb") as errors:
            if hashlib.sha256(prompt.read()).hexdigest() != spec.prompt_sha256:
                raise AttemptRejected("PROMPT_CHANGED_BEFORE_START")
            prompt.seek(0)
            os.fchmod(output.fileno(), 0o600)
            os.fchmod(errors.fileno(), 0o600)
            proc = subprocess.Popen(argv if argv is not None else vendor_command(spec), cwd=spec.worktree, stdin=prompt, stdout=output, stderr=errors, pass_fds=(lock_fd,), start_new_session=True, env=env, close_fds=True)
            if on_started:
                on_started(proc)
            try:
                code = proc.wait(timeout=spec.timeout_seconds)
            except subprocess.TimeoutExpired:
                _terminate_group(proc, spec.grace_seconds)
                code = proc.returncode
            output.flush()
            errors.flush()
            os.fsync(output.fileno())
            os.fsync(errors.fileno())
        try:
            return seal_attempt_log(log_path=stdout, receipt_path=receipt, request_id=spec.request_id, provider=spec.provider, exit_code=code, fencing_token=spec.fencing_token, command_sha256=spec.command_sha256)
        except (AttemptJournalError, OSError):
            return None  # no fabricated FINISHED after missing/partial JSONL
    finally:
        os.close(lock_fd)


def reconcile_attempt(spec: AttemptSpec, *, attempts_root: Path) -> dict[str, Any]:
    attempt_dir = attempts_root / spec.attempt_id
    if attempt_dir.is_symlink() or not attempt_dir.is_dir():
        return {"status": "UNKNOWN", "reason": "ATTEMPT_DIR_UNAVAILABLE"}
    receipt = attempt_dir / "attempt.exit"
    marker = attempt_dir / "attempt.started"
    lock_path = attempt_dir / "attempt.lock"
    if receipt.is_symlink() or marker.is_symlink() or lock_path.is_symlink():
        return {"status": "UNKNOWN", "reason": "UNTRUSTED_ATTEMPT_FILES"}
    result = recover_attempt_log(log_path=attempt_dir / "stdout.jsonl", receipt_path=receipt)
    if result is not None:
        if (result.get("request_id") == spec.request_id and result.get("provider") == spec.provider and result.get("fencing_token") == spec.fencing_token and result.get("command_sha256") == spec.command_sha256):
            return {"status": "FINISHED", "receipt": result}
        return {"status": "UNKNOWN", "reason": "FENCING_OR_COMMAND_MISMATCH"}
    if receipt.exists():
        return {"status": "UNKNOWN", "reason": "INVALID_RECEIPT"}
    if lock_path.exists():
        try:
            fd = _acquire_lock(lock_path)
        except AttemptRejected as exc:
            if str(exc) == "ATTEMPT_ALREADY_RUNNING":
                return {"status": "RUNNING"}
            return {"status": "UNKNOWN", "reason": str(exc)}
        else:
            os.close(fd)
    if marker.exists() or (attempt_dir / "stdout.jsonl").exists():
        return {"status": "UNKNOWN", "reason": "MISSING_EXIT_RECEIPT"}
    return {"status": "NOT_STARTED", "reason": "NO_LAUNCH_PROOF"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="autoLoop detached one-attempt wrapper")
    parser.add_argument("--command-file", type=Path, required=True)
    parser.add_argument("--command-sha256", required=True)
    parser.add_argument("--worktree-root", type=Path, required=True)
    parser.add_argument("--attempts-root", type=Path, required=True)
    parser.add_argument("--home", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        spec = load_attempt_spec(args.command_file, expected_sha256=args.command_sha256, allowed_worktree_root=args.worktree_root)
        env = subscription_preflight(spec.provider, home=args.home, worktree=spec.worktree)
        receipt = run_attempt(spec, attempts_root=args.attempts_root, env=env)
        print(json.dumps({"status": "FINISHED" if receipt else "UNKNOWN", "attempt_id": spec.attempt_id, "receipt": receipt}, sort_keys=True))
        return 0 if receipt else 4
    except (AttemptRejected, BillingModeRejected, OSError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, sort_keys=True), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
