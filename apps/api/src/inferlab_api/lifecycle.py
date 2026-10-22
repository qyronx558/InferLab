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


def check_transition(
    current: JobPhase, target: JobPhase, *, retry_authorized: bool = False
) -> None:
    # Worker-only rescheduling: the failed attempt, confirmed engine stop,
    # backoff, remaining deadline and two-attempt cap are enforced by WorkerStore.
    if retry_authorized and current in {"leased", "running"} and target == "queued":
        return
    if target not in TRANSITIONS[current]:
        raise APIError(409, "invalid_transition", "Job transition is not allowed.")
