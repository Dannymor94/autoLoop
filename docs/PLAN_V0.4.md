# autoLoop v0.4 — approved architecture, E2E-first execution plan

**Decision:** 2026-11-20. **Status:** architecture approved; physical Mac E2E not run.

The in-repository executor prototype is the provisional executor. Bernstein,
Kandev and Cezar are fallback experiments only if live E2E proves a material
architectural blocker. Offline 79 PASS is not a live acceptance result.

## Hard boundaries

1. **Sole controller:** autoLoop owns canonical states, queue, leases, retry,
   worktree evidence and merge. `states.yaml` transitions are enforced in code.
2. **Noninteractive agents:** Claude `claude -p --output-format stream-json`
   implements; Codex `codex exec --json` independently reviews. No vendor
   Remote session belongs to an autoLoop process. Vendor Remote is human-only.
3. **Intervention:** stop and quiesce the attempt, emit durable
   `OWNER_INTERVENTION`, then `BLOCKED(reason=OWNER_INTERVENTION)`; no automatic
   resume. Before Resume and QA, compare both HEAD and the Git-visible dirty
   tree with the saved checkpoint and reconcile changes explicitly.
4. **Fail-closed privileges:** `policies.yaml` enumerates dangerous actions;
   unknown actions are denied, approvals bind task/action/head/base/policy
   revision and are single-use with TTL. The LLM does not decide what needs
   approval. Generate CLI permission profiles from contracts and prove they
   are actually active on the installed versions; never overwrite a user's
   personal `.claude/settings.json` to install them.
5. **QA:** fresh session, separate OS user, source checkout read-only,
   no GitHub write/push credentials, no developer reasoning. Run any tests in
   CI or a disposable writable export of the exact committed SHA. A QA source
   worktree is never used as a writable test working directory. Verify an
   attempted QA push is rejected, irrespective of the agent's promise.
6. **GitHub:** issues with the `autoloop` label and one schema-valid YAML
   task body. Poll through `gh` outbound from Mac, no inbound webhook.
   Authorization uses immutable GitHub user IDs. Idempotency binds issue ID,
   accepted revision/content digest and task ID. Edited comments/issues do
   not silently mutate accepted tasks.
7. **Approvals:** explicit `/approve <action> <head_sha>` comment on the
   related issue/PR from an allowlisted user ID; the command is consumed once,
   with TTL and unchanged SHA/policy checks. Comment edits invalidate it.
   Parsing/transport implementation is strictly AFTER live E2E.

## Git-visible dirty-tree identity

At a **quiescent** checkpoint, use a temporary `GIT_INDEX_FILE`, `git
read-tree HEAD`, `git add -A -- :/`, `git write-tree`. The real `.git/index` is
not modified. `head_sha` and `dirty_tree_sha` are bound to the checkpoint;
differences reject Resume and QA. Git ignores ignored/untracked-ignored
artifacts and does not capture internal modifications of an uncommitted
submodule; isolate build outputs, and require a clean committed checkout for
the final QA/CI SHA gate. Filesystem activity must be quiesced before taking
the snapshot; this algorithm is not a transactional filesystem snapshot.

The prototype already has `capture_git_snapshot()` and a checkpoint verifier;
it does **not** yet persist an `OWNER_INTERVENTION` canonical state event on
detected mismatch, which requires an approved `states.yaml` extension.

## Crash-consistent attempts

The stdout/stderr JSONL stream is written to a per-attempt file. On observed
process exit, **first** flush and fsync file contents, then persist an atomic
fsynced completion receipt containing attempt ID, process exit code, log
digest and validated terminal-event identity; only **then** update SQLite
inside a transaction. Fsync the directory after receipt rename.

On restart: a verifiably complete receipt and matching log may be rehydrated
idempotently; a truncated/ambiguous log or missing receipt is `UNKNOWN` and
requires Git/process reconciliation. The mere presence of a final-looking
JSON line is not proof of successful process exit or successful task/QA.
Never silently launch the same external attempt twice. The Codex CLI adapter
now seals a fsynced completion receipt before returning a result and can
reload that receipt after a restart. **SQLite/outbox reconciliation of those
receipts is not yet wired**, and Claude's terminal stream needs live validation.
This remains a required E2E/kill-9 acceptance gate.

## Mandatory stage order

### Stage 0 — Mac and contract preflight

- [ ] Owner approves protected changes in `contracts/states.yaml`,
  `contracts/policies.yaml`, generated `AGENTS.md`/`CLAUDE.md` and ADR-001.
- [ ] Implement `OWNER_INTERVENTION` transition and durable event receipt.
- [ ] Add policy `dangerous_actions`, check default deny and run generator
  for Claude session `--settings` and Codex sandbox/approval profile.
- [ ] Check actual effective tool permissions on the Mac; no bypass flags.
- [ ] Verify user-authorized Claude and Codex subscription CLI auth without
  copying secrets; provision and authorize the QA OS user separately.
- [ ] Demonstrate read-only QA source and actual denied Git push.
- [ ] Ensure Mac is on AC power, lid open / supported clamshell mode,
  idle-sleep prevented as appropriate, `launchd KeepAlive` and restart
  behavior tested. `caffeinate` does not prevent lid-triggered forced sleep.
- [x] Git-visible worktree hash utility + checkpoint binding + unit tests.
- [x] E2E task specification, expected evidence and fixture frozen in
  `pilot/e2e/manifest.yaml`.

### Stage 1 — One real normal E2E on Mac

Use **only** a disposable repository copied from
`pilot/e2e/disposable_repo`. Record its baseline Git SHA before start.
The initial unit tests fail with `NotImplementedError` intentionally.
Claude implements the immutable `AL-E2E-001` specification, Codex reviews
in read-only QA, CI runs the frozen tests, and autoLoop writes evidence
bound to head/base/tested tree/suite fingerprint. The run must not merge.
PASS requires ALL `manifest.yaml` evidence fields with stable identities.

### Stage 2 — SIGKILL / recovery E2E

Repeat on disposable branches and inject failures during implementation and
after process exit but before SQLite completion commit. A restart must not
lose or double-start work. A partial stream means `UNKNOWN`, not PASS.
Test STOP_PENDING, confirmed BLOCKED, manual reconciliation and Resume.

### Stage 3 — GitHub command transport

Only after stages 1 and 2 pass. Implement outbound `gh` issue polling,
allowlisted task issue YAML and approval comments. A GitHub connector exposes
issue create/update tools, but repository-specific write access is still
unproven: test one disposable issue only with owner authorization.

### Stage 4 — mobile operation

ChatGPT/GitHub task control, review/approvals and ordinary macOS SSH over
Tailscale. Vendor Remote remains an optional human-intervention facility.

## Explicit non-PASS conditions

Missing artifact, stale base SHA, dirty-tree mismatch, QA with push rights,
unsupported CLI permission mode, duplicate start, unverifiable process exit,
sleeping Mac, or a failed `kill -9` recovery test means BLOCKED/FAIL. No
positive claim may be inferred from offline unit tests or agent narration.
