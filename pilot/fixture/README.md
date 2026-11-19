# AL-001 reusable candidate fixture

This directory is a **template for a separate, disposable GitHub repository**. Copy it to a dedicated pilot repo, record its baseline SHA, then run the *same* fixture for Bernstein, Kandev and Cezar. Never install untrusted candidate orchestrators or run crash tests in a production repository.

Offline preparation requires Python 3.12+ and the repository's pinned PyYAML dependency:

```bash
python -m pip install -r requirements.txt
python harness.py replay
python -m unittest discover -s harness_tests -v
```

For T2 the normalized output of `python harness.py replay` must be byte-for-byte identical on two executions. For T3 the test suite intentionally sends SIGKILL **only to a child fixture Python process**. All side effects are mock SQLite records, never GitHub writes.

## T1 baseline is intentionally red

```bash
python -m unittest discover -s candidate_tests -v
```

The candidate executor must implement [`SPEC-T1.md`](SPEC-T1.md) by editing `toy_app.py` only. Keep the five acceptance tests unchanged. This will prove a minimal feature/PR path when performed with actual authorized CLI subscriptions.

For the live candidate comparison, freeze the toolchain versions (including `pytest`, `ruff` and `pyright`) in the **disposable repo's lockfile**, use the same lint/type-check commands for all three candidates, and include those inputs in `suite_fingerprint`. This offline template intentionally avoids forcing unverified tool versions or extra API costs.

## Distinguish fixture preflight from platform acceptance

Passing `harness_tests` proves the **mock harness** is deterministic and its simulated recovery is sound. It does *not* prove real platform recovery, absence of platform merge rights, Android control or working Claude/Codex subscriptions. All three platform results remain `NOT_TESTED` until their live tests are run with captured commands, configuration, SHAs and links.

The negative QA push test requires an actual isolated QA OS identity with a read-only checkout and no Git credentials. It cannot be passed by a Python mock that simply raises `PermissionError`.

T1–T5 and the six binary selection criteria are normative in [`docs/ADR-001-executor.md`](../../docs/ADR-001-executor.md), plus [AL-001 Issue #1](https://github.com/Dannymor94/autoLoop/issues/1). Avoid mixing platform test results with these offline preflight checks.
