# autoLoop economics and preregistered hypotheses (v0.4.2)

**State:** design and research evidence only, 2026-11-20. No observed
human-time saving, token saving, economic PASS or live subscription E2E exists.
The 79 older prototype checks are engineering progress, not ROI evidence.

## Decision objective

Maximize accepted, independently verified tasks per unit of **scarce
subscription capacity** and owner-active time, subject to hard safety,
quality, exact-SHA and authorization gates. Features qualify for development
only if they demonstrably increase accepted throughput, reduce owner-active
time, or lower the risk of an incorrect/unsafe result.

## Prospective cost accounting (not sunk costs)

Already spent prototype hours are sunk costs and **must not** be counted in a
go/no-go decision. Record remaining engineering hours **from the decision date
until Smoke B**, not the original project estimate. The monthly prospective
break-even volume is:

```text
H_month = H_maintenance + H_remaining_to_SmokeB / amortization_months
net_owner_hours_saved_per_task = (T_manual_active - T_auto_active) / 3600
N_break_even = ceil((H_month + incremental_monthly_cash_cost / owner_hour_value)
                    / net_owner_hours_saved_per_task)
```

This formula applies only if `owner_hour_value > 0` and savings per accepted
task is positive. If saving is zero/negative or inputs are unknown, report
`NOT_ESTIMABLE`, not a fabricated lower task threshold. Include Mac energy,
incremental CI/private-repo billing, purchased model credits, infrastructure,
support and QA incident resolution in incremental costs. The owner's existing
Claude and ChatGPT subscription fees are fixed baseline costs, unless a plan
upgrade is caused by autoLoop. The **opportunity cost** of consumed subscription
quota must be tracked separately; it is not automatically equivalent to a
published token API price. Never double-count a fixed subscription fee.

The former illustrative 36-task/month threshold included hypothetical 40
hours of build time. It is **not the decision threshold** for our existing
prototype. Recalculate after estimating only the remaining work.

## Preregistered hypotheses and measurements

| ID | Falsifiable claim | Measure | Decision criterion (proposed, before data) |
| --- | --- | --- | --- |
| H1 | AutoLoop saves owner-active time compared with manual subscription CLI + browser coordination. | Same timer-ledger protocol in both arms; minutes/accepted task. | At least 30% saving is the target. |
| H2 | The deterministic wrapper/gates reduce resource waste. | Per-provider observed tokens and quota draw when available; attempts, test overhead, accepted task. | No material regression in provider-specific capacity/accepted task; `UNKNOWN` remains unknown. |
| H3 | Independent Codex QA detects real defects. | Seeded mutants detected / known mutants, and independently assessed false positives. | Record recall and false positives; never weaken the non-negotiable QA gate. |
| H4 | Additional agents, retries and larger models help only on some task classes. | Extra accepted tasks relative to resource/time cost by class. | Expand only if measured marginal benefit warrants it. |

**Stop criterion:** after the registered experiment, freeze new features if
`H1 < 30%` **AND** quota consumed **per accepted task** is not lower than
manual, provided both comparisons have valid data. Unmeasured quota yields
`INCONCLUSIVE`. Security or correctness findings are addressed regardless.
Do not choose a more favorable threshold after examining results.

## Design of economic experiment B

- Begin **only after** launchd Smoke A and the complete v0.4.1 Smoke B PASS.
- Use 12–20 preregistered real tasks in easy/medium/hard strata, matched by
  objective difficulty. Compare manual *Claude + Codex + ChatGPT + GitHub*
  against autoLoop; **not** unaided human coding.
- Lock acceptance specs, executable commands, SHA, CLI/model versions, risk
  class, assignment and analysis method before running. Counterbalance task
  ordering, reuse no already-learned solution, and keep both arms' quality
  expectations identical. Count abandoned and escalated tasks; never keep
  only easy PASS successes.
- Owner uses the timestamped `al time start/stop` activity ledger in **both**
  arms. AutoLoop event counts supplement but never substitute measured time.
- Seed a disclosed-to-experimenter, hidden-from-QA subset of mutant defects.
  Record mutation ID/gold label, baseline, seeded SHA and false-positive
  controls. Reviewers receive a clean fresh session and standard acceptance.
- Report arithmetic per complexity class and combined results; disclose
  sample-size limitations and task-level raw evidence.

## Source verification and limits

Checked the **primary sources** on 2026-11-20:

1. *Termination Lag: Coding Agents Solve Early but Stop Late* (Cim, Topcu,
   Kandemir; arXiv:2611.14960v1, dated 2026-11-11):
   https://arxiv.org/abs/2611.14960 and
   https://borowiecki.dev/pdf/2611.14960 . It examines intermediate source
   patches and verifies them with external benchmark tests. This supports
   **observed first verified pass** measurement, but **does not** justify
   claiming first-pass turn from JSONL alone without acceptance probes.
   Its measured agent/dataset proportions do not predict autoLoop savings.
2. OpenAI Help, *Understanding ChatGPT and Codex usage limits*:
   https://help.openai.com/en/articles/20001625-understanding-chatgpt-and-codex-usage-limits .
   As of 2026-11-20 OpenAI states that **starting in December** Plus, Pro
   and Business will share a ChatGPT/Codex allowance. This is a **future
   announced change**, not a measured current account condition; verify
   actual plan/account usage dashboard before interpreting quota data.
3. Anthropic Help, *Manage API key environment variables in Claude Code*:
   https://support.claude.com/en/articles/12304248-manage-api-key-environment-variables-in-claude-code .
   Explicit environment API keys can override subscription auth and cause
   separately billed API usage. Also verify `apiKeyHelper` effective settings.
4. Claude Code docs, *Legal and compliance*:
   https://code.claude.com/docs/en/legal-and-compliance . Personal use of
   the unmodified binary and third-party paid service/credential routing
   have distinct requirements. No credentials are copied into autoLoop.

**No external study demonstrates that autoLoop itself is cheaper.** Only the
registered manual-versus-autoLoop experiment can support that claim.
