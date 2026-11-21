# autoLoop Mac handoff — work that cannot be proven in GitHub Actions

**Status:** prepared from offline implementation; no real Claude or Codex
subscription session has been invoked. All commands below must run on the
owner-authorized MacBook Air in a disposable test checkout. Never paste token
values or Keychain output into a report.

## Before Smoke A (owner Mac)

1. Connect Mac to power, ensure adequate free disk, confirm sleep and lid
   policy for its actual installation. Do not assume `caffeinate` defeats
   closed-lid sleep on a MacBook Air.
2. Record `uname -a`, OS version, installed `claude --version`,
   `codex --version`, Python 3.12, and working login-user context.
3. Run `claude auth status --json` and `codex login status` locally and
   redact usernames/emails. Verify **subscriber** login, not API credentials.
4. Inspect all effective settings scopes, including managed settings and
   configured authentication/provider overrides. `apiKeyHelper`, API
   variables or unrecognized settings must block; no paid API fallback.
5. Use real `launchd` **LaunchAgent** under the logged-in owner account and
   compare noninteractive auth result with Terminal; test a separate QA
   macOS user only after that user's own interactive account login.

## Smoke A required evidence

| ID | Procedure | PASS evidence |
| --- | --- | --- |
| A1 | Claude subscriber login in Terminal + launchd | Both auth status snapshots and JSONL contract; no stored secret |
| A2 | Codex ChatGPT login in Terminal + launchd | Both status snapshots and JSONL contract; no API billing |
| A3 | Inject `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` in test environment | Wrapper blocks as `BILLING_MODE` before model invocation |
| A4 | Configure `apiKeyHelper` and a paid provider in disposable settings | Wrapper rejects, no paid call |
| A5 | Missing/ambiguous subscription status | `BILLING_MODE`, never silently use credits |
| A6 | Verify model permission/sandbox behavior | Claude rules enforced, Codex QA read-only, no bypass flags |

The local Python `attempt_wrapper` and `billing_guard` implementations are
**not integrated with SQLite dispatcher reconciling yet**. Their offline test
PASS is not a Smoke A PASS. The wrapper's mock-execution path exists solely
in direct unit-test injection; the executable entrypoint requires preflight.

## After Smoke A, before Smoke B

- Validate CLI flag availability, structured event completion and exit code
  mapping against *installed versions*. Claude authenticated status JSON field
  names are pinned only after observation; otherwise fail closed.
- Connect wrapper attempt command SHA to SQLite outbox/fencing and reconcile
  valid `.exit` exactly once after restart. Missing receipt must remain
  `UNKNOWN` even when raw JSONL ends with a terminal-looking event.
- Test real SIGKILL under macOS, including inherited `flock` lifetime,
  `launchd` restart and owner Stop delivery.
- Provision QA under a distinct OS identity and credentials scope, perform
  **negative `git push` test**, not merely process sandbox settings.
- Provision an owner-authorized GitHub publisher with restricted branch
  namespace and no rule bypass; verify denied pushes to `main`, tags and
  unrelated branches before any actual merge path is enabled.
- Execute frozen `pilot/e2e/manifest.yaml` unchanged: normal flow + K1–K4,
  with CI, PR, head/base/tree SHA, QA verdict, logs and idempotence evidence.

## After Smoke B, economics and phone

- In both manual and automated experiment arms, measure owner activity via
  `PYTHONPATH=src python -m autoloop time start AL-XXX` and matching `stop`.
  The data is local `data/owner-time.jsonl`; it is **not** automatically
  uploaded to GitHub. Do not post personal activity data without review.
- Calibrate first-observed acceptance vs final-agent-step metric with
  independently executed tests on exact tree identities, or keep `UNKNOWN`.
- Run the preregistered 12–20-task comparison before optimizing additional
  agents. Keep raw results and assess the CONTINUE/FREEZE/INCONCLUSIVE rule.
- Only after reliability gates: GitHub issue command/approval allowlist,
  private mobile terminal access, owner-intervention checkpoint verification.

## Interpretation of offline results

GitHub Actions on macOS tests process/file semantics inside an ephemeral
runner; it does not have the owner's Keychain or subscription session. Mock
CLI output validates local parsing and control flow, not provider compliance.
No new `main` merge, paid call, live Smoke A or B PASS is authorized by an
offline green check.
