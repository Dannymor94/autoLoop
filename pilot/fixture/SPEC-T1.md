# PILOT-T1 — Identical bounded feature for each candidate

Implement `toy_app.slugify(value: str) -> str` using Python 3.12 standard library only.

- Accept only `str`; `TypeError` on any other input.
- Lowercase ASCII letters A–Z.
- Treat runs of whitespace as one hyphen; trim leading/trailing whitespace.
- Reject characters outside ASCII letters, ASCII digits, hyphen and whitespace with `ValueError`; no Unicode transliteration.
- Collapse repeated hyphens to one and strip leading/trailing hyphens.
- Empty/whitespace-only input returns an empty string.
- Keep implementation deterministic, side-effect free and independent of an LLM at runtime.
- Do **not** change `candidate_tests/`, `scenarios.yaml` or acceptance rules.

Start at a pinned fixture baseline SHA. Run:

```bash
python -m unittest discover -s candidate_tests -v
```

The tests intentionally fail at baseline until an agent implements this feature. Capture new commit, PR, CI, head SHA and base SHA; verify subscriptions for **both** Claude Code and Codex CLI on the user's authorized machine. No API key and no forced auto-merge.
