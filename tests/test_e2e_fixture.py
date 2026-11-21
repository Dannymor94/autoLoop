"""Fail CI if the frozen real-world smoke fixture silently drifts."""

from __future__ import annotations

import hashlib
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "pilot" / "e2e"


class E2EFixtureTests(unittest.TestCase):
    def test_frozen_spec_digest(self) -> None:
        manifest = yaml.safe_load((FIXTURE / "manifest.yaml").read_text(encoding="utf-8"))
        digest = hashlib.sha256((FIXTURE / manifest["source_spec"]).read_bytes()).hexdigest()
        self.assertEqual(digest, manifest["acceptance_spec_sha256"])
        self.assertTrue(manifest["forbid_implicit_pass"])
        self.assertTrue(manifest["forbid_merge_or_close"])

    def test_complete_and_bounded_smoke_contract(self) -> None:
        manifest = yaml.safe_load((FIXTURE / "manifest.yaml").read_text(encoding="utf-8"))
        self.assertEqual(manifest["run_modes"], ["normal", "kill_after_claim_before_start", "kill_during_implementation", "kill_after_process_exit_before_sqlite_commit", "kill_after_push_before_pr"])
        self.assertEqual(len(set(manifest["required_artifacts"])), len(manifest["required_artifacts"]))
        for item in ("pr_url_and_number", "tested_tree_sha", "ci_run_url_and_conclusion", "independent_qa_verdict_with_session_id", "qa_push_denial_with_os_identity", "raw_attempt_jsonl_and_fsync_receipt", "sqlite_event_log_and_fencing_tokens"):
            self.assertIn(item, manifest["required_artifacts"])
        self.assertEqual(manifest["pass_rule"], "ALL_ARTIFACTS_PRESENT_AND_IDENTITIES_MATCH")

    def test_four_kill_points_have_frozen_recovery_expectations(self) -> None:
        manifest = yaml.safe_load((FIXTURE / "manifest.yaml").read_text(encoding="utf-8"))
        points = manifest["kill_points"]
        self.assertEqual([item["id"] for item in points], ["K1_AFTER_CLAIM_BEFORE_START", "K2_DURING_AGENT", "K3_AFTER_EXIT_BEFORE_DB", "K4_AFTER_PUSH_BEFORE_PR"])
        self.assertEqual(len({item["inject"] for item in points}), 4)
        for item in points:
            self.assertTrue(item["expected_state"])
            self.assertTrue(item["required_invariant"])


if __name__ == "__main__":
    unittest.main()
