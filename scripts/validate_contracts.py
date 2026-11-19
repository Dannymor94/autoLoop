"""Fail-closed invariant checks for initial autoLoop contract definitions."""

from __future__ import annotations

from collections import deque

from contract_data import ROOT, load_contracts


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_contracts(c: dict) -> None:
    machine = c["states"]
    states = machine["states"]
    transitions = machine["transitions"]
    require(machine["version"] == 1, "unsupported states version")
    require(machine["initial_state"] == "READY", "initial state must be READY")
    require(
        set(states) == {"READY", "RUNNING", "VERIFYING", "MERGING", "DONE", "BLOCKED", "ESCALATED", "SUPERSEDED"},
        "canonical state enum changed: requires explicit ADR and tests",
    )
    require(all(isinstance(record["terminal"], bool) for record in states.values()), "state terminal metadata invalid")
    require(states["DONE"]["terminal"] and states["SUPERSEDED"]["terminal"], "terminal states must be final")
    require(all(not record["terminal"] for name, record in states.items() if name not in ("DONE", "SUPERSEDED")), "only DONE and SUPERSEDED may be terminal")

    seen: set[tuple[str, str]] = set()
    graph: dict[str, set[str]] = {name: set() for name in states}
    for t in transitions:
        src, dst, event, guards = t["from"], t["to"], t["event"], t["guards"]
        require(src in states and dst in states, f"unknown state in {t}")
        require(not states[src]["terminal"], f"terminal state {src} has outgoing transition")
        require(isinstance(event, str) and event and event == event.upper(), f"invalid event in {t}")
        require(isinstance(guards, list) and bool(guards) and len(guards) == len(set(guards)), f"invalid guards in {t}")
        require((src, event) not in seen, f"non-deterministic transition: {src}/{event}")
        seen.add((src, event))
        graph[src].add(dst)

    reached = {machine["initial_state"]}
    queue = deque(reached)
    while queue:
        for dst in graph[queue.popleft()]:
            if dst not in reached:
                reached.add(dst)
                queue.append(dst)
    require(reached == set(states), f"unreachable canonical states: {set(states) - reached}")

    index = {(t["from"], t["event"]): t for t in transitions}
    required = {
        ("RUNNING", "OWNER_STOP_CONFIRMED"): ("BLOCKED", {"runner_stop_confirmed", "block_reason_owner_stop", "checkpoint_recorded"}),
        ("BLOCKED", "RESUME_OWNER_STOP"): ("READY", {"block_reason_owner_stop", "runner_stop_confirmed", "no_active_lease", "dependencies_done"}),
        ("VERIFYING", "QA_AND_CI_PASS"): ("MERGING", {"head_sha_current", "base_sha_current", "tested_tree_sha_current", "acceptance_spec_current", "suite_fingerprint_current", "independent_qa_pass", "ci_success", "merge_policy_allows"}),
        ("MERGING", "FINALIZE_MERGE"): ("DONE", {"auto_loop_merge_confirmed", "exact_evidence_still_valid", "target_ref_confirmed"}),
        ("MERGING", "MERGE_EVIDENCE_STALE"): ("VERIFYING", {"merge_not_started", "old_evidence_revoked"}),
        ("BLOCKED", "MERGE_RECONCILED"): ("MERGING", {"previously_in_merging", "merge_reconciliation_complete", "no_duplicate_side_effect", "prior_qa_pass_still_valid", "exact_evidence_still_valid"}),
        ("VERIFYING", "REPEATED_FAILURE"): ("ESCALATED", {"duplicate_failure_fingerprint"}),
        ("VERIFYING", "REPAIR_LIMIT"): ("ESCALATED", {"repair_budget_exhausted"}),
        ("VERIFYING", "INVALIDATE_EVIDENCE"): ("VERIFYING", {"old_evidence_revoked"}),
    }
    for selector, (target, guard_set) in required.items():
        t = index.get(selector)
        require(t is not None and t["to"] == target and guard_set.issubset(t["guards"]), f"security-critical transition violated: {selector}")

    # A platform may never move a task directly to DONE, and an executor event
    # is not proof of a final QA or merge decision.
    require(all(t["from"] == "MERGING" for t in transitions if t["to"] == "DONE"), "DONE bypasses merge gate")
    require(all(
        (t["from"] == "VERIFYING" and t["event"] == "QA_AND_CI_PASS")
        or (t["from"] == "BLOCKED" and t["event"] == "MERGE_RECONCILED")
        for t in transitions if t["to"] == "MERGING"
    ), "MERGING bypasses QA gate/reconciliation")
    require(not any(t["from"] == "RUNNING" and t["to"] == "DONE" for t in transitions), "RUNNING must not finalize")

    limits = c["limits"]
    require(limits["version"] == 1 and limits["repair"]["max_repair_cycles"] >= 0, "invalid repair limit")
    require(limits["repair"]["escalate_on_repeated_failure_fingerprint"] is True, "duplicate failure escalation disabled")
    require(0 < limits["context"]["checkpoint_suggest_percent"] < limits["context"]["prepare_new_session_percent"] <= 100, "invalid context thresholds")
    require(limits["dispatcher"]["max_writers"] == 1 and limits["runner"]["max_parallel_attempts_per_task"] == 1, "MVP is single writer, single attempt")

    policies = c["policies"]
    require(policies["canonical_state_owner"] == "autoLoop", "platform cannot own canonical state")
    executor = policies["executor"]
    for key in ("platform_auto_merge", "platform_auto_close", "platform_claim_next_task", "platform_repair_retry", "platform_can_assign_canonical_state", "platform_has_merge_credentials"):
        require(executor[key] is False, f"executor privilege enabled: {key}")
    require(policies["storage"]["backend"] == "sqlite" and policies["storage"]["database_writers"] == 1, "MVP storage must have one writer")
    qa = policies["qa"]
    for key in ("independent_fresh_session", "read_only_source_tree", "require_exact_head_sha", "require_exact_base_sha", "require_tested_tree_sha", "require_suite_fingerprint"):
        require(qa[key] is True, f"QA guard disabled: {key}")
    require(qa["can_push_to_github"] is False and qa["can_access_developer_reasoning"] is False, "QA has forbidden privileges")
    require(policies["merge"]["only_actor"] == "autoLoop" and policies["merge"]["require_fresh_ci"] and policies["merge"]["require_independent_qa_pass"], "merge bypass permitted")
    require(policies["owner_stop"]["confirmed_block_reason"] == "OWNER_STOP", "Stop resolution contract broken")
    require(policies["browser_bridge"]["read_assistant_replies"] is False, "browser bridge must be delivery-only")

    protected = c["protected_paths"]
    require(protected["policy"] == "explicit_owner_approval_before_modification_or_merge", "protected path approval removed")
    require({"contracts/**", ".github/workflows/**", "AGENTS.md", "CLAUDE.md"}.issubset(set(protected["paths"])), "critical protected paths missing")

    for key in ("task", "runner_events", "evidence", "report"):
        schema = c[key]
        require(schema["$schema"].endswith("2020-12/schema") and schema["type"] == "object", f"invalid {key} JSON schema")
        require(len(schema["required"]) == len(set(schema["required"])), f"duplicate required fields in {key}")
        require(set(schema["required"]).issubset(schema["properties"]), f"undefined required field in {key}")

    require({"head_sha", "base_sha", "tested_tree_sha", "suite_fingerprint", "evidence_key", "ci_success", "independent_qa_verdict"}.issubset(c["evidence"]["required"]), "evidence identity incomplete")
    require({"attempt_id", "tests", "tokens", "base_sha"}.issubset(c["report"]["required"]), "report fields incomplete")


def main() -> int:
    validate_contracts(load_contracts(ROOT))
    print("Contracts validated: deterministic state graph and critical ownership guards OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
