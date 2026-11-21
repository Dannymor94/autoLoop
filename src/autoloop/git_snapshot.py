"""Deterministic Git-visible worktree identity using an isolated temporary index.

The canonical Git index is never modified. Capture only at a quiescent runner
checkpoint: Git does not provide an atomic filesystem snapshot during writes.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory


class GitSnapshotError(RuntimeError):
    """A worktree cannot be trusted as a stable checkpoint."""


class OwnerInterventionDetected(GitSnapshotError):
    """The checkpoint no longer matches the Git-visible worktree."""


@dataclass(frozen=True)
class GitSnapshot:
    head_sha: str
    dirty_tree_sha: str


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise GitSnapshotError(f"GIT_SNAPSHOT_FAILED:{' '.join(args)}") from exc
    return completed.stdout.strip()


def capture_git_snapshot(worktree: Path) -> GitSnapshot:
    """Hash tracked and non-ignored untracked content without touching .git/index.

    `git add -A` observes Git-visible changes only: ignored files and content
    inside submodules are outside this identity and need separate controls.
    """
    repo = worktree.resolve(strict=True)
    if not repo.is_dir() or Path(_git(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
        raise GitSnapshotError("WORKTREE_ROOT_REQUIRED")
    original_head = _git(repo, "rev-parse", "HEAD")
    with TemporaryDirectory(prefix="autoloop-git-index-") as directory:
        env = dict(os.environ)
        env["GIT_INDEX_FILE"] = str(Path(directory) / "index")
        # Starting from HEAD ensures that staged files in the real index have
        # no effect, and that tracked deletions are represented correctly.
        _git(repo, "read-tree", "HEAD", env=env)
        _git(repo, "add", "-A", "--", ":/", env=env)
        tree = _git(repo, "write-tree", env=env)
    if _git(repo, "rev-parse", "HEAD") != original_head:
        raise GitSnapshotError("HEAD_CHANGED_DURING_SNAPSHOT")
    if len(tree) not in (40, 64) or any(ch not in "0123456789abcdef" for ch in tree):
        raise GitSnapshotError("INVALID_TREE_OID")
    return GitSnapshot(head_sha=original_head, dirty_tree_sha=tree)


def require_snapshot_match(worktree: Path, checkpoint: GitSnapshot) -> GitSnapshot:
    """Fail closed before Resume and before the independent QA gate."""
    observed = capture_git_snapshot(worktree)
    if observed != checkpoint:
        raise OwnerInterventionDetected("OWNER_INTERVENTION")
    return observed
