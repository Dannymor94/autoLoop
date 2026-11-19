from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from evidence_contract import evidence_key, failure_fingerprint, suite_fingerprint  # noqa: E402


class EvidenceKeyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.kw = dict(project_id="demo", task_id="AL-001", acceptance_spec_hash="a" * 64, head_sha="b" * 40, base_sha="c" * 40, tested_tree_sha="d" * 40, suite_fingerprint="e" * 64)

    def test_repeatable(self) -> None:
        self.assertEqual(evidence_key(**self.kw), evidence_key(**self.kw))

    def test_changed_base_invalidates_pass_key(self) -> None:
        changed = dict(self.kw, base_sha="f" * 40)
        self.assertNotEqual(evidence_key(**self.kw), evidence_key(**changed))

    def test_changed_head_invalidates_pass_key(self) -> None:
        changed = dict(self.kw, head_sha="f" * 40)
        self.assertNotEqual(evidence_key(**self.kw), evidence_key(**changed))

    def test_changed_tested_tree_invalidates_pass_key(self) -> None:
        changed = dict(self.kw, tested_tree_sha="f" * 40)
        self.assertNotEqual(evidence_key(**self.kw), evidence_key(**changed))

    def test_changed_suite_invalidates_pass_key(self) -> None:
        changed = dict(self.kw, suite_fingerprint="f" * 64)
        self.assertNotEqual(evidence_key(**self.kw), evidence_key(**changed))

    def test_suite_fingerprint_depends_on_lockfile_and_workflow(self) -> None:
        source = dict(check_commands=["python -m unittest"], lockfile_sha256_by_path={"requirements-dev.txt": "a" * 64}, ci_workflow_sha256_by_path={".github/workflows/contracts-check.yml": "b" * 64}, tool_versions={"python": "3.12"})
        self.assertNotEqual(suite_fingerprint(**source), suite_fingerprint(**dict(source, ci_workflow_sha256_by_path={".github/workflows/contracts-check.yml": "c" * 64})))
        self.assertNotEqual(suite_fingerprint(**source), suite_fingerprint(**dict(source, lockfile_sha256_by_path={"requirements-dev.txt": "d" * 64})))

    def test_failure_fingerprint_repeatable_regardless_of_attempt(self) -> None:
        failure = dict(sorted_failed_test_node_ids=["tests/test_a.py::test_b"], normalized_error_code="ASSERTION_ERROR", failure_stage="TEST")
        self.assertEqual(failure_fingerprint(**failure), failure_fingerprint(**failure))

    def test_failure_fingerprint_rejects_unstable_error_text(self) -> None:
        with self.assertRaises(ValueError):
            failure_fingerprint(sorted_failed_test_node_ids=["test_a"], normalized_error_code="Error at /tmp/random/123", failure_stage="TEST")


if __name__ == "__main__":
    unittest.main()
