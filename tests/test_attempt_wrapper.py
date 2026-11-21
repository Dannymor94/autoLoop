from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autoloop.attempt_wrapper import (  # noqa: E402
    AttemptRejected, load_attempt_spec, reconcile_attempt, run_attempt,
)


class AttemptWrapperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.tree_root = self.root / "trees"
        self.tree_root.mkdir()
        self.worktree = self.tree_root / "one"
        subprocess.run(["git", "init", "-q", str(self.worktree)], check=True, capture_output=True)
        self.attempts = self.root / "attempts"
        self.attempts.mkdir()
        self.prompt = self.root / "prompt.txt"
        self.prompt.write_text("do one task", encoding="utf-8")
        self.attempt_id = str(uuid.uuid4())
        self.request_id = str(uuid.uuid4())
        self.spec_path = self.root / "spec.json"
        self.spec_fields = {"version": 1, "attempt_id": self.attempt_id, "request_id": self.request_id, "fencing_token": 3, "provider": "codex", "worktree": str(self.worktree), "prompt_path": str(self.prompt), "prompt_sha256": hashlib.sha256(self.prompt.read_bytes()).hexdigest(), "timeout_seconds": 4, "grace_seconds": 1, "max_turns": 5, "model": None}
        self.spec = self.save_spec()

    def tearDown(self):
        self.temp.cleanup()

    def save_spec(self):
        self.spec_path.write_text(json.dumps(self.spec_fields, sort_keys=True), encoding="utf-8")
        return load_attempt_spec(self.spec_path, expected_sha256=hashlib.sha256(self.spec_path.read_bytes()).hexdigest(), allowed_worktree_root=self.tree_root)

    def test_single_launch_durable_receipt_and_no_duplicate(self):
        code = "import json,sys; print(json.dumps({'type':'thread.started'})); print(json.dumps({'type':'turn.completed','usage':{'input_tokens':3}}))"
        self.assertEqual(reconcile_attempt(self.spec, attempts_root=self.attempts)["status"], "UNKNOWN")
        receipt = run_attempt(self.spec, attempts_root=self.attempts, env=os.environ.copy(), argv=[sys.executable, "-c", code])
        self.assertEqual(receipt["fencing_token"], 3)
        self.assertEqual(receipt["command_sha256"], self.spec.command_sha256)
        self.assertEqual(reconcile_attempt(self.spec, attempts_root=self.attempts)["status"], "FINISHED")
        with self.assertRaisesRegex(AttemptRejected, "ATTEMPT_MAY_HAVE_STARTED"):
            run_attempt(self.spec, attempts_root=self.attempts, env=os.environ.copy(), argv=[sys.executable, "-c", code])

    def test_pinned_manifest_and_prompt_hash(self):
        self.prompt.write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(AttemptRejected, "PROMPT_HASH_MISMATCH"):
            self.save_spec()
        self.prompt.write_text("do one task", encoding="utf-8")
        with self.assertRaisesRegex(AttemptRejected, "COMMAND_HASH_MISMATCH"):
            load_attempt_spec(self.spec_path, expected_sha256="0" * 64, allowed_worktree_root=self.tree_root)

    def test_partial_log_does_not_create_false_exit(self):
        code = "import json;print(json.dumps({'type':'thread.started'}))"
        receipt = run_attempt(self.spec, attempts_root=self.attempts, env=os.environ.copy(), argv=[sys.executable, "-c", code])
        self.assertIsNone(receipt)
        result = reconcile_attempt(self.spec, attempts_root=self.attempts)
        self.assertEqual(result["status"], "UNKNOWN")

    def test_wrong_fencing_token_invalidates_existing_receipt(self):
        code = "print('{\"type\":\"turn.completed\"}')"
        run_attempt(self.spec, attempts_root=self.attempts, env=os.environ.copy(), argv=[sys.executable, "-c", code])
        self.spec_fields["fencing_token"] = 4
        changed = self.save_spec()
        self.assertEqual(reconcile_attempt(changed, attempts_root=self.attempts)["status"], "UNKNOWN")

    def test_timeout_without_terminal_event_remains_unknown(self):
        self.spec_fields["timeout_seconds"] = 1
        spec = self.save_spec()
        code = "import time; print('{\"type\":\"thread.started\"}',flush=True); time.sleep(30)"
        self.assertIsNone(run_attempt(spec, attempts_root=self.attempts, env=os.environ.copy(), argv=[sys.executable, "-c", code]))
        self.assertEqual(reconcile_attempt(spec, attempts_root=self.attempts)["status"], "UNKNOWN")

    @unittest.skipUnless(os.name == "posix" and hasattr(signal, "SIGKILL"), "POSIX only")
    def test_sigkill_wrapper_preserves_child_lock_and_never_relaunches(self):
        # Test process launches the same run_attempt function as production,
        # with a fake CLI substituted only in this offline test.
        agent = 'import time;print(\'{"type":"thread.started"}\',flush=True);time.sleep(2);print(\'{"type":"turn.completed"}\',flush=True)'
        body = (
            "import hashlib,os,sys;from pathlib import Path;"
            "from autoloop.attempt_wrapper import load_attempt_spec,run_attempt;"
            "p=Path(sys.argv[1]);s=load_attempt_spec(p,expected_sha256=sys.argv[2],allowed_worktree_root=Path(sys.argv[3]));"
            f"run_attempt(s,attempts_root=Path(sys.argv[4]),env=os.environ.copy(),argv=[sys.executable,'-c',{agent!r}])"
        )
        sha = hashlib.sha256(self.spec_path.read_bytes()).hexdigest()
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
        wrapper = subprocess.Popen([sys.executable, "-c", body, str(self.spec_path), sha, str(self.tree_root), str(self.attempts)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            stdout_path = self.attempts / self.attempt_id / "stdout.jsonl"
            deadline = time.monotonic() + 5
            while (not stdout_path.exists() or b'thread.started' not in stdout_path.read_bytes()) and time.monotonic() < deadline:
                time.sleep(0.025)
            self.assertTrue(stdout_path.exists() and b'thread.started' in stdout_path.read_bytes(), "fake CLI did not start")
            os.kill(wrapper.pid, signal.SIGKILL)
            wrapper.wait(timeout=3)
            self.assertEqual(reconcile_attempt(self.spec, attempts_root=self.attempts)["status"], "RUNNING")
            with self.assertRaisesRegex(AttemptRejected, "ATTEMPT_ALREADY_RUNNING"):
                run_attempt(self.spec, attempts_root=self.attempts, env=os.environ.copy(), argv=[sys.executable, "-c", "pass"])
            deadline = time.monotonic() + 7
            while reconcile_attempt(self.spec, attempts_root=self.attempts)["status"] == "RUNNING" and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertEqual(reconcile_attempt(self.spec, attempts_root=self.attempts)["status"], "UNKNOWN")
        finally:
            if wrapper.poll() is None:
                wrapper.kill()
            wrapper.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
