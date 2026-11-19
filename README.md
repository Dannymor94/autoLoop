# autoLoop

Deterministic-first orchestration for subscription-based Claude Code and Codex CLI agents, with independent QA and mobile-first control.

**Project status:** contract bootstrap in progress. No OSS executor has been selected; no candidate has passed the AL-001 acceptance pilot. See [the implementation plan](docs/IMPLEMENTATION_PLAN.md).

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
| `AGENTS.md`, `CLAUDE.md` | Agent instructions; marked sections are generated from contracts |
| `scripts/generate_agent_docs.py` | Deterministic generator and drift check |

## Contract checks

Requires Python 3.12+ and PyYAML 6.0.3. No API key or paid model is required.

```bash
python -m pip install -r requirements-dev.txt
python scripts/validate_contracts.py
python scripts/generate_agent_docs.py --check
python -m unittest discover -s tests -v
```

To regenerate marked agent instruction blocks after changing a contract:

```bash
python scripts/generate_agent_docs.py
```

CI verifies generated content; it does **not** regenerate or silently overwrite it.

## Next acceptance gates

1. **AL-001**: freeze a disposable five-scenario pilot fixture, execute it against each candidate and record independently verifiable PASS/FAIL/NOT_TESTED outcomes.
2. **AL-002/003/004**: run the Bernstein/Kandev/Cezar pilots with subscription credentials on an isolated user-controlled host.
3. **AL-005**: choose the platform only if mandatory gates 2–4 pass, then finalize ADR-001.
4. **AL-101**: contracts and generated instruction files must pass CI before the dispatcher implementation starts.

This repository contains no production agent credentials. Do not commit credentials, or run dangerous permission-bypass flags on a personal machine.
