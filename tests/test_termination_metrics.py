from __future__ import annotations

import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autoloop.termination_metrics import observed_termination_lag  # noqa: E402


class TerminationMetricsTests(unittest.TestCase):
    def test_observed_pass_and_final_step(self):
        events = [
            {"type": "agent.step", "agent_step": 1},
            {"type": "acceptance.checked", "agent_step": 3, "pass": True, "tested_tree_sha": "a"*40, "suite_fingerprint": "b"*64, "trusted_verifier": True},
            {"type": "agent.step", "agent_step": 8},
        ]
        self.assertEqual(observed_termination_lag(events), {"first_observed_pass_step": 3, "final_step": 8, "termination_lag_observed": 5})

    def test_no_check_never_claims_zero_lag(self):
        self.assertIsNone(observed_termination_lag([{"type": "agent.step", "agent_step": 8}])["termination_lag_observed"])

    def test_untrusted_agent_claim_is_not_acceptance(self):
        events = [{"type": "acceptance.checked", "agent_step": 1, "pass": True, "tested_tree_sha": "a"*40, "suite_fingerprint": "b"*64, "trusted_verifier": False}]
        self.assertIsNone(observed_termination_lag(events)["first_observed_pass_step"])

    def test_bad_sha_or_regressing_steps_are_unknown(self):
        self.assertIsNone(observed_termination_lag([{"type": "acceptance.checked", "agent_step": 1, "pass": True, "tested_tree_sha": "bad", "suite_fingerprint": "b"*64, "trusted_verifier": True}])["termination_lag_observed"])
        self.assertIsNone(observed_termination_lag([{"type": "agent.step", "agent_step": 5}, {"type": "agent.step", "agent_step": 3}])["final_step"])


if __name__ == "__main__":
    unittest.main()
