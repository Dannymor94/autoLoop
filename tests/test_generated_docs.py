from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generate_agent_docs import BEGIN, END, check_or_write  # noqa: E402


class AgentDocsTests(unittest.TestCase):
    def test_repository_docs_in_sync(self) -> None:
        self.assertEqual(check_or_write(ROOT, check=True), [])

    def test_preserves_unmarked_custom_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copytree(ROOT / "contracts", root / "contracts")
            (root / "AGENTS.md").write_text("# AGENTS.md\n\nMy custom instructions stay.\n", encoding="utf-8")
            check_or_write(root, check=False)
            existing = (root / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("My custom instructions stay.", existing)
            self.assertEqual(existing.count(BEGIN), 1)
            self.assertEqual(existing.count(END), 1)
            self.assertEqual(check_or_write(root, check=True), [])

    def test_modified_contract_causes_ci_drift_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copytree(ROOT / "contracts", root / "contracts")
            check_or_write(root, check=False)
            original = (root / "contracts" / "limits.yaml").read_text(encoding="utf-8")
            (root / "contracts" / "limits.yaml").write_text(original.replace("max_repair_cycles: 2", "max_repair_cycles: 3"), encoding="utf-8")
            self.assertEqual(set(check_or_write(root, check=True)), {"AGENTS.md", "CLAUDE.md"})

    def test_duplicate_markers_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copytree(ROOT / "contracts", root / "contracts")
            (root / "AGENTS.md").write_text(f"{BEGIN}\n{END}\n{BEGIN}\n{END}", encoding="utf-8")
            with self.assertRaises(ValueError):
                check_or_write(root, check=False)


if __name__ == "__main__":
    unittest.main()
