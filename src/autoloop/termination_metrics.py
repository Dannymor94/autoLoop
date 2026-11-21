"""Observed (not inferred) post-acceptance agent-step waste metrics."""

from __future__ import annotations

import re
from typing import Any, Iterable


_SHA = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


def observed_termination_lag(events: Iterable[dict[str, Any]]) -> dict[str, int | None]:
    """Require trusted acceptance checks at an exact Git tree and suite SHA.

    Events are produced by a deterministic observer, not taken on faith from
    an agent's natural language output. Without independent checks, both
    numbers remain UNKNOWN (None).
    """
    final_step: int | None = None
    first_pass: int | None = None
    for event in events:
        kind = event.get("type")
        step = event.get("agent_step")
        if kind not in {"agent.step", "acceptance.checked"} or isinstance(step, bool) or not isinstance(step, int) or step < 0:
            continue
        if final_step is not None and step < final_step:
            return {"first_observed_pass_step": None, "final_step": None, "termination_lag_observed": None}
        final_step = step
        if kind == "acceptance.checked" and event.get("pass") is True:
            if _SHA.fullmatch(str(event.get("tested_tree_sha", ""))) and _FINGERPRINT.fullmatch(str(event.get("suite_fingerprint", ""))) and event.get("trusted_verifier") is True:
                if first_pass is None:
                    first_pass = step
    if final_step is None or first_pass is None:
        return {"first_observed_pass_step": None, "final_step": final_step, "termination_lag_observed": None}
    return {"first_observed_pass_step": first_pass, "final_step": final_step, "termination_lag_observed": final_step - first_pass}
