"""Offline fixture for AL-001; NOT a production dispatcher or OSS acceptance proof."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import sqlite3
import sys
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def replay_trace(plan_path: Path = HERE / "scenarios.yaml") -> str:
    """Deterministic graph and assignment replay; zero LLM coordination calls."""
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    tasks = {record["id"]: record for record in plan["tasks"]}
    completed: set[str] = set()
    trace: list[dict] = []
    while len(completed) != len(tasks):
        ready = sorted(
            (t for t in tasks.values() if t["id"] not in completed and set(t["dependencies"]).issubset(completed)),
            key=lambda task: task["id"],
        )
        if not ready:
            raise ValueError("invalid graph: cyclic dependencies")
        for task in ready:
            trace.extend(
                [
                    {"task_id": task["id"], "event": "CLAIM_ATTEMPT", "agent": task["agent"]},
                    {"task_id": task["id"], "event": "MOCK_EXECUTED", "agent": task["agent"]},
                ]
            )
            completed.add(task["id"])
    return canonical_json({"fixture": plan["fixture_name"], "tasks": sorted(tasks), "trace": trace, "coordination_llm_calls": 0})


class MockStore:
    """SQLite/WAL reference test store. No production credentials or Git side effects."""

    def __init__(self, path: Path) -> None:
        self.db = sqlite3.connect(path, isolation_level=None, timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS leases(task_id TEXT PRIMARY KEY, owner TEXT, fence INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS outbox(action_key TEXT PRIMARY KEY, payload TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS remote_mock(action_key TEXT PRIMARY KEY, payload TEXT NOT NULL);
            """
        )

    def claim(self, task_id: str, worker: str, *, recover: bool = False) -> int:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT owner, fence FROM leases WHERE task_id=?", (task_id,)).fetchone()
            if row and row[0] is not None and not recover:
                raise ValueError("LEASE_BUSY")
            next_token = row[1] + 1 if row else 1
            self.db.execute(
                "INSERT INTO leases(task_id,owner,fence) VALUES(?,?,?) "
                "ON CONFLICT(task_id) DO UPDATE SET owner=excluded.owner,fence=excluded.fence",
                (task_id, worker, next_token),
            )
            self.db.execute("COMMIT")
            return next_token
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def check_fence(self, task_id: str, token: int) -> bool:
        row = self.db.execute("SELECT fence FROM leases WHERE task_id=?", (task_id,)).fetchone()
        return bool(row and row[0] == token)

    def enqueue_once(self, action_key: str, payload: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO outbox(action_key,payload) VALUES(?,?)", (action_key, payload))

    def deliver_pending(self, *, crash_after_remote_commit: bool = False) -> None:
        for action_key, payload in self.db.execute("SELECT action_key,payload FROM outbox WHERE delivered=0 ORDER BY action_key").fetchall():
            self.db.execute("INSERT OR IGNORE INTO remote_mock(action_key,payload) VALUES(?,?)", (action_key, payload))
            if crash_after_remote_commit:
                os.kill(os.getpid(), signal.SIGKILL)
            self.db.execute("UPDATE outbox SET delivered=1 WHERE action_key=?", (action_key,))

    def count_effects(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM remote_mock").fetchone()[0]

    def close(self) -> None:
        self.db.close()


class MockPlatform:
    """A deliberately non-privileged executor interface."""

    _allowed = frozenset({"start", "stop", "status", "get_logs"})

    def command(self, name: str) -> str:
        if name not in self._allowed:
            raise PermissionError("platform cannot issue canonical queue, merge, close or repair decisions")
        return "COMPLETED" if name == "start" else "OBSERVED"


def repair_decision(*, past_fingerprints: set[str], fingerprint: str, repair_count: int, max_repair_cycles: int = 2) -> str:
    if fingerprint in past_fingerprints:
        return "ESCALATED:REPEATED_FAILURE"
    if repair_count >= max_repair_cycles:
        return "ESCALATED:REPAIR_LIMIT"
    return "RETRY"


def stop_decision(*, acknowledged: bool) -> tuple[str, str]:
    return ("BLOCKED", "OWNER_STOP") if acknowledged else ("RUNNING", "STOP_PENDING")


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "replay":
        print(replay_trace())
        return 0
    if len(sys.argv) == 4 and sys.argv[1] == "crash":
        path, crash_point = Path(sys.argv[2]), sys.argv[3]
        store = MockStore(path)
        store.claim("ALP-03", "test-worker")
        if crash_point == "after_claim":
            os.kill(os.getpid(), signal.SIGKILL)
        if crash_point == "after_remote_effect":
            store.enqueue_once("mock-pr-001", "fixture payload")
            store.deliver_pending(crash_after_remote_commit=True)
        raise ValueError(f"unknown fixture crash point {crash_point}")
    print("Usage: python harness.py replay | crash <sqlite-path> <after_claim|after_remote_effect>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
