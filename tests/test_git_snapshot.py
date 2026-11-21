"""Worktree identity must reject modifications invisible to HEAD alone."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autoloop.git_snapshot import (  # noqa: E402
    GitSnapshotError,
    OwnerInterventionDetected,
    capture_git_snapshot,
    require_snapshot_match,
)


class GitSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "Fixture")
        (self.repo / "tracked.txt").write_text("baseline\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-qm", "baseline")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def git(self, *args: str) -> str:
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True, text=True).stdout.strip()

    def test_clean_checkpoint_preserves_real_index(self) -> None:
        baseline = capture_git_snapshot(self.repo)
        self.assertEqual(baseline.head_sha, self.git("rev-parse", "HEAD"))
        self.assertEqual(baseline.dirty_tree_sha, self.git("rev-parse", "HEAD^{tree}"))
        self.assertEqual(require_snapshot_match(self.repo, baseline), baseline)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_modified_file_triggers_owner_intervention_without_head_change(self) -> None:
        baseline = capture_git_snapshot(self.repo)
        (self.repo / "tracked.txt").write_text("changed outside agent\n", encoding="utf-8")
        self.assertEqual(baseline.head_sha, self.git("rev-parse", "HEAD"))
        with self.assertRaisesRegex(OwnerInterventionDetected, "OWNER_INTERVENTION"):
            require_snapshot_match(self.repo, baseline)

    def test_untracked_file_and_deletion_trigger_intervention(self) -> None:
        baseline = capture_git_snapshot(self.repo)
        (self.repo / "new.txt").write_text("new\n", encoding="utf-8")
        with self.assertRaises(OwnerInterventionDetected):
            require_snapshot_match(self.repo, baseline)
        (self.repo / "new.txt").unlink()
        (self.repo / "tracked.txt").unlink()
        with self.assertRaises(OwnerInterventionDetected):
            require_snapshot_match(self.repo, baseline)

    def test_real_index_stays_unchanged_even_when_staged_content_differs(self) -> None:
        (self.repo / "tracked.txt").write_text("staged\n", encoding="utf-8")
        self.git("add", "tracked.txt")
        index_before = self.git("ls-files", "-s")
        snapshot = capture_git_snapshot(self.repo)
        self.assertNotEqual(snapshot.dirty_tree_sha, self.git("rev-parse", "HEAD^{tree}"))
        self.assertEqual(self.git("ls-files", "-s"), index_before)

    def test_non_repository_fails_closed(self) -> None:
        with self.assertRaises(GitSnapshotError):
            capture_git_snapshot(Path(self.temp.name))


if __name__ == "__main__":
    unittest.main()
