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


# V4.0 OpportunityPacket workflow. Rejection, revision, cancellation, deferral and retry paths are explicit.
OPPORTUNITY_TRANSITIONS: dict[str, set[str]] = {
    "RESEARCHED": {"MANAGER_REVIEW", "CANCELLED"},
    "MANAGER_REVIEW": {"ROUTED", "REJECTED", "CANCELLED"},
    "ROUTED": {"DEPARTMENT_ACCEPTED", "MANAGER_REVIEW", "CANCELLED"},          # department may hand it back
    "DEPARTMENT_ACCEPTED": {"IN_PRODUCTION", "CANCELLED"},
    "IN_PRODUCTION": {"QUALITY_REVIEW", "REVISION_REQUESTED", "REJECTED", "CANCELLED"},
    "QUALITY_REVIEW": {"MANAGER_APPROVAL", "REVISION_REQUESTED", "CANCELLED"},
    "MANAGER_APPROVAL": {"OWNER_APPROVAL", "REVISION_REQUESTED", "REJECTED", "CANCELLED"},
    "OWNER_APPROVAL": {"RELEASE_AUTHORIZED", "REVISION_REQUESTED", "REJECTED", "DEFERRED", "MANAGER_APPROVAL", "CANCELLED"},
    "RELEASE_AUTHORIZED": {"MANAGER_APPROVAL"},                                  # invalidated: artifact changed after approval
    "REVISION_REQUESTED": {"IN_PRODUCTION", "REJECTED", "CANCELLED"},
    "DEFERRED": {"OWNER_APPROVAL", "CANCELLED"},
    "REJECTED": {"MANAGER_REVIEW"},                                               # owner/GM may reopen (retry)
    "CANCELLED": set(),
}

PACKAGE_TRANSITIONS: dict[str, set[str]] = {
    "QUEUED": {"IN_TRANSIT", "DELIVERY_FAILED", "CANCELLED"},
    "IN_TRANSIT": {"IN_TRANSIT", "ARRIVED", "DELIVERY_FAILED", "CANCELLED"},     # IN_TRANSIT -> IN_TRANSIT = reroute
    "DELIVERY_FAILED": {"IN_TRANSIT", "CANCELLED"},
    "ARRIVED": {"RECEIVED"},
    "RECEIVED": set(),
    "CANCELLED": set(),
}


def assert_v4_transition(kind: str, current: str, target: str) -> None:
    table = {"opportunity": OPPORTUNITY_TRANSITIONS, "package": PACKAGE_TRANSITIONS}[kind]
    if current == target and kind == "opportunity":
        return
    if target not in table.get(current, set()):
        raise InvalidTransition(f"{kind}: {current} -> {target} is not allowed")
