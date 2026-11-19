"""Stable hashes only; no automatic QA verdict, merge or runner operation."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


_NORMALIZED_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_.:-]*$")


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256_canonical(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def suite_fingerprint(
    *,
    check_commands: list[str],
    lockfile_sha256_by_path: dict[str, str],
    ci_workflow_sha256_by_path: dict[str, str],
    tool_versions: dict[str, str],
) -> str:
    """Versioned interface: SHA-256 canonical JSON of actual CI input artifacts."""
    return sha256_canonical(
        {
            "check_commands": check_commands,
            "lockfile_sha256_by_path": lockfile_sha256_by_path,
            "ci_workflow_sha256_by_path": ci_workflow_sha256_by_path,
            "tool_versions": tool_versions,
        }
    )


def evidence_key(
    *,
    project_id: str,
    task_id: str,
    acceptance_spec_hash: str,
    head_sha: str,
    base_sha: str,
    tested_tree_sha: str,
    suite_fingerprint: str,
) -> str:
    return sha256_canonical(
        {
            "project_id": project_id,
            "task_id": task_id,
            "acceptance_spec_hash": acceptance_spec_hash,
            "head_sha": head_sha,
            "base_sha": base_sha,
            "tested_tree_sha": tested_tree_sha,
            "suite_fingerprint": suite_fingerprint,
        }
    )


def failure_fingerprint(
    *, sorted_failed_test_node_ids: list[str], normalized_error_code: str, failure_stage: str
) -> str:
    """Callers must supply a stable error *code*, not log text or an LLM summary."""
    if not _NORMALIZED_ERROR_CODE.fullmatch(normalized_error_code):
        raise ValueError("normalized_error_code must be a stable uppercase machine code")
    if not failure_stage or not re.fullmatch(r"[A-Z][A-Z0-9_]*", failure_stage):
        raise ValueError("failure_stage must be a stable uppercase stage code")
    if not sorted_failed_test_node_ids or sorted_failed_test_node_ids != sorted(
        set(sorted_failed_test_node_ids)
    ):
        raise ValueError("failed test node IDs must be nonempty, sorted and unique")
    return sha256_canonical(
        {
            "sorted_failed_test_node_ids": sorted_failed_test_node_ids,
            "normalized_error_code": normalized_error_code,
            "failure_stage": failure_stage,
        }
    )
