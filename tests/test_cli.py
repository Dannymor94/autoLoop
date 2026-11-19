from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))


class CLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "cli.sqlite"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def call(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-m", "autoloop", "--db", str(self.db), *args], cwd=ROOT, env={key: value for key, value in env.items() if key != "AUTOLOOP_OWNER_PASSWORD"}, capture_output=True, text=True, check=False)

    def test_bootstrap_create_claim_and_restart(self) -> None:
        self.assertEqual(self.call("init-db").returncode, 0)
        self.assertEqual(self.call("add-project", "--id", "P", "--name", "Test").returncode, 0)
        self.assertEqual(self.call("add-plan", "--id", "PL", "--project", "P", "--spec-hash", "a" * 64).returncode, 0)
        self.assertEqual(self.call("add-task", "--id", "A", "--plan", "PL", "--title", "Test", "--acceptance-hash", "b" * 64).returncode, 0)
        first = self.call("claim", "--worker", "mock", "--key", "tick")
        self.assertEqual(first.returncode, 0)
        result = json.loads(first.stdout)
        self.assertEqual(result["fencing_token"], 1)
        second = self.call("claim", "--worker", "mock", "--key", "tick")
        self.assertEqual(json.loads(second.stdout), result)
        self.assertEqual(json.loads(self.call("tasks").stdout)[0]["state"], "RUNNING")

    def test_server_refuses_missing_password(self) -> None:
        result = self.call("serve")
        self.assertEqual(result.returncode, 2)
        self.assertIn("AUTOLOOP_OWNER_PASSWORD", result.stderr)


if __name__ == "__main__":
    unittest.main()
