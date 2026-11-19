# autoLoop

Deterministic-first orchestration for subscription-based Claude Code and Codex CLI agents, with independent QA and mobile-first control.

**Project status:** contracts and the offline deterministic prototype are implemented; the actual subscription CLI + independent OS-isolated QA + mobile-on-device loop is **not** yet validated. No OSS executor has been selected or passed the AL-001 live acceptance pilot. See [the implementation plan](docs/IMPLEMENTATION_PLAN.md) and [evidence/status](docs/STATUS.md).

## Non-negotiable boundaries

- **autoLoop owns the canonical task queue, leases, retry/repair budgets, state transitions, evidence and merge/close decisions.** The selected OSS platform may only execute an explicit attempt and report events.
- Canonical task states and transitions come exclusively from [`contracts/states.yaml`](contracts/states.yaml), not an LLM, a platform UI or an agent report.
- A platform-run `COMPLETED` event is *not* an autoLoop task `DONE`. Auto-merge and auto-close must be disabled and credentials separated.
- QA runs in a fresh independent context and read-only checkout, without developer chain-of-thought or GitHub write credentials. Final evidence binds `head_sha`, `base_sha`, the tested Git tree, the acceptance spec and the CI suite fingerprint.
- The initial backend will use **SQLite/WAL + SQLAlchemy + Alembic** with a single dispatcher writer. PostgreSQL is a later multi-writer/multi-host decision.
- Browser chat integration is **delivery-only**. It does not read chat replies or authorize state transitions.

## Repository map

| Path | Authority |
| --- | --- |
| `contracts/states.yaml` | Allowed task states/transitions and their guards |
| `contracts/limits.yaml` | Repair, context and timeout limits |
| `contracts/protected_paths.yaml` | Paths requiring owner review |
| `contracts/policies.yaml` | Execution, merge and QA security policies |
| `contracts/*.json` | Task, runner event, QA evidence and report schemas |
| `docs/ADR-001-executor.md` | Ownership matrix and pending OSS decision |
| `docs/IMPLEMENTATION_PLAN.md` | Architecture, milestones and acceptance plan |
| `docs/STATUS.md` | Current task/evidence tracker (never infer CI PASS) |
| `pilot/fixture/` | Copyable offline pilot template; includes five scenarios and SIGKILL mock checks |
| `pilot/RESULTS.md` | Binary candidate matrix; initially all NOT_TESTED |
| `AGENTS.md`, `CLAUDE.md` | Agent instructions; marked sections are generated from contracts |
| `scripts/generate_agent_docs.py` | Deterministic generator and drift check |
| `src/autoloop/` | Durable dispatcher, fenced runner outbox, SHA-bound QA, context ledger, local mobile API |
| `migrations/` | Alembic schema for SQLite/WAL with a single writer |
| `web/` | Password-gated mobile browser UI with Stop/Resume requests |

## Contract checks

Requires Python 3.12+ and PyYAML 6.0.3. No API key or paid model is required.

```bash
python -m pip install -r requirements-dev.txt
python scripts/validate_contracts.py
python scripts/generate_agent_docs.py --check
python -m unittest discover -s tests -v
python -m unittest discover -s pilot/fixture/harness_tests -v
```

To regenerate marked agent instruction blocks after changing a contract:

```bash
python scripts/generate_agent_docs.py
```

CI verifies generated content; it does **not** regenerate or silently overwrite it.

## Run the local prototype

Use Python 3.12+, an isolated environment, and a user-controlled test repository. These commands create durable local state without invoking a paid model:

```bash
python -m pip install -r requirements-dev.txt
export PYTHONPATH=src
python -m autoloop --db data/autoloop.sqlite init-db
python -m autoloop --db data/autoloop.sqlite add-project --id demo --name Demo
python -m autoloop --db data/autoloop.sqlite add-plan --id demo-v1 --project demo --spec-hash aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
python -m autoloop --db data/autoloop.sqlite add-task --id T1 --plan demo-v1 --title "Review sample feature" --acceptance-hash bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
python -m autoloop --db data/autoloop.sqlite tasks
```

To open the private owner UI on **the same machine**:

```bash
export AUTOLOOP_OWNER_PASSWORD='replace-this-with-a-private-unique-password'
python -m autoloop --db data/autoloop.sqlite serve --port 8765
```

Then open `http://127.0.0.1:8765/ui/`. This command binds **only 127.0.0.1**, so it cannot be reached directly from a mobile phone; a separately configured authenticated/private tunnel is required. Local HTTP uses a host-only HttpOnly SameSite cookie. HTTPS integrations must use `create_app(..., secure_cookie=True)` and a trusted private proxy. **Do not expose this development server to the public internet.**

The CLI can claim a task (`claim --worker name --key unique-key`); an accepted claim emits a durable START command. It does **not** start an agent by itself. The internal `RunnerWorker` can deliver one explicit command to an isolated Git worktree with the mock adapter, or to an installed Codex CLI with user-authorized credentials. There is no unattended daemon, automatic worktree provisioning, real Claude Code integration, end-to-end Stop delivery, real GitHub proof adapter, or executable merge operation yet. The mobile UI displays the truth from the DB; its Stop action remains `STOP_PENDING` until a runner confirms it.

`codex exec --json --sandbox workspace-write` is invoked with instructions on stdin and no bypass-permission flags. That Codex sandbox is not proof that the QA runner is independently OS-isolated. Token values are reported **only when a CLI event exposes them**; unknown context fullness and remaining subscription quota stay `null`/`UNKNOWN`. Agents are not automatically cleared/compacted.

## Next acceptance gates

1. **AL-001**: finish freezing the disposable five-scenario pilot fixture, then execute it against each candidate and record independently verifiable PASS/FAIL/NOT_TESTED outcomes. The checked-in mock harness is **preflight only**.
2. **AL-002/003/004**: run the Bernstein/Kandev/Cezar pilots with subscription credentials on an isolated user-controlled host.
3. **AL-005**: choose the platform only if mandatory gates 2–4 pass, then finalize ADR-001.
4. **AL-102–106**: integrate the offline components with the chosen platform and prove real process callbacks, OS-isolated QA push denial, and mobile access on an actual phone before accepting the entire autonomous loop.

This repository contains no production agent credentials. Do not commit credentials, or run dangerous permission-bypass flags on a personal machine.
