"""These are mock harness checks, NOT real Bernstein/Kandev/Cezar PASS."""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from harness import MockPlatform, MockStore, repair_decision, replay_trace, stop_decision  # noqa: E402


class OfflinePilotFixtureTests(unittest.TestCase):
    def test_scenarios_identical_for_all_candidates(self) -> None:
        fixture = yaml.safe_load((HERE / "scenarios.yaml").read_text(encoding="utf-8"))
        self.assertEqual([s["id"] for s in fixture["scenarios"]], [f"PILOT-T{n}" for n in range(1, 6)])
        self.assertEqual(len({task["id"] for task in fixture["tasks"]}), 5)

    def test_t1_baseline_is_intentionally_red(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "candidate_tests", "-v"],
            cwd=HERE, capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NotImplementedError", result.stderr)

    def test_t2_byte_identical_graph_and_zero_coordination_llm_calls(self) -> None:
        first, second = replay_trace(), replay_trace()
        self.assertEqual(first.encode("utf-8"), second.encode("utf-8"))
        self.assertEqual(json.loads(first)["coordination_llm_calls"], 0)
        self.assertEqual(len(json.loads(first)["trace"]), 10)

    def test_t3_sigkill_after_claim_and_fencing_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mock.sqlite"
            result = subprocess.run([sys.executable, str(HERE / "harness.py"), "crash", str(path), "after_claim"], cwd=HERE, capture_output=True, check=False)
            self.assertEqual(result.returncode, -signal.SIGKILL)
            store = MockStore(path)
            self.assertTrue(store.check_fence("ALP-03", 1))
            self.assertEqual(store.claim("ALP-03", "recovery-worker", recover=True), 2)
            self.assertFalse(store.check_fence("ALP-03", 1))
            self.assertTrue(store.check_fence("ALP-03", 2))
            self.assertEqual(store.count_effects(), 0)
            store.close()

    def test_t3_sigkill_after_mock_external_effect_has_no_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mock.sqlite"
            result = subprocess.run([sys.executable, str(HERE / "harness.py"), "crash", str(path), "after_remote_effect"], cwd=HERE, capture_output=True, check=False)
            self.assertEqual(result.returncode, -signal.SIGKILL)
            store = MockStore(path)
            self.assertEqual(store.count_effects(), 1)
            store.claim("ALP-03", "recovery-worker", recover=True)
            store.enqueue_once("mock-pr-001", "fixture payload")
            store.deliver_pending()
            store.deliver_pending()
            self.assertEqual(store.count_effects(), 1)
            self.assertEqual(store.db.execute("SELECT delivered FROM outbox").fetchone()[0], 1)
            store.close()

    def test_t4_mock_platform_denies_merge_and_close(self) -> None:
        platform = MockPlatform()
        self.assertEqual(platform.command("start"), "COMPLETED")
        for command in ("merge", "close", "next_task", "repair", "assign_canonical_state"):
            with self.subTest(command=command):
                with self.assertRaises(PermissionError):
                    platform.command(command)

    def test_t5_duplicate_failure_escalates_before_budget(self) -> None:
        self.assertEqual(repair_decision(past_fingerprints={"same"}, fingerprint="same", repair_count=0), "ESCALATED:REPEATED_FAILURE")
        self.assertEqual(repair_decision(past_fingerprints=set(), fingerprint="new", repair_count=2), "ESCALATED:REPAIR_LIMIT")
        self.assertEqual(repair_decision(past_fingerprints=set(), fingerprint="new", repair_count=1), "RETRY")

    def test_t5_stop_requires_ack(self) -> None:
        self.assertEqual(stop_decision(acknowledged=False), ("RUNNING", "STOP_PENDING"))
        self.assertEqual(stop_decision(acknowledged=True), ("BLOCKED", "OWNER_STOP"))


if __name__ == "__main__":
    unittest.main()
