"""Explicit state machines. Every status write goes through `assert_transition`."""
from __future__ import annotations


class InvalidTransition(ValueError):
    pass


MISSION_TRANSITIONS: dict[str, set[str]] = {
    "CREATED": {"VALIDATING", "CANCELLED"},
    "VALIDATING": {"PLANNING", "FAILED", "CANCELLED"},
    "PLANNING": {"QUEUED", "FAILED", "CANCELLED"},
    "QUEUED": {"RUNNING", "CANCELLED"},
    "RUNNING": {"WAITING_FOR_APPROVAL", "COMPLETED", "FAILED", "CANCELLED"},
    "WAITING_FOR_APPROVAL": {"RUNNING", "FAILED", "CANCELLED"},
    "COMPLETED": set(),
    "FAILED": set(),
    "CANCELLED": set(),
}
MISSION_TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}

TASK_TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"RUNNING", "CANCELLED", "SKIPPED"},
    "RUNNING": {"COMPLETED", "FAILED", "WAITING_FOR_APPROVAL", "CANCELLED", "PENDING", "SKIPPED"},  # PENDING = retry
    "WAITING_FOR_APPROVAL": {"RUNNING", "FAILED", "CANCELLED", "SKIPPED"},  # SKIPPED = reviewer rejected
    "COMPLETED": {"PENDING"},  # re-opened when downstream verification sends work back

    "FAILED": {"PENDING"},  # retry policy may re-queue
    "CANCELLED": set(),
    "SKIPPED": set(),
}

# Execution state only. Movement (MOVING/STATIONARY) lives in agent_positions and is never an execution state.
AGENT_TRANSITIONS: dict[str, set[str]] = {
    "IDLE": {"ASSIGNED"},
    "ASSIGNED": {"PLANNING", "EXECUTING", "CANCELLED", "IDLE"},
    "PLANNING": {"EXECUTING", "WAITING_FOR_AGENT", "FAILED", "CANCELLED"},
    "EXECUTING": {"WAITING_FOR_TOOL", "WAITING_FOR_AGENT", "WAITING_FOR_APPROVAL", "REVIEWING", "COMPLETED", "FAILED", "CANCELLED"},
    "WAITING_FOR_TOOL": {"EXECUTING", "FAILED", "CANCELLED"},
    "WAITING_FOR_AGENT": {"EXECUTING", "FAILED", "CANCELLED"},
    "WAITING_FOR_APPROVAL": {"EXECUTING", "FAILED", "CANCELLED"},
    "REVIEWING": {"EXECUTING", "COMPLETED", "FAILED", "CANCELLED"},
    "COMPLETED": {"IDLE", "ASSIGNED"},
    "FAILED": {"IDLE", "ASSIGNED"},
    "CANCELLED": {"IDLE", "ASSIGNED"},
}


def assert_transition(kind: str, current: str, target: str) -> None:
    table = {"mission": MISSION_TRANSITIONS, "task": TASK_TRANSITIONS, "agent": AGENT_TRANSITIONS}[kind]
    if current == target:
        return
    if current not in table:
        raise InvalidTransition(f"unknown {kind} state {current!r}")
    if target not in table[current]:
        raise InvalidTransition(f"{kind}: {current} -> {target} is not allowed")
