# AGENTS.md

Read this file before working in this repository.

## Owner's efficiency rule

Every new autoLoop feature must demonstrably do at least one of the following:
increase the number of independently accepted tasks, reduce the owner's active
time, or lower the risk of an incorrect or unsafe outcome. If none can be
measured or justified, defer the feature. Reliability and security gates must
never be weakened to improve throughput or apparent savings.

<!-- BEGIN AUTOLOOP-GENERATED RULES -->
## autoLoop contract rules (generated; do not edit this section)

Contract digest: `a295bf1032f9d8ff12aa397951c3791826e3a5278e0d950dfe89751d1a90fc75`. Source of truth: `contracts/`.

### Ownership and security

- autoLoop owns queue, leases, fencing, canonical task state, repair counts, QA verdicts and merge/close.
- The OSS platform executes only one expressly requested attempt; its run completion does not mean task DONE.
- Never auto-merge, auto-close, claim another task or run an autonomous repair loop from an executor.
- Independent QA requires a fresh context, read-only source checkout, and no GitHub push/merge credentials.
- A stale head, base, tested tree, acceptance spec or suite fingerprint invalidates a prior QA PASS.
- Repeated failure fingerprint across attempts means immediate ESCALATED, even with repair budget left.
- Owner Stop is STOP_PENDING until executor acknowledgement; only confirmed Stop yields BLOCKED(reason=OWNER_STOP).
- Never fabricate token quota, context usage, CI results, QA outcomes or platform compliance.

### Canonical task states

- `READY` (nonterminal): Runnable when dependencies and policy checks are satisfied.
- `RUNNING` (nonterminal): Exactly one leased executor attempt is active.
- `VERIFYING` (nonterminal): Independent QA and CI validate exact Git evidence.
- `MERGING` (nonterminal): autoLoop alone holds the gated merge or close operation.
- `DONE` (terminal): Final merge or no-merge completion confirmed by autoLoop.
- `BLOCKED` (nonterminal): Requires a named resolution reason; OWNER_STOP is reversible.
- `ESCALATED` (nonterminal): Owner intervention required for repeated or exhausted failure.
- `SUPERSEDED` (terminal): Replaced by a new plan because acceptance or dependencies changed.

### Allowed transitions (event / required guards)

| From | Event | To | Required guards |
| --- | --- | --- | --- |
| `READY` | `CLAIM_ATTEMPT` | `RUNNING` | `dependencies_done`, `lease_granted`, `fencing_token_valid` |
| `READY` | `DEPENDENCY_BLOCKED` | `BLOCKED` | `dependency_blocked_reason_recorded` |
| `READY` | `REPLACE_PLAN` | `SUPERSEDED` | `acceptance_or_dependencies_changed`, `replacement_recorded` |
| `RUNNING` | `EXECUTION_FINISHED` | `VERIFYING` | `runner_exit_observed`, `attempt_artifacts_recorded`, `lease_fencing_valid` |
| `RUNNING` | `OWNER_STOP_CONFIRMED` | `BLOCKED` | `runner_stop_confirmed`, `checkpoint_recorded`, `block_reason_owner_stop` |
| `RUNNING` | `EXECUTION_BLOCKED` | `BLOCKED` | `runner_quiesced`, `blocking_reason_recorded` |
| `RUNNING` | `TERMINAL_EXECUTION_FAILURE` | `ESCALATED` | `runner_quiesced`, `failure_evidence_recorded` |
| `VERIFYING` | `QA_AND_CI_PASS` | `MERGING` | `head_sha_current`, `base_sha_current`, `tested_tree_sha_current`, `acceptance_spec_current`, `suite_fingerprint_current`, `independent_qa_pass`, `ci_success`, `merge_policy_allows` |
| `VERIFYING` | `INVALIDATE_EVIDENCE` | `VERIFYING` | `evidence_change_observed`, `old_evidence_revoked` |
| `VERIFYING` | `START_REPAIR` | `RUNNING` | `qa_failure_recorded`, `failure_fingerprint_new`, `repair_budget_available`, `new_attempt_lease_granted` |
| `VERIFYING` | `REPEATED_FAILURE` | `ESCALATED` | `duplicate_failure_fingerprint`, `failure_evidence_recorded` |
| `VERIFYING` | `REPAIR_LIMIT` | `ESCALATED` | `repair_budget_exhausted`, `failure_evidence_recorded` |
| `VERIFYING` | `WAIT_FOR_APPROVAL` | `BLOCKED` | `approval_required`, `blocking_reason_recorded` |
| `VERIFYING` | `REPLACE_PLAN` | `SUPERSEDED` | `acceptance_or_dependencies_changed`, `replacement_recorded` |
| `MERGING` | `FINALIZE_MERGE` | `DONE` | `auto_loop_merge_confirmed`, `exact_evidence_still_valid`, `target_ref_confirmed` |
| `MERGING` | `MERGE_EVIDENCE_STALE` | `VERIFYING` | `merge_not_started`, `evidence_change_observed`, `old_evidence_revoked` |
| `MERGING` | `MERGE_OUTCOME_UNKNOWN` | `BLOCKED` | `merge_reconciliation_required`, `blocking_reason_recorded` |
| `BLOCKED` | `RESUME_OWNER_STOP` | `READY` | `block_reason_owner_stop`, `runner_stop_confirmed`, `dependencies_done`, `no_active_lease` |
| `BLOCKED` | `DEPENDENCIES_RECOVERED` | `READY` | `dependency_blocked_reason_recorded`, `dependencies_done`, `no_active_lease` |
| `BLOCKED` | `QA_APPROVAL_RECEIVED` | `VERIFYING` | `qa_block_reason_recorded`, `approval_confirmed`, `evidence_recheck_required` |
| `BLOCKED` | `MERGE_RECONCILED` | `MERGING` | `previously_in_merging`, `merge_reconciliation_complete`, `no_duplicate_side_effect`, `prior_qa_pass_still_valid`, `exact_evidence_still_valid` |
| `BLOCKED` | `DEPENDENCY_NOT_RECOVERABLE` | `ESCALATED` | `dependency_superseded_or_terminal`, `escalation_reason_recorded` |
| `BLOCKED` | `REPLACE_PLAN` | `SUPERSEDED` | `acceptance_or_dependencies_changed`, `replacement_recorded` |
| `ESCALATED` | `OWNER_REAUTHORIZE` | `READY` | `explicit_owner_approval`, `new_attempt_budget_recorded`, `dependencies_done` |
| `ESCALATED` | `REPLACE_PLAN` | `SUPERSEDED` | `acceptance_or_dependencies_changed`, `replacement_recorded` |

### Limits and protected paths

- Max repair cycles: **2**.
- Repeated failure immediately escalates: **true**.
- Context checkpoint suggestion: **65%**; prepare new session: **80%**.
- Maximum dispatcher writers: **1**; storage: **sqlite/WAL**.
- Protected-path rule: `explicit_owner_approval_before_modification_or_merge`. Paths:
  - `contracts/**`
  - `.github/workflows/**`
  - `AGENTS.md`
  - `CLAUDE.md`
  - `docs/ADR-*.md`
  - `.env*`
  - `**/secrets/**`
  - `**/*credential*`

### Required attempt report fields

Include machine-readable fields: `project_id`, `task_id`, `attempt_id`, `result`, `head_sha`, `base_sha`, `tested_tree_sha`, `tests`, `artifacts`, `tokens`.
Unknown token counts or subscription balance must be `null`, never guessed.
Agents cannot authorize transitions by changing their own reports; autoLoop checks every guard.

<!-- END AUTOLOOP-GENERATED RULES -->
