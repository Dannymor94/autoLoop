"""Regenerate only marked AGENTS.md / CLAUDE.md sections from contracts."""

from __future__ import annotations

import argparse
from pathlib import Path

from contract_data import ROOT, load_contracts
from evidence_contract import sha256_canonical


BEGIN = "<!-- BEGIN AUTOLOOP-GENERATED RULES -->"
END = "<!-- END AUTOLOOP-GENERATED RULES -->"
DOCS = ("AGENTS.md", "CLAUDE.md")


def render_generated_block(contracts: dict) -> str:
    states = contracts["states"]
    limits = contracts["limits"]
    policies = contracts["policies"]
    protected = contracts["protected_paths"]
    required_report = contracts["report"]["required"]
    digest = sha256_canonical(contracts)

    lines = [
        BEGIN,
        "## autoLoop contract rules (generated; do not edit this section)",
        "",
        f"Contract digest: `{digest}`. Source of truth: `contracts/`.",
        "",
        "### Ownership and security",
        "",
        "- autoLoop owns queue, leases, fencing, canonical task state, repair counts, QA verdicts and merge/close.",
        "- The OSS platform executes only one expressly requested attempt; its run completion does not mean task DONE.",
        "- Never auto-merge, auto-close, claim another task or run an autonomous repair loop from an executor.",
        "- Independent QA requires a fresh context, read-only source checkout, and no GitHub push/merge credentials.",
        "- A stale head, base, tested tree, acceptance spec or suite fingerprint invalidates a prior QA PASS.",
        "- Repeated failure fingerprint across attempts means immediate ESCALATED, even with repair budget left.",
        "- Owner Stop is STOP_PENDING until executor acknowledgement; only confirmed Stop yields BLOCKED(reason=OWNER_STOP).",
        "- Never fabricate token quota, context usage, CI results, QA outcomes or platform compliance.",
        "",
        "### Canonical task states",
        "",
    ]
    for state, definition in states["states"].items():
        terminal = "terminal" if definition["terminal"] else "nonterminal"
        lines.append(f"- `{state}` ({terminal}): {definition['description']}")

    lines.extend(["", "### Allowed transitions (event / required guards)", "", "| From | Event | To | Required guards |", "| --- | --- | --- | --- |"])
    for transition in states["transitions"]:
        guards = ", ".join(f"`{g}`" for g in transition["guards"])
        lines.append(
            f"| `{transition['from']}` | `{transition['event']}` | `{transition['to']}` | {guards} |"
        )

    lines.extend(
        [
            "",
            "### Limits and protected paths",
            "",
            f"- Max repair cycles: **{limits['repair']['max_repair_cycles']}**.",
            f"- Repeated failure immediately escalates: **{str(limits['repair']['escalate_on_repeated_failure_fingerprint']).lower()}**.",
            f"- Context checkpoint suggestion: **{limits['context']['checkpoint_suggest_percent']}%**; prepare new session: **{limits['context']['prepare_new_session_percent']}%**.",
            f"- Maximum dispatcher writers: **{limits['dispatcher']['max_writers']}**; storage: **{policies['storage']['backend']}/{policies['storage']['journal_mode']}**.",
            f"- Protected-path rule: `{protected['policy']}`. Paths:",
        ]
    )
    for path in protected["paths"]:
        lines.append(f"  - `{path}`")
    lines.extend(["", "### Required attempt report fields", ""])
    lines.append("Include machine-readable fields: " + ", ".join(f"`{field}`" for field in required_report) + ".")
    lines.append("Unknown token counts or subscription balance must be `null`, never guessed.")
    lines.append("Agents cannot authorize transitions by changing their own reports; autoLoop checks every guard.")
    lines.extend(["", END])
    return "\n".join(lines)


def replace_block(existing: str, block: str) -> str:
    if BEGIN not in existing and END not in existing:
        return existing.rstrip("\n") + "\n\n" + block + "\n"
    if existing.count(BEGIN) != 1 or existing.count(END) != 1:
        raise ValueError("missing, duplicate or unmatched generated-section markers")
    start = existing.index(BEGIN)
    end = existing.index(END) + len(END)
    if end <= start:
        raise ValueError("generated-section markers are out of order")
    return existing[:start] + block + existing[end:]


def check_or_write(root: Path, *, check: bool) -> list[str]:
    block = render_generated_block(load_contracts(root))
    changed: list[str] = []
    for name in DOCS:
        path = root / name
        if not path.is_file():
            if check:
                changed.append(name)
                continue
            existing = f"# {name}\n\nRead this file before working in this repository.\n"
        else:
            existing = path.read_text(encoding="utf-8")
        expected = replace_block(existing, block)
        if existing != expected:
            changed.append(name)
            if not check:
                path.write_text(expected, encoding="utf-8")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if agent documents differ from contracts")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    changed = check_or_write(args.root, check=args.check)
    if args.check and changed:
        print("Generated agent document drift: " + ", ".join(changed))
        return 1
    print("Agent documents in sync" if not changed else "Updated: " + ", ".join(changed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
