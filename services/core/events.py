"""Event persistence + transactional outbox.

`emit` must be called inside `transaction()`; it writes the events row and the outbox row in the
same database transaction as whatever state change caused the event. The publisher (realtime.py)
only ever reads the outbox, so a crash between commit and publish loses nothing: the row is
picked up on the next poll.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import func, insert, select
from sqlalchemy.engine import Connection

from . import db
from .config import load_seed

ORG_ID = load_seed()["organization_id"]


@contextmanager
def transaction() -> Iterator[Connection]:
    with db.write_lock:
        with db.get_engine().begin() as conn:
            yield conn


def next_sequence(conn: Connection, org_id: str) -> int:
    cur = conn.execute(select(func.max(db.events.c.sequence)).where(db.events.c.organization_id == org_id)).scalar()
    return int(cur or 0) + 1


def emit(
    conn: Connection,
    event_type: str,
    *,
    mission_id: str | None = None,
    agent_id: str | None = None,
    payload: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    execution_mode: str = "live",
    org_id: str = ORG_ID,
) -> dict:
    event_id = db.new_id()
    row = dict(
        id=event_id,
        organization_id=org_id,
        sequence=next_sequence(conn, org_id),
        mission_id=mission_id,
        agent_id=agent_id,
        event_type=event_type,
        schema_version=1,
        correlation_id=correlation_id or mission_id or event_id,
        execution_mode=execution_mode,
        payload=payload or {},
        occurred_at=db.utcnow(),
    )
    conn.execute(insert(db.events).values(**row))
    from .audit import link
    link(conn, row)  # chain it to the previous event in the same transaction (tamper-evident log)
    conn.execute(insert(db.event_outbox).values(event_id=event_id, organization_id=org_id))
    return to_envelope(row)


def to_envelope(row: Any) -> dict:
    r = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    return {
        "event_id": r["id"],
        "schema_version": r["schema_version"],
        "organization_id": r["organization_id"],
        "mission_id": r["mission_id"],
        "agent_id": r["agent_id"],
        "event_type": r["event_type"],
        "sequence": r["sequence"],
        "occurred_at": r["occurred_at"],
        "correlation_id": r["correlation_id"],
        "payload": r["payload"] or {},
        "execution_mode": r["execution_mode"],
    }


def events_after(conn: Connection, after_sequence: int, limit: int = 500, org_id: str = ORG_ID,
                 mission_id: str | None = None) -> list[dict]:
    q = select(db.events).where(db.events.c.organization_id == org_id, db.events.c.sequence > after_sequence)
    if mission_id:
        q = q.where(db.events.c.mission_id == mission_id)
    rows = conn.execute(q.order_by(db.events.c.sequence).limit(limit)).fetchall()
    return [to_envelope(r) for r in rows]
