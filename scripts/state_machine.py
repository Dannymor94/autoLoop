"""Pure transition resolver; persistence, leases and side effects belong to AL-102."""

from __future__ import annotations


class TransitionRejected(ValueError):
    pass


def transition_target(states: dict, *, current_state: str, event: str, satisfied_guards: set[str]) -> str:
    """Only a declared event with every required guard may advance the state.

    This function does not *evaluate* guards or issue commands. The dispatcher
    must verify task_version, lease fencing and the evidence/approval gates.
    """
    matches = [
        transition
        for transition in states["transitions"]
        if transition["from"] == current_state and transition["event"] == event
    ]
    if len(matches) != 1:
        raise TransitionRejected(f"undeclared or ambiguous transition: {current_state}/{event}")
    missing = set(matches[0]["guards"]) - satisfied_guards
    if missing:
        raise TransitionRejected(f"unsatisfied guards: {', '.join(sorted(missing))}")
    return matches[0]["to"]
