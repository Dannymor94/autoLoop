# autoLoop — Implementation status

Updated: 2026-11-19 (UTC). Evidence must be linked before a gate is marked PASS.

| Task | State | Evidence and next gate |
| --- | --- | --- |
| Bootstrap | DONE | Initial default branch and project README |
| AL-101 — contract bootstrap | GITHUB_CI_PASS | [CI run 44599076437](https://github.com/Dannymor94/autoLoop/actions/runs/44599076437): schema and generated-doc integrity checks passed. |
| AL-001 — reproducible pilot fixture | MOCK_PREFLIGHT_PASS / LIVE_NOT_TESTED | [Issue #1](https://github.com/Dannymor94/autoLoop/issues/1): reusable fixture in `pilot/fixture/`; 8 offline harness tests PASS, including SIGKILL child-process recovery. Live platform runs and dedicated fixture repo still outstanding. |
| AL-002 — Bernstein pilot | NOT_TESTED | Requires AL-001 fixture; mandatory criteria 2–4. |
| AL-003 — Kandev pilot | NOT_TESTED | Requires AL-001 fixture; mandatory criteria 2–4. |
| AL-004 — Cezar pilot | NOT_TESTED | Requires AL-001 fixture; mandatory criteria 2–4. |
| AL-005 — select executor | BLOCKED_ON_PILOT | No platform selected; ADR-001 remains PROPOSED. |
| AL-102 — SQLite dispatcher | LOCAL_PASS / PR_CI_PENDING | Single-writer WAL, 14 tables, Alembic, durable outbox, fencing, SIGKILL replay and Stop confirmation tested. No unattended process reconciler or full crash-recovery daemon yet. |
| AL-103 — CLI adapters | LOCAL_MOCK_PASS / LIVE_NOT_TESTED | Worktree-bound Codex command adapter, private logs, JSON usage parsing, fail-closed uncertain delivery. Claude CLI not installed in test environment; subscription session unspent. |
| AL-104 — QA evidence gate | LOCAL_MOCK_PASS / OS_ISOLATION_NOT_TESTED | Head/base/tested tree/spec/suite validation, protected paths, repeated failure escalation and max repair bound. Trusted GitHub/CI adapter, OS read-only push-negative test and real merge are absent. |
| AL-105 — context checkpoints | LOCAL_PASS / LIVE_USAGE_NOT_TESTED | Structured usage or UNKNOWN, 65/80 guidance, SHA-bound immutable checkpoints. Real compact/clear intentionally disabled. |
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

Resume with [AL-001](https://github.com/Dannymor94/autoLoop/issues/1): freeze the pilot fixture, use an authorized isolated CLI host to test the three OSS candidates, and choose an executor via the mandatory gates. The code in `src/autoloop/` may be used for offline integration testing, but real QA, CI and merge adapters are not yet trusted. Never merge agent work into a real user project without its own verified QA gate.
