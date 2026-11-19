"""AL-103 mock/command validation; no live model requests are issued."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autoloop.dispatcher import DispatchRejected, payload_hash  # noqa: E402
from autoloop.runner import (  # noqa: E402
    ClaudeCliAdapter,
    CodexCliAdapter,
    MockAdapter,
    RunnerCommand,
    RunnerUnsupported,
    codex_command_args,
    parse_codex_usage,
    validate_command,
)


class RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.worktree = self.root / "worktree-a"
        self.worktree.mkdir()
        subprocess.run(["git", "init", "-q", str(self.worktree)], check=True, capture_output=True)
        self.payload = {"project_id": "p", "task_id": "A", "attempt_id": "attempt", "worker_id": "codex", "fencing_token": 1, "instructions": "Implement a bounded feature", "instructions_hash": hashlib.sha256(b"Implement a bounded feature").hexdigest(), "acceptance_spec_hash": "a" * 64}
        self.command = RunnerCommand(request_id=str(uuid.uuid4()), payload=self.payload, payload_hash=payload_hash(self.payload), worktree=self.worktree)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_mock_execution_is_deterministic_and_without_fake_tokens(self) -> None:
        result = MockAdapter(allowed_worktree_root=self.root).execute(self.command)
        self.assertEqual(result["event_type"], "COMPLETED")
        self.assertIsNone(result["usage"]["subscription_remaining"])
        self.assertEqual(MockAdapter(allowed_worktree_root=self.root).execute(self.command), result)

    def test_tampered_payload_hash_fails_closed(self) -> None:
        command = RunnerCommand(request_id=self.command.request_id, payload=self.payload, payload_hash="f" * 64, worktree=self.worktree)
        with self.assertRaisesRegex(DispatchRejected, "PAYLOAD_HASH_MISMATCH"):
            validate_command(command, allowed_worktree_root=self.root)

    def test_tampered_instructions_fail_closed(self) -> None:
        payload = dict(self.payload, instructions="a different prompt")
        command = RunnerCommand(request_id=self.command.request_id, payload=payload, payload_hash=payload_hash(payload), worktree=self.worktree)
        with self.assertRaisesRegex(DispatchRejected, "INSTRUCTIONS_HASH_MISMATCH"):
            validate_command(command, allowed_worktree_root=self.root)

    def test_dispatcher_request_id_is_mandatory(self) -> None:
        command = RunnerCommand(request_id="", payload=self.payload, payload_hash=self.command.payload_hash, worktree=self.worktree)
        with self.assertRaisesRegex(DispatchRejected, "MISSING_DISPATCHER_REQUEST_ID"):
            validate_command(command, allowed_worktree_root=self.root)

    def test_worktree_must_be_isolated_under_approved_root(self) -> None:
        command = RunnerCommand(request_id=self.command.request_id, payload=self.payload, payload_hash=self.command.payload_hash, worktree=self.root)
        with self.assertRaisesRegex(DispatchRejected, "WORKTREE_NOT_ISOLATED"):
            validate_command(command, allowed_worktree_root=self.root)

    def test_codex_invocation_uses_stdin_json_and_safe_sandbox(self) -> None:
        args = codex_command_args(self.command)
        self.assertEqual(args[:3], ["codex", "exec", "--json"])
        self.assertIn("workspace-write", args)
        self.assertNotIn("danger-full-access", args)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", args)
        self.assertEqual(args[-1], "-")

    def test_structured_codex_usage_does_not_invent_quota(self) -> None:
        usage = parse_codex_usage({"type": "turn.completed", "usage": {"input_tokens": 123, "output_tokens": 9}})
        self.assertEqual((usage["input_tokens"], usage["output_tokens"]), (123, 9))
        self.assertIsNone(usage["subscription_remaining"])
        self.assertIsNone(usage["context_used_percent"])
        self.assertIsNone(parse_codex_usage({"type": "item.completed"}))

    def test_unsupported_compact_never_clears_session(self) -> None:
        adapter = CodexCliAdapter(allowed_worktree_root=self.root, log_dir=self.root / "logs")
        self.assertEqual(adapter.compact_if_supported("request"), "UNSUPPORTED")

    def test_claude_not_fake_success(self) -> None:
        with self.assertRaises(RunnerUnsupported):
            ClaudeCliAdapter().launch(self.command)


if __name__ == "__main__":
    unittest.main()
