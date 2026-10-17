"""Tamper-evident event log: every event is chained to the one before it with SHA-256.

When an event is written, its link stores hash(previous link's hash + the event's canonical JSON), in the same
transaction. Editing, deleting or reordering any event afterwards breaks every link from that point on, and
`verify` reports the first place it breaks. The chain table itself is append-only (a trigger in Postgres and in
SQLite refuses updates and deletes). This makes tampering evident; it doesn't stop someone with database access
from rewriting the whole chain, which is why the latest hash is shown to you so you can note it down.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.engine import Connection

from . import db

GENESIS = "0" * 64
BATCH = 2000


def normalize(payload: Any) -> Any:
    """The payload as every database will read it back: string keys, no -0.0, and integer-valued big floats as
    integers (Postgres jsonb stores numbers as numeric). Stored and hashed in this form, so verification is exact."""
    def fix(v: Any) -> Any:
        if isinstance(v, dict):
            return {str(k): fix(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [fix(x) for x in v]
        if isinstance(v, float):
            if v == 0:
                return 0.0
            if v.is_integer() and abs(v) >= 1e15:
                return int(v)
        return v
    return fix(json.loads(json.dumps(payload, default=str)))


def canonical(e: dict) -> str:
    """The fields that make up an event, in a fixed form (sorted keys, no whitespace)."""
    keep = ("id", "organization_id", "sequence", "mission_id", "agent_id", "event_type", "schema_version", "correlation_id",
            "execution_mode", "payload", "occurred_at")
    return json.dumps({k: e.get(k) for k in keep}, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def digest(prev: str, e: dict) -> str:
    return hashlib.sha256((prev + canonical(e)).encode()).hexdigest()


def link(conn: Connection, row: dict) -> str:
    """Chain a just-written event (called by events.emit inside the same transaction)."""
    prev = conn.execute(select(db.event_chain.c.hash).where(db.event_chain.c.organization_id == row["organization_id"],
                                                            db.event_chain.c.sequence == row["sequence"] - 1)).scalar()
    prev = prev or GENESIS  # the first event, or the first one written after this feature arrived
    h = digest(prev, row)
    conn.execute(insert(db.event_chain).values(organization_id=row["organization_id"], sequence=row["sequence"], event_id=row["id"],
                                               prev_hash=prev, hash=h))
    return h


def _as_dict(r: Any) -> dict:
    d = dict(r._mapping)
    d["payload"] = d.get("payload") or {}
    return d


def verify(conn: Connection, org_id: str) -> dict:
    """Recompute every link. Reports the first event that was changed, removed or never chained."""
    first = conn.execute(select(db.event_chain.c.sequence).where(db.event_chain.c.organization_id == org_id)
                         .order_by(db.event_chain.c.sequence).limit(1)).scalar()
    if first is None:
        return {"ok": True, "checked": 0, "from_sequence": None, "latest_hash": None, "problem": None,
                "note": "No chained events yet."}
    prev, checked, after, last_hash = None, 0, first - 1, None
    while True:
        links = conn.execute(select(db.event_chain).where(db.event_chain.c.organization_id == org_id, db.event_chain.c.sequence > after)
                             .order_by(db.event_chain.c.sequence).limit(BATCH)).fetchall()
        if not links:
            break
        seqs = [l.sequence for l in links]
        events = {e.sequence: _as_dict(e) for e in conn.execute(select(db.events).where(db.events.c.organization_id == org_id,
                                                                                         db.events.c.sequence.in_(seqs))).fetchall()}
        for l in links:
            if prev is not None and l.sequence != after + 1:
                return _broken(checked, first, f"links {after + 1}–{l.sequence - 1} are missing", after + 1, last_hash)
            expected_prev = prev if prev is not None else l.prev_hash  # the first link starts from whatever it recorded
            if l.prev_hash != expected_prev:
                return _broken(checked, first, "a link doesn't point at the one before it", l.sequence, last_hash)
            e = events.get(l.sequence)
            if e is None:
                return _broken(checked, first, "the event was deleted", l.sequence, last_hash)
            if e["id"] != l.event_id or digest(l.prev_hash, e) != l.hash:
                return _broken(checked, first, "the event was changed after it was written", l.sequence, last_hash)
            prev, after, last_hash = l.hash, l.sequence, l.hash
            checked += 1
    # an event with no link at all (one written while we were checking has its link: it arrives in the same transaction)
    unchained = conn.execute(select(db.events.c.sequence)
                             .outerjoin(db.event_chain, (db.event_chain.c.organization_id == db.events.c.organization_id)
                                        & (db.event_chain.c.sequence == db.events.c.sequence))
                             .where(db.events.c.organization_id == org_id, db.events.c.sequence > after,
                                    db.event_chain.c.sequence.is_(None))
                             .order_by(db.events.c.sequence).limit(1)).scalar()
    if unchained is not None:
        return _broken(checked, first, "an event exists that was never chained", unchained, last_hash)
    return {"ok": True, "checked": checked, "from_sequence": first, "latest_sequence": after, "latest_hash": last_hash, "problem": None,
            "note": "Every event since the chain began matches its link." + (f" Events before #{first} predate the chain." if first > 1 else "")}


_LAST: dict[str, tuple[float, dict]] = {}
MIN_INTERVAL = 10.0  # a full check reads every event; one per organization every 10 seconds is plenty


def verify_throttled(conn: Connection, org_id: str) -> dict:
    import time
    now = time.monotonic()
    latest = conn.execute(select(db.events.c.sequence).where(db.events.c.organization_id == org_id)
                          .order_by(db.events.c.sequence.desc()).limit(1)).scalar()
    hit = _LAST.get(org_id)
    if hit and now - hit[0] < MIN_INTERVAL and hit[1].get("_latest") == latest:
        return {**{k: v for k, v in hit[1].items() if k != "_latest"}, "cached": True}
    res = verify(conn, org_id)
    _LAST[org_id] = (now, {**res, "_latest": latest})
    return {**res, "cached": False}


def check_links(events: list[dict]) -> dict:
    """A mission's own events against their links (each link's hash recomputed from its event and recorded prev)."""
    bad = next((e["sequence"] for e in events if not e.get("chain_hash") or digest(e["chain_prev"], e) != e["chain_hash"]), None)
    return {"ok": bad is None, "checked": len(events), "problem_sequence": bad,
            "note": "Every event in this file matches its link." if bad is None else f"Event #{bad} doesn't match its link."}


def _broken(checked: int, first: int, why: str, at: int, last_hash: str | None) -> dict:
    return {"ok": False, "checked": checked, "from_sequence": first, "latest_hash": last_hash,
            "problem": {"sequence": at, "reason": why}, "note": f"The log was altered at event #{at}: {why}."}


def mission_export(conn: Connection, mission_id: str) -> dict:
    """Everything about one mission, with each event's chain link, and a hash of the whole bundle."""
    from services.management import recovery, reliability
    from services.management.trace import mission_trace
    m = conn.execute(select(db.missions).where(db.missions.c.id == mission_id)).first()
    rows = conn.execute(select(db.events, db.event_chain.c.hash.label("chain_hash"), db.event_chain.c.prev_hash.label("chain_prev"))
                        .outerjoin(db.event_chain, (db.event_chain.c.organization_id == db.events.c.organization_id)
                                   & (db.event_chain.c.sequence == db.events.c.sequence))
                        .where(db.events.c.mission_id == mission_id).order_by(db.events.c.sequence)).fetchall()
    events = [{**_as_dict(r)} for r in rows]
    bundle = {"format": "aiciv.mission-audit.v1", "mission": dict(m._mapping), "trace": mission_trace(conn, mission_id),
              "objective": reliability.objective_for(conn, mission_id), "recovery": recovery.plans(conn, m.organization_id, mission_id=mission_id),
              "events": events, "chain": check_links(events),
              "latest_link": conn.execute(select(db.event_chain.c.sequence, db.event_chain.c.hash)
                                          .where(db.event_chain.c.organization_id == m.organization_id)
                                          .order_by(db.event_chain.c.sequence.desc()).limit(1)).first()._asdict()
              if conn.execute(select(db.event_chain.c.sequence).where(db.event_chain.c.organization_id == m.organization_id).limit(1)).first()
              else None}
    body = json.dumps(bundle, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
    bundle["bundle_sha256"] = hashlib.sha256(body.encode()).hexdigest()
    return bundle
