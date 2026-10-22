"""Job transition policy. No lease scheduler or benchmark execution lives here."""

from .contracts import JobPhase
from .errors import APIError

TRANSITIONS: dict[JobPhase, frozenset[JobPhase]] = {
    "queued": frozenset({"leased", "cancelled"}),
    "leased": frozenset({"running", "failed", "cancelled"}),
    "running": frozenset({"completed", "failed", "cancelled"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}


def check_transition(current: JobPhase, target: JobPhase) -> None:
    if target not in TRANSITIONS[current]:
        raise APIError(409, "invalid_transition", "Job transition is not allowed.")
