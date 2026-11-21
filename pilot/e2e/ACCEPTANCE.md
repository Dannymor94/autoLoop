# AL-E2E-001 — Frozen acceptance specification

This specification is immutable for the first real Mac smoke. Any amendment
requires a NEW task ID and acceptance_spec_hash before running an agent.

## Task for Claude Code

Implement `normalize_ticket_reference(value: str) -> str` in `ticket.py` in the
dedicated disposable fixture repository. An acceptable ticket has an optional
leading/trailing ASCII whitespace, case-insensitive `AL-` prefix, and an
integer from 1 through 999999 written without leading zeroes. Return the
canonical uppercase `AL-NNN` form (retaining the original decimal digits).
Reject all other inputs with `ValueError`. The implementation must not call
external services or add dependencies. Preserve the public function signature.

## Executable acceptance cases

- `"al-1"` returns `"AL-1"`.
- `" AL-42\n"` returns `"AL-42"`.
- `"Al-999999"` returns `"AL-999999"`.
- `"AL-0"`, `"AL-01"`, `"AL-1000000"`, `"AL-3x"`, `"AL--1"` and `""` raise `ValueError`.
- Running the checked-in `python -m unittest discover -s tests -v` succeeds.

## Execution boundary

Claude is the sole implementation agent. Codex is the sole independent QA
agent, in a fresh context with read-only access to source, no push credential
and a separate identity. Unit tests may run in CI or a disposable writable
copy, never writing into the QA source worktree.

No merge, close or deployment is authorized by this fixture. Only autoLoop
may evaluate the CI and QA evidence after the exact Git identities match.
