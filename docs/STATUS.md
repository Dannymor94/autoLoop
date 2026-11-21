# autoLoop — Implementation status

Updated: 2026-11-21 (UTC). Evidence must be linked before a gate is marked PASS.

**v0.4.2 accepted for planning:** see [PLAN_V0.4.2.md](PLAN_V0.4.2.md),
[ECONOMICS.md](ECONOMICS.md) and [METRICS.md](METRICS.md). The seven
deterministic economic-measurement clarifications and efficiency principle
have been documented. An initial owner-time CLI, termination-lag parser and
per-attempt budget wrapper are now **offline-tested only**; the complete
measurement experiment is not wired into a live runner. The earlier v0.4.1
execution sequence is unchanged.

**v0.4.1 approved:** see [PLAN_V0.4.1.md](PLAN_V0.4.1.md). Own prototype is
provisionally selected; launchd Smoke A and real Mac E2E are the next gates. The older
Bernstein/Kandev/Cezar live pilot is deferred unless E2E fails. The offline
implementation is prepared for a **separate stacked draft PR**; it must not
be conflated with PR #2's earlier CI evidence.

v0.4.1 planning update: per-attempt `fcntl.flock` wrapper replaces proposed
long-lived supervisor, Smoke A explicitly tests launchd/Keychain auth,
publisher is commit-local + autoLoop push/PR, and four crash-injection
points are frozen in `pilot/e2e/manifest.yaml`. **The wrapper is offline-tested;
Mac login, GitHub rulesets and publisher have NOT been tested live.**

**Offline v0.4.2 implementation (local, pending GitHub CI):** added the isolated
`attempt_wrapper.py` with durable one-shot launch intent, inherited `flock`,
bounded process wait and validated `.exit` receipt; `billing_guard.py` with
mock-tested subscriber auth/provider checks; owner-time append-only JSONL
ledger and `python -m autoloop time start/stop/summary`; and an observed
termination-lag parser. Added offline CI matrix `ubuntu-latest` + `macos-15`
and [Mac handoff](MAC_HANDOFF.md). **No SQLite outbox/worker integration, live
Mac auth, OS-separated QA, Github publisher or real Smoke B PASS yet.**

**Local-only Stage 0 result (2026-11-21):** offline core suite (110 tests PASS), 8 mock fixture
tests PASS, contracts validator PASS, generated agent-doc drift check PASS.
Added Git-visible dirty-tree SHA capture to checkpoints, `require_checkpoint_unchanged`,
Codex JSONL fsync receipts with read-only recovery, and a frozen `pilot/e2e/`
smoke acceptance hash/manifest. These are NOT live runner or SIGKILL PASS.

Latest core prototype review: [draft PR #2](https://github.com/Dannymor94/autoLoop/pull/2), [first PR CI PASS on commit `1928d3e6`](https://github.com/Dannymor94/autoLoop/actions/runs/44616381127). This CI runs 71 core/contract unit tests and 8 offline pilot tests, not the live acceptance pilot.

| Task | State | Evidence and next gate |
| --- | --- | --- |
| Bootstrap | DONE | Initial default branch and project README |
| AL-101 — contract bootstrap | GITHUB_CI_PASS | [CI run 44599076437](https://github.com/Dannymor94/autoLoop/actions/runs/44599076437): schema and generated-doc integrity checks passed. |
| AL-001 — reproducible pilot fixture | MOCK_PREFLIGHT_PASS / LIVE_NOT_TESTED | [Issue #1](https://github.com/Dannymor94/autoLoop/issues/1): reusable fixture in `pilot/fixture/`; 8 offline harness tests PASS, including SIGKILL child-process recovery. Live platform runs and dedicated fixture repo still outstanding. |
| AL-002 — Bernstein pilot | NOT_TESTED | Requires AL-001 fixture; mandatory criteria 2–4. |
| AL-003 — Kandev pilot | NOT_TESTED | Requires AL-001 fixture; mandatory criteria 2–4. |
| AL-004 — Cezar pilot | NOT_TESTED | Requires AL-001 fixture; mandatory criteria 2–4. |
| AL-005 — select executor | PROVISIONAL_OWN_PROTOTYPE | Approved direction in v0.4, pending real E2E/SIGKILL. ADR-001 protected update pending. |
| AL-102 — SQLite dispatcher | LOCAL_PASS / PR_CI_PASS | Single-writer WAL, 14 tables, Alembic, durable outbox, fencing, SIGKILL replay and Stop confirmation tested. No unattended process reconciler or full crash-recovery daemon yet. |
| AL-103 — CLI adapters | LOCAL_MOCK_PASS / LIVE_NOT_TESTED | Worktree-bound Codex command adapter, private logs, JSON usage parsing, fail-closed uncertain delivery. Claude CLI not installed in test environment; subscription session unspent. Offline checks passed in PR CI. |
| AL-104 — QA evidence gate | LOCAL_MOCK_PASS / OS_ISOLATION_NOT_TESTED | Head/base/tested tree/spec/suite validation, protected paths, repeated failure escalation and max repair bound. Trusted GitHub/CI adapter, OS read-only push-negative test and real merge are absent. Offline checks passed in PR CI. |
| AL-105 — context checkpoints | LOCAL_PASS / LIVE_USAGE_NOT_TESTED | Structured usage or UNKNOWN, 65/80 guidance, SHA + Git-visible dirty-tree bound immutable checkpoints. Resume/QA wiring and real compact/clear still disabled. |
| AL-106 — mobile control | LOCAL_API_PASS / DEVICE_NOT_TESTED | Owner login, CSRF, HttpOnly cookie, Stop/Resume, responsive read-only dashboard on loopback. Private tunnel and physical phone test not configured. |
| AL-107 — browser delivery bridge | NOT_STARTED | Out of MVP; explicit destination and delivery-only bridge contract still needed. |
| AL-108 — multi-host | NOT_STARTED | PostgreSQL and multiple writers deferred until single-host acceptance. |

## Evidence policy

- `LOCAL_PASS` or `MOCK_PREFLIGHT_PASS` means checks ran in a separate preparation environment, **not** GitHub Actions PASS or an OSS candidate's PASS.
- `NOT_TESTED` must never be counted as PASS in the pilot matrix.
- CI synthetic merge-ref must bind head SHA, base SHA and tested tree SHA.
- A successful upstream framework unit test is not a passing autoLoop pilot scenario.
- Offline components passing unit tests are **not** proof of a working mobile-to-CLI-to-GitHub agent loop.

## Agent handoff

Resume with [v0.4.2](PLAN_V0.4.2.md) stage 1 and the [v0.4.1](PLAN_V0.4.1.md)
Smoke A: preflight subscription CLI logins under launchd, the `BILLING_MODE`
negative matrix and a separate QA OS user on Mac. Then integrate the offline
wrapper with the SQLite outbox/dispatcher and enforce effective CLI permissions
and isolation. Run the frozen disposable [E2E task](../pilot/e2e/ACCEPTANCE.md)
and SIGKILL tests. Only after Smoke B PASS start economic experiment B.
Live Claude, QA push denial, CI adapter, SQLite receipt reconciliation, and
mobile E2E remain untested. Never merge agent work into a real user project
without its own verified QA gate.
