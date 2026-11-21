# autoLoop v0.4.2 — efficiency-first measurement gates

**Owner acceptance:** 2026-11-20. **Status:** specification only. The actual
Mac subscription Smoke A, end-to-end Smoke B, and economic experiment are **NOT
TESTED**. This document adds deterministic economics and observability to the
approved [v0.4.1](PLAN_V0.4.1.md); it does not replace that plan's execution
order or authorize a merge.

## 1. Decision principle and remaining-cost accounting

Every feature must show an evidence-backed path to more independently accepted
tasks, less active owner time, or lower risk. Security and evidence gates are
non-negotiable and cannot be traded away for apparent efficiency. This owner
principle is recorded outside the contract-generated block of `AGENTS.md`.

Treat already completed prototype work, including the older 79-test snapshot,
as **sunk cost**, not as remaining implementation effort. For the decision to
continue, count only measured or explicitly estimated hours **remaining** to
Smoke B, ongoing maintenance, incremental spend and scarce subscription
capacity. Do not claim a revised break-even task count until these inputs have
been measured. Formula and decision log: [ECONOMICS.md](ECONOMICS.md).

## 2. Executable acceptance and stopping telemetry

- Each evaluation task must include explicit, versioned executable acceptance
  commands, expected outcomes and an acceptance specification SHA. Prose alone
  cannot certify PASS. Existing `pilot/e2e/ACCEPTANCE.md` includes an executable
  test command and remains frozen; do not change its hash to retrofit metrics.
- The eventual wrapper enforces an externally configured wall-clock deadline,
  termination grace period and SIGKILL of the entire attempt process group if
  needed. Use an installed CLI's supported maximum-turn flag (Claude Code's
  `--max-turns` where verified). Do not assume Codex has an equivalent flag;
  enforce the portable external timeout in every case.
- Compute `termination_lag_observed = last_agent_turn - first_observed_pass_turn`
  using **only** parsed structured tool events, acceptance command results and
  recorded Git tree identities. A tool's reported success does not establish
  PASS unless the complete acceptance suite passed for that exact tree.
- The JSONL transcript alone cannot reveal the first passing turn if no
  acceptance check was executed then. In that case record `UNKNOWN`, not zero.
  If checking intermediate states, use isolated writable copies or reproducible
  snapshots, never modify the active or read-only QA worktree. The probe's own
  runtime and expense are measured: excessive probing can negate savings.
- On limit exhaustion, stop safely and seal logs/checkpoints; no automatic
  paid API fallback or unbounded self-review loop. A forced stop is not QA PASS.

## 3. Subscription-only billing gate (Smoke A)

`subscription_only` must be enforced by the wrapper, not just mentioned in a
prompt or a policy document. For each attempted launch:

1. Construct an explicit child environment without `ANTHROPIC_API_KEY`,
   `OPENAI_API_KEY` and other known API-key/provider override variables. Preserve
   necessary login environment and avoid logging environment secrets.
2. Inspect **effective** Claude settings, including applicable managed/user/
   project/local files and overrides; reject `apiKeyHelper` or a paid-provider
   selection. Unknown precedence, unreadable settings or ambiguous auth is
   fail-closed.
3. Run CLI-supported read-only auth checks (for example, Claude authentication
   status and Codex login status). Verify that each CLI is using its own
   subscriber's intended login, **not** API-key credentials. Login presence
   alone is not adequate proof of the billing mode.
4. If subscribed auth cannot be positively established, do not spawn the
   attempt. Record `BLOCKED(reason=BILLING_MODE)` via an **existing valid**
   state transition or design and approve the required contract guard first.
   Never directly mutate the canonical state to bypass `states.yaml`.

Smoke A must include separate positive subscription-logins and negative cases:
injected environment API key, configured `apiKeyHelper`, paid-provider config,
unknown status, wrong OS login and CLI setting precedence. Do not read, copy,
publish or intermediate OAuth/session tokens. Capture only safe redacted
evidence. This is a **planned gate**, not an implemented security guarantee.

## 4. Measured QA recall on injected known defects (H3)

Economic experiment B includes a preregistered subset of tasks with known
defects (mutations or explicit acceptance violations). Record each defect ID,
the baseline, expected detection and gold outcome **outside QA context**.
Codex receives only the task's legitimate acceptance and the candidate diff,
with a fresh read-only checkout, not the injected-defect answer key.

Measure `QA_recall = independently_confirmed_defects_detected /
independently_confirmed_seeded_defects` and false positives separately. Do not
count unsupported model assertions or intentionally trivial bait as proof of
production QA quality. The quality gate remains mandatory for normal tasks.

## 5. Owner activity and economic experiment (H1/H2/H4)

Capture owner-active periods through an append-only timestamped ledger:
`al time start <task_id>` and `al time stop <task_id>` in the **manual and
autoLoop arms**, including time spent reviewing reports, approvals and
interventions. Idempotent start/stop with explicit correction events are
required before economic PASS. In autoLoop mode additionally count issue
commands, approvals, comments and `OWNER_INTERVENTION` from event logs.
Event counts alone cannot be converted to minutes. Track passive wait
separately. See [METRICS.md](METRICS.md).

After Smoke B passes, compare 12–20 preregistered, complexity-matched tasks
against the owner's present manual Claude/Codex/ChatGPT/GitHub workflow.
Alternate/counterbalance assignment to minimize learning and order effects;
evaluate both arms against the same quality criteria and record incomplete
tasks. The real goal is **accepted tasks per unit of owner time and scarce
subscription capacity**, not agent executions or PR count.

## 6. Preregistered continuation/freeze decision

Before experiment B, lock the dataset, definitions and threshold. Proposed
freeze rule: if `H1_owner_time_saving < 30%` **AND** the measured subscription
capacity consumed per accepted task is **not lower** than in the manual arm,
freeze further autoLoop feature development at the tested scope, retaining only
security and correctness fixes. If a required quantity is `UNKNOWN`, classify
the economics as `INCONCLUSIVE`, never synthesize a PASS or apply the rule as
if quota had been measured. Zero false SHA-bound PASS and zero unauthorized
merge are mandatory independent of economic result.

The 30% target is a **proposed predeclared decision threshold**, not observed
evidence or an industry benchmark. See [ECONOMICS.md](ECONOMICS.md).

## 7. Deterministic complexity classifier

The eventual task classification is a pure versioned function of validated
`task.yaml` fields: protected-path indicator/list, unique affected component
IDs/count, and migration indicator. No model, natural-language interpretation,
live Git scan, clock or mutable external state participates in classification.
Record input hash and classifier policy version with each decision.

The current `contracts/task.schema.json` does **not** define these fields.
Schema, generated documentation and policy changes require an explicit
protected-contract approval and tests before implementation. Proposed boundary
tests: 0/1/2/3 components, protected-path presence, migration presence,
missing fields, duplicate IDs, malformed values and conflicting indicators.
Missing/ambiguous metadata must block automated assignment or conservatively
escalate; never silently treat it as a simple task.

## 8. Execution order and explicit exclusions

1. Finish these non-executable specifications and verify docs generator drift.
2. **Smoke A:** subscription auth and `BILLING_MODE` negatives under launchd;
   run actual CLI flag/version preflight without paid-model fallback.
3. Wrapper / isolated QA / publisher per v0.4.1. Add the bounded stopping and
   measured acceptance checkpoints without undermining crash recovery.
4. **Smoke B:** frozen end-to-end plus four crash-injection gates; acceptance
   fixture SHA and required artifacts remain unchanged.
5. **Economic experiment B:** collect paired tasks and predeclared metrics;
   make the CONTINUE/FREEZE/INCONCLUSIVE decision from the event ledger.
6. Only then build mobile GitHub command ergonomics and optional optimizations.

No vendor login, process isolation, rule-set change, paid call, actual Mac test,
GitHub push or automatic merge is represented as completed by this document.
