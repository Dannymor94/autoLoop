"""Subscription CLI execution adapter; never controls queue, QA or merge."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
from typing import Any
from uuid import UUID

from autoloop.dispatcher import DispatchRejected, payload_hash


class RunnerUnsupported(RuntimeError):
    pass


@dataclass(frozen=True)
class RunnerCommand:
    request_id: str
    payload: dict[str, Any]
    payload_hash: str
    worktree: Path
    model: str | None = None


def validate_command(command: RunnerCommand, *, allowed_worktree_root: Path) -> None:
    try:
        UUID(command.request_id)
    except ValueError as exc:
        raise DispatchRejected("MISSING_DISPATCHER_REQUEST_ID") from exc
    if command.payload_hash != payload_hash(command.payload):
        raise DispatchRejected("PAYLOAD_HASH_MISMATCH")
    for field in ("project_id", "task_id", "attempt_id", "fencing_token", "instructions", "instructions_hash", "acceptance_spec_hash"):
        if field not in command.payload:
            raise DispatchRejected(f"MISSING_COMMAND_FIELD:{field}")
    if hashlib.sha256(command.payload["instructions"].encode("utf-8")).hexdigest() != command.payload["instructions_hash"]:
        raise DispatchRejected("INSTRUCTIONS_HASH_MISMATCH")
    if not isinstance(command.payload["fencing_token"], int) or command.payload["fencing_token"] < 1:
        raise DispatchRejected("INVALID_FENCE")
    worktree = command.worktree.resolve(strict=True)
    root = allowed_worktree_root.resolve(strict=True)
    if not worktree.is_dir() or not worktree.is_relative_to(root) or worktree == root or not (worktree / ".git").exists():
        raise DispatchRejected("WORKTREE_NOT_ISOLATED")


def codex_command_args(command: RunnerCommand) -> list[str]:
    args = ["codex", "exec", "--json", "--sandbox", "workspace-write", "--cd", str(command.worktree.resolve())]
    if command.model is not None:
        if not command.model or command.model.startswith("-"):
            raise DispatchRejected("INVALID_MODEL_NAME")
        args.extend(["--model", command.model])
    args.append("-")  # prompt is delivered on stdin; never parsed by a shell
    return args


def restricted_cli_env() -> dict[str, str]:
    """Remove ambient GitHub merge tokens from child processes.

    This is defense in depth, NOT a replacement for a dedicated OS identity
    with branch-scoped Git credentials. Must be verified on user's runner host.
    """
    blocked = {"GH_TOKEN", "GITHUB_TOKEN", "GITHUB_PAT", "GIT_ASKPASS", "SSH_ASKPASS", "SSH_AUTH_SOCK", "GIT_SSH_COMMAND"}
    env = {key: value for key, value in os.environ.items() if key not in blocked}
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def parse_codex_usage(event: dict[str, Any]) -> dict[str, int | float | None] | None:
    """Read actual structured counters; do not extrapolate subscription quotas."""
    if event.get("type") != "turn.completed":
        return None
    usage = event.get("usage")
    if not isinstance(usage, dict):
        return {"input_tokens": None, "output_tokens": None, "context_used_percent": None, "subscription_remaining": None}
    def counter(key: str) -> int | None:
        value = usage.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
    return {"input_tokens": counter("input_tokens"), "output_tokens": counter("output_tokens"), "context_used_percent": None, "subscription_remaining": None}


class CodexCliAdapter:
    def __init__(self, *, allowed_worktree_root: Path, log_dir: Path) -> None:
        self.root = allowed_worktree_root
        self.log_dir = log_dir.resolve()
        self.log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.active: dict[str, subprocess.Popen[str]] = {}
        self.logs: dict[str, tuple[Path, Path]] = {}

    def launch(self, command: RunnerCommand) -> str:
        validate_command(command, allowed_worktree_root=self.root)
        if shutil.which("codex") is None:
            raise RunnerUnsupported("Codex CLI is not installed")
        if command.request_id in self.active:
            return command.request_id  # in-memory dedup; DB outbox handles restart
        prompt = command.payload["instructions"]
        if len(prompt.encode("utf-8")) > 32768:
            raise DispatchRejected("INSTRUCTIONS_TOO_LARGE")
        stdout_path = self.log_dir / f"{command.request_id}.stdout.jsonl"
        stderr_path = self.log_dir / f"{command.request_id}.stderr.log"
        # Files (not bounded OS pipes) allow arbitrarily long JSONL output
        # without blocking the CLI process while the dispatcher is offline.
        with stdout_path.open("xb") as stdout_handle, stderr_path.open("xb") as stderr_handle:
            os.chmod(stdout_path, 0o600)
            os.chmod(stderr_path, 0o600)
            proc = subprocess.Popen(
                codex_command_args(command),
                cwd=command.worktree,
                stdin=subprocess.PIPE,
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
                env=restricted_cli_env(),
                start_new_session=True,
            )
        if proc.stdin is None:
            proc.kill()
            raise RuntimeError("No CLI stdin")
        proc.stdin.write(prompt)
        proc.stdin.close()
        self.active[command.request_id] = proc
        self.logs[command.request_id] = (stdout_path, stderr_path)
        return command.request_id

    def status(self, request_id: str) -> dict[str, Any]:
        proc = self.active.get(request_id)
        if proc is None:
            return {"status": "UNKNOWN", "reason": "NOT_IN_PROCESS_REGISTRY"}
        code = proc.poll()
        return {"status": "RUNNING" if code is None else "EXITED", "exit_code": code}

    def request_stop(self, request_id: str) -> str:
        proc = self.active.get(request_id)
        if proc is None:
            return "UNKNOWN"
        if proc.poll() is not None:
            return "EXITED"
        os.killpg(proc.pid, signal.SIGINT)
        return "STOP_PENDING"  # never claim BLOCKED until process exit is confirmed

    def read_result_after_exit(self, request_id: str) -> dict[str, Any]:
        proc = self.active.get(request_id)
        if proc is None or proc.poll() is None:
            raise DispatchRejected("PROCESS_NOT_FINISHED")
        stdout_path, stderr_path = self.logs[request_id]
        usage: dict[str, int | float | None] = {"input_tokens": None, "output_tokens": None, "context_used_percent": None, "subscription_remaining": None}
        events: list[dict] = []
        total_event_count = 0
        thread_id: str | None = None
        with stdout_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(item, dict):
                    continue
                total_event_count += 1
                if item.get("type") == "thread.started" and isinstance(item.get("thread_id"), str):
                    thread_id = item["thread_id"]
                if len(events) < 200:
                    events.append({"type": item.get("type", "UNKNOWN")})
                observed = parse_codex_usage(item)
                if observed is not None:
                    usage = observed
        with stderr_path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - 1500))
            stderr_tail = handle.read().decode("utf-8", errors="replace")
        del self.active[request_id]
        del self.logs[request_id]
        return {"exit_code": proc.returncode, "thread_id": thread_id, "events": events, "total_event_count": total_event_count, "usage": usage, "stderr_tail": stderr_tail}

    def compact_if_supported(self, _request_id: str) -> str:
        return "UNSUPPORTED"  # no blind /clear; requires checkpoint + new explicit session


class MockAdapter:
    def __init__(self, *, allowed_worktree_root: Path) -> None:
        self.root = allowed_worktree_root

    def execute(self, command: RunnerCommand) -> dict[str, Any]:
        validate_command(command, allowed_worktree_root=self.root)
        return {"request_id": command.request_id, "event_type": "COMPLETED", "result_hash": hashlib.sha256(command.payload["instructions"].encode("utf-8")).hexdigest(), "usage": {"input_tokens": None, "output_tokens": None, "context_used_percent": None, "subscription_remaining": None}}


class ClaudeCliAdapter:
    """Explicitly unsupported here until a real Claude CLI protocol is validated."""

    def launch(self, _command: RunnerCommand) -> None:
        raise RunnerUnsupported("Claude Code CLI protocol has not been tested on an authorized host")
