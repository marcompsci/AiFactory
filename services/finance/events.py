"""Finance events: the 3D city and activity feed see *that* something happened, never the money (THREAT_MODEL F9)."""
from __future__ import annotations

from sqlalchemy.engine import Connection

from services.core.events import emit

from .redaction import event_safe

PACKET_TRANSITIONS = {
    "SUBMITTED": {"AT_BANK", "CLOSED"},
    "AT_BANK": {"RESEARCH_REQUESTED", "FINDINGS_RETURNED", "CLOSED"},   # FINDINGS_RETURNED directly: legal obligations are not shopped
    "RESEARCH_REQUESTED": {"RESEARCHING", "CLOSED"},
    "RESEARCHING": {"FINDINGS_RETURNED", "CLOSED"},
    "FINDINGS_RETURNED": {"GM_REVIEW", "OWNER_DECISION", "CLOSED"},
    "GM_REVIEW": {"OWNER_DECISION", "RESEARCH_REQUESTED", "REJECTED", "CLOSED"},
    "OWNER_DECISION": {"APPROVED", "REJECTED", "DEFERRED", "RESEARCH_REQUESTED", "CLOSED"},
    "DEFERRED": {"OWNER_DECISION", "RESEARCH_REQUESTED", "CLOSED"},
    "APPROVED": {"EXECUTED", "DEFERRED", "CLOSED"},   # DEFERRED when the approval expired before it could be executed
    "EXECUTED": set(),
    "REJECTED": set(),
    "CLOSED": set(),
}


class BadTransition(ValueError):
    pass


def check_packet_transition(current: str, target: str) -> None:
    if target not in PACKET_TRANSITIONS.get(current, set()):
        raise BadTransition(f"cost review packet cannot go from {current} to {target}")


def femit(conn: Connection, event_type: str, payload: dict, *, agent_id: str | None = None, mission_id: str | None = None,
          simulated: bool = False) -> dict:
    assert event_type.startswith("finance."), event_type
    return emit(conn, event_type, agent_id=agent_id, mission_id=mission_id, payload=event_safe(payload),
                execution_mode="simulation" if simulated else "live")
