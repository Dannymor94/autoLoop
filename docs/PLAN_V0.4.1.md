# autoLoop v0.4.1 — attempt wrapper, Mac auth and four crash gates

**Approved architecture:** 2026-11-20. **State:** planning/frozen acceptance only; no real Mac run yet.

This document supersedes the implementation order in
[PLAN_V0.4.md](PLAN_V0.4.md). The deterministic state machine, sole autoLoop
ownership, subscription CLI execution, independent QA, SHA evidence,
GitHub Issues after full E2E, and mobile human-only access remain unchanged.

## 1. Per-attempt process wrapper, not a persistent supervisor

Invoke `autoloop-attempt <attempt_id>` from the one-writer dispatcher using a
durable, hashed command file. The wrapper enters its own OS session, validates
the attempt/fencing token, acquires a nonblocking **exclusive** `fcntl.flock`
on `attempts/<id>.lock`, and launches exactly one CLI subprocess. Duplicate
attempt IDs must never create another subprocess.

The subprocess receives stdin from a durable prompt file, not a dispatcher
pipe. Stdout and stderr go directly to attempt-specific files, never to a
dispatcher pipe. The wrapper fsyncs the log and atomically creates a sealed
`attempts/<id>.exit` receipt (attempt_id, fencing token, provider, observed
exit code, log hash and terminal event), followed by directory fsync. Only
then may autoLoop reconcile completion to SQLite.

**Important crash detail:** if the wrapper is killed while the agent is still
alive, the agent must hold an inherited copy of the lock descriptor (or the
wrapper must guarantee child termination) to avoid reporting a running agent
as stopped. If the agent finishes without the wrapper, `.exit` may be missing;
that is **UNKNOWN**, never an automatic new start or synthetic completion.
Validate inherited lock lifetime in a real SIGKILL test on macOS. Do not rely
on PID alone; PID numbers can be reused.

Recovery order, after observing a stable per-attempt directory:

1. Valid `.exit` and matching fsynced JSONL digest → `FINISHED` evidence;
   reconcile SQLite idempotently after checking attempt fence and Git state.
2. No `.exit`, lock busy → `RUNNING/RECONCILING` (no duplicate launch).
3. No `.exit`, lock free → `UNKNOWN` unless an independent durable dispatch
   ledger proves that wrapper execution was never attempted. Investigate and
   explicitly authorize any new attempt; never replay an uncertain start.
4. Conflicting receipt, malformed log, uncertain lock ownership, or stale
   fencing token → `BLOCKED` / require owner reconciliation.

All attempt artifacts reside on a local filesystem in a private directory,
not NFS or a cloud sync folder. File names are derived from validated IDs.
Lock ownership cannot by itself authorize `QA_PASS`, `MERGING` or `DONE`.

The existing `attempt_journal.py` is a prototype receipt mechanism. It has
NOT been integrated into an OS wrapper or SQLite recovery yet.

## 2. Smoke A must run under launchd

Use an isolated disposable fixture and no paid API fallback. Run both CLI
subscription logins in an ordinary terminal **and** the intended `launchd`
execution context. Record CLI versions, exit status, structured event types
and whether authentication succeeds without GUI interaction; never publish
tokens, Keychain contents or subscription credentials.

Test separately:

- `LaunchAgent` for the interactive, logged-in development user.
- Candidate `LaunchDaemon` / separate QA OS identity (only if provisioned).
- Clean `HOME`/environment and absent `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
  and similar API billing overrides. Confirm subscription auth method.
- Claude `-p --output-format stream-json` and Codex `exec --json`, sandbox
  and approval behavior, failure output, Stop signal, timeout and process exit.

The hypothesis that a locked login Keychain prevents headless authentication
is **NOT_TESTED**, not a finding. If confirmed, prefer properly logged-in
per-user `LaunchAgents` and their own authenticated GUI sessions. Falling
back to one OS user with CLI sandboxes weakens isolation; do **not** mark the
independent QA OS/denied-push gate as PASS under that fallback. Escalate the
required security profile or use a dedicated isolated execution host.

**Smoke A PASS** proves only authentic headless CLI compatibility under
launchd and truthful structured exit evidence. It does not prove GitHub,
independent QA, unattended recovery or end-to-end success.

## 3. Minimal publisher and server-side protection

Claude creates a local commit in its own isolated Git worktree, with no
GitHub write credentials. After the process exits and the dirty-tree policy
is satisfied, autoLoop validates the base/HEAD, protected paths, branch
name, commit ancestry, recorded attempt fence and exact SHA; autoLoop alone
pushes to `refs/heads/autoloop/<task-id>-<attempt-id>` and opens a PR.

Before pushing, fetch current remote refs. Never force push, reuse an owner
branch or push a tag. Recovery after a push must look up the remote branch
and any existing PR by head branch and repo identity before creating a PR;
one task/attempt must not produce duplicate PRs.

GitHub rulesets are a **second layer**: protect `main` from direct updates,
require PR/CI/review, prevent force-push/deletion, and restrict updates of
unapproved branch namespaces. Give the publisher a dedicated least-privilege
identity with no admin/bypass permissions. The ability to push only into the
approved namespace must be demonstrated with denied push attempts to `main`,
another namespace and tags, plus a denied premature merge. Do not assume a
repository-scoped `contents:write` token is itself branch-scoped. Verify
ruleset availability for this repository's visibility/plan before relying on
it. No actual GitHub rulesets have been modified yet.

## 4. Frozen SIGKILL matrix

`pilot/e2e/manifest.yaml` is normative. Run the same immutable task in
disposable branches with these predefined crash points:

| ID | Injection | Expected durable/recovered outcome |
| --- | --- | --- |
| `K1_AFTER_CLAIM_BEFORE_START` | Kill dispatcher after claim, before durable wrapper-launch intent | `RUNNING` + pending START; on recovery start exactly once because no spawn was attempted |
| `K2_DURING_AGENT` | Kill dispatcher while agent is active and lock held | `RUNNING` reattached to locked attempt; no second agent; completion reconciled from receipt |
| `K3_AFTER_EXIT_BEFORE_DB` | Kill dispatcher after atomic `.exit`, before SQLite completion | Receipt+log SHA revalidated; one DB transition to `VERIFYING`; no duplicate execution |
| `K4_AFTER_PUSH_BEFORE_PR` | Kill publisher after remote push, before PR creation | `VERIFYING` with one PR after remote SHA lookup; no repeat push, merge or duplicate branch |

Each case requires raw attempt JSONL, lock/exit evidence, event log, exact
head/base/dirty/tested-tree SHA, and an explicit absence-of-duplicate proof.
If any expected evidence is absent, status is UNKNOWN/FAIL, never assumed PASS.
The separate ambiguous window *after* wrapper launch was attempted but
*before* a durable receipt/lock observation is not K1; it must result in
`UNKNOWN` unless a separate no-spawn proof exists.

## 5. Implementation order

1. **Smoke A:** disposable subscription CLI + launchd authentication/JSON
   preflight on Mac, including a read-only Codex mode and failure case.
2. **Wrapper:** one-attempt lock/exit protocol with offline and real SIGKILL
   tests; hook the existing receipt journal to SQLite reconciliation.
3. **Privileges and publisher:** explicit policy-generated CLI restrictions,
   QA identity/negative push check, minimal autoLoop push+PR publisher and
   GitHub server ruleset checks. Protected contract changes require the
   existing explicit approval gate.
4. **Smoke B:** frozen normal end-to-end plus all four crash points. E2E
   PASS requires every artifact in the manifest and no merge.
5. **Only after Smoke B PASS:** GitHub Issues/approval comments, Tailscale
   terminal and mobile control. Bernstein/Kandev/Cezar remain fallback only
   for a material executor architecture failure, not an ordinary fixable bug.
