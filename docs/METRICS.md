# autoLoop v0.4.2 — measurement protocol

**State:** planned; telemetry hooks and `al time` commands are **not yet
implemented**. No model may synthesize missing usage or infer owner time
from the presence of a GitHub comment.

## Event ledger and normalization

Every recorded datum is immutable/event-sourced with UTC timestamp,
`task_id`, `attempt_id` (if applicable), event ID, actor, data source and
`source_sha`/Git tree SHA where relevant. Corrections append compensating
events with explicit reasons; do not rewrite historical durations. Collapse
duplicate event IDs idempotently. Keep model outputs distinct from trusted
CI/wrapper/owner-originated records.

| Field | Source of truth | Rule for `UNKNOWN` |
| --- | --- | --- |
| `accepted` | Exact-SHA CI PASS + independent QA PASS + owner-acceptance event | Not PASS if any evidence is missing |
| `owner_active_seconds` | Paired `al time start/stop <task_id>` events in both manual and autoLoop modes | Missing start/stop → `UNKNOWN`; no estimated minutes |
| `owner_actions` | Audited issue approvals, comments, command and intervention events | Counts are not duration |
| `elapsed_seconds` | Durable task-start and end timestamps | Missing clock endpoint → `UNKNOWN` |
| `claude_reported_tokens` | Authenticated Claude JSONL usage event | No usage event → `UNKNOWN` |
| `codex_reported_tokens` | Authenticated Codex JSONL usage event | No usage event → `UNKNOWN` |
| `subscription_quota_consumed` | Explicit subscription/account meter reading with timestamp and provider | No meter or contaminated observation → `UNKNOWN`; tokens are not the same as quota |
| `repair_cycles` | autoLoop canonical state transition/event log | Missing interval → `UNKNOWN` |
| `ci_minutes` | GitHub run/job billing or duration data | No trusted run/billing data → `UNKNOWN` |
| `external_spend` | Provider billing evidence | Unavailable billing data → `UNKNOWN`, not zero |
| `qa_seeded_recall` | Independently checked mutant gold set and QA findings | No seeded cases → `NOT_APPLICABLE` |
| `termination_lag_observed` | First verified passing acceptance tree/turn and final agent turn | No intermediate verified PASS/tree linkage → `UNKNOWN` |

Owner timers: only the owner creates time-start/stop records, including manual
mode. Track task switches, accidental open timers, overlaps and corrections
explicitly. Multiple overlapping intervals count once for **total owner
wall-active time**, and task allocation is separately reported rather than
silently double-counting cross-task work.

## Acceptance event and lag definition

For a `first_observed_pass_turn` to exist:

1. All required executable acceptance commands succeed against one identified
   Git tree SHA, with the same spec/commands fingerprint and clean staged
   dependencies; do not accept agent prose claiming the tests passed.
2. A timestamped, monotonic agent turn/step number is reproducibly mapped to
   that snapshot via structured logs and tree-checkpoint events.
3. The verifier runs with isolation; tests cannot mutate the developer's
   worktree or the QA source worktree. Failure to prove isolation gives no
   valid PASS.

Compute `lag = final_agent_turn - first_observed_pass_turn`, where both
integers come from the same attempt. This is **observed lag**, not proof of
the earliest theoretically correct patch. A final-only test run yields
`UNKNOWN`, not zero. Report optional `probe_overhead_seconds` separately.

Before implementing probes, benchmark whether their incremental compute/CI
cost exceeds the savings that earlier stops could provide. Store the test
runner/environment fingerprint with every PASS.

## Deterministic task class (future contract change)

`classify(version, protected_path_flag, component_id_set, migration_flag)` is
a pure function over validated `task.yaml` data. Its output and fingerprint
are reproducible. The current task schema lacks these inputs: do not guess
them from descriptions. A separate explicitly approved contract patch is
needed. Tests must cover boundaries, missing and conflicting metadata.

## Economic report statuses

- `CONTINUE`: preregistered gates and measured gain justify next stage.
- `FREEZE`: measured stop condition holds; only safety/correctness changes.
- `INCONCLUSIVE`: required evidence absent, partial, or incomparable.

`INCONCLUSIVE` must never be reported as success. Economic reports are
snapshots of a specified dataset SHA and measurement-definition version.
