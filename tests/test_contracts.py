"""Machine-generated positive/negative transition checks from states.yaml."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from contract_data import load_contracts  # noqa: E402
from state_machine import TransitionRejected, transition_target  # noqa: E402
from validate_contracts import validate_contracts  # noqa: E402


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contracts = load_contracts(ROOT)
        cls.states = cls.contracts["states"]

    def test_normative_contracts_pass(self) -> None:
        validate_contracts(self.contracts)

    def test_every_declared_transition_with_all_guards_passes(self) -> None:
        for item in self.states["transitions"]:
            with self.subTest(item=item["event"], source=item["from"]):
                self.assertEqual(
                    transition_target(self.states, current_state=item["from"], event=item["event"], satisfied_guards=set(item["guards"])),
                    item["to"],
                )

    def test_every_undeclared_state_event_pair_is_rejected(self) -> None:
        events = {t["event"] for t in self.states["transitions"]}
        declared = {(t["from"], t["event"]) for t in self.states["transitions"]}
        for state in self.states["states"]:
            for event in events:
                if (state, event) in declared:
                    continue
                with self.subTest(state=state, event=event):
                    with self.assertRaises(TransitionRejected):
                        transition_target(self.states, current_state=state, event=event, satisfied_guards=events)

    def test_every_required_guard_is_enforced(self) -> None:
        for item in self.states["transitions"]:
            for missing in item["guards"]:
                with self.subTest(event=item["event"], missing=missing):
                    with self.assertRaises(TransitionRejected):
                        transition_target(
                            self.states,
                            current_state=item["from"],
                            event=item["event"],
                            satisfied_guards=set(item["guards"]) - {missing},
                        )

    def test_platform_completion_cannot_make_done(self) -> None:
        with self.assertRaises(TransitionRejected):
            transition_target(self.states, current_state="RUNNING", event="FINALIZE_MERGE", satisfied_guards={"auto_loop_merge_confirmed", "exact_evidence_still_valid", "target_ref_confirmed"})

    def test_owner_stop_must_be_acknowledged(self) -> None:
        with self.assertRaises(TransitionRejected):
            transition_target(self.states, current_state="RUNNING", event="OWNER_STOP_CONFIRMED", satisfied_guards={"checkpoint_recorded", "block_reason_owner_stop"})


if __name__ == "__main__":
    unittest.main()
