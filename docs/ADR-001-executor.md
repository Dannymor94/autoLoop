# ADR-001 — Executor boundary and ownership

- **Status:** PROPOSED / executor selection PENDING (AL-005)
- **Date:** 2026-11-19
- **Decision owner:** autoLoop project owner
- **Acceptance gate:** AL-001–AL-005 pilot with binary evidence

## Context

Bernstein, Kandev and Cezar each contain some of their own scheduling, retries or task queues. Letting both a platform and autoLoop update the same canonical task state would produce races, duplicate attempts and un-auditable merges. autoLoop therefore acts as the sole authority for business state; a candidate platform is an executor of a single explicit attempt.

## Normative ownership matrix

| Function | One owner | Executor/API limitation |
| --- | --- | --- |
| Task queue, priority and dependency release | **autoLoop** | A platform may stage an accepted run only; no autonomous dispatch of the next task |
| Lease, fencing token, claim recovery | **autoLoop** | A platform sends observed PID/session/heartbeat, not canonical claims |
| Task retry and repair_count | **autoLoop** | Only transparent transport retries within the same attempt are permitted |
| Worktree creation and removal | **Executor platform** | autoLoop records path, branch, base/head SHA and verifies isolation |
| CLI process and session lifecycle | **Executor platform** | autoLoop issues start/stop/resume/compact commands via adapter |
| Task status in `states.yaml` | **autoLoop** | Platform-native run status is telemetry; it cannot change task state |
| QA evidence, failure fingerprint, PASS/FAIL | **autoLoop** | Platform may supply logs and CI links, never a final gate |
| GitHub merge and Issue/PR close | **autoLoop** | Disable platform auto-merge/auto-close and remove its merge/close credentials |
| Owner Stop/Resume and blocking reason | **autoLoop** | Stop only after observed acknowledgement; pending stop is a command receipt |
| Mobile controls and audit log | **autoLoop** | UI must use autoLoop APIs for all state-changing operations |
| Subscription usage reports | **Executor observes, autoLoop records** | Unknown quotas are `null`, not estimated as facts |

Everything described by `contracts/states.yaml` belongs exclusively to autoLoop. Platform-native queues, state stores or internal retries may exist for technical reasons only if they cannot bypass the above matrix. A candidate that requires its own autonomous queue, merge gate or task DONE cannot be used as the executor in this architecture.

## Exact-SHA QA gate

CI may run on a synthetic PR merge-ref, not just `head_sha`. Record `head_sha`, `base_sha`, `tested_tree_sha` and (if present) `tested_merge_sha`, plus command/lockfile/workflow/tool-version inputs. A PASS is invalidated by any relevant change. Before final merge, autoLoop re-reads the base SHA and rechecks the evidence. QA is independent and read-only, with a negative attempted-push test.

Fingerprint contracts:

```text
suite_fingerprint = sha256(canonical_json({
  check_commands, lockfile_sha256_by_path,
  ci_workflow_sha256_by_path, tool_versions
}))

evidence_key = sha256(canonical_json({
  project_id, task_id, acceptance_spec_hash,
  head_sha, base_sha, tested_tree_sha, suite_fingerprint
}))

failure_fingerprint = sha256(canonical_json({
  sorted_failed_test_node_ids, normalized_error_code, failure_stage
}))
```

Repeated failure fingerprint on a **different attempt of the same task** must immediately transition to `ESCALATED`, even if the repair limit remains. Normalized error codes must not contain stack addresses, timestamps or dynamic paths.

## Candidate comparison protocol

Use one dedicated disposable fixture repo and the same five scenario definitions for all three candidates. Do not use production repositories or user credentials in crash tests. Run real subscription-login tests only on a host the owner controls; no paid model API is assumed.

| Scenario | Acceptance evidence |
| --- | --- |
| T1: CLI subscription + PR | Both Claude Code and Codex subscription sessions work without API keys; SHA and CI proof |
| T2: identical deterministic plan twice | Byte-identical normalized state graph, zero LLM calls in coordination |
| T3: SIGKILL and recovery | No lost canonical state, duplicate claim or duplicate Git side effect |
| T4: disallowed platform merge/close | Platform cannot merge/close and cannot mark canonical DONE/MERGING, even after its own COMPLETED |
| T5: repair, repeated failure, Android | Configured limit, immediate duplicate escalation, mobile stop/resume/status |

Six binary selection criteria: (1) both subscription CLI logins; (2) deterministic transitions; (3) SIGKILL recovery; (4) sole autoLoop merge/close; (5) mobile management; (6) configured repair limit. **Criteria 2, 3 and 4 are mandatory.** A `NOT_TESTED` result does not count as PASS. Highest PASS count among eligible candidates wins; tie-break by lower privileges, fewer forks and simpler maintenance. If no candidate passes all mandatory criteria, make **no selection**.

## Decision log

| Candidate | 1 | 2 | 3 | 4 | 5 | 6 | Result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Bernstein | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | Pending |
| Kandev | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | Pending |
| Cezar | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | Pending |

Earlier successful **upstream project unit tests** do not count as candidate acceptance evidence. Once candidate logs and pilot fixture SHAs exist, link them here before changing `Status` to ACCEPTED.

## Deferred decisions

- SQLite/WAL + SQLAlchemy/Alembic will be used for the MVP single dispatcher writer; PostgreSQL only after a separate multi-host/multi-writer migration gate.
- Chipping Orchestrator is an **architectural reference only**, not a production dependency; dangerous permission bypass must never run on a host with personal data.
- Browser chat bridge only delivers an explicit addressed payload; it does not read replies or act as a scheduler.
- No irreversible `CANCELLED` state in the MVP. A confirmed owner Stop means `BLOCKED(reason=OWNER_STOP)`, then explicit Resume can return to READY.
