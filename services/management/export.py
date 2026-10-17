"""Records export (V6.26): the owner's copy of the organization's records as one JSON file.

What's in it: missions, tasks, approvals, owner decisions, the charter and its amendments, schedules, run-again and
follow-on links, the team roster, and recent events with their audit-chain links, plus a fresh check of the whole chain
and `bundle_sha256`: the SHA-256 of the bundle without that field, as compact JSON with sorted keys (the file itself is
indented for reading, so recompute it from the parsed JSON, not from the file's bytes). What's left out, on purpose: money records (bank, ledger, financial approvals),
encrypted credentials and anything in the environment. Every export is itself recorded as an event.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.engine import Connection

from services.core import audit, db

MAX_MISSIONS = 1000
MAX_EVENTS = 5000
EXCLUDED = ["money records (bank, ledger, financial approvals, finance events)", "encrypted credentials and connection secrets",
            "settings held in the server's environment"]


def _rows(conn: Connection, q) -> list[dict]:
    return [dict(r._mapping) for r in conn.execute(q).fetchall()]


def build(conn: Connection, org_id: str, by_user: str) -> dict:
    from services.management import charter, schedules
    from services.core.roster import team
    M = db.missions
    missions = _rows(conn, select(M).where(M.c.organization_id == org_id).order_by(M.c.created_at.desc()).limit(MAX_MISSIONS))
    ids = [m["id"] for m in missions]
    T = db.tasks
    tasks = _rows(conn, select(T.c.id, T.c.mission_id, T.c.agent_id, T.c.title, T.c.status, T.c.district, T.c.created_at, T.c.updated_at)
                  .where(T.c.organization_id == org_id, T.c.mission_id.in_(ids))) if ids else []
    E, C = db.events, db.event_chain
    events = _rows(conn, select(E, C.c.hash.label("chain_hash"), C.c.prev_hash.label("chain_prev"))
                   .outerjoin(C, (C.c.organization_id == E.c.organization_id) & (C.c.sequence == E.c.sequence))
                   .where(E.c.organization_id == org_id, E.c.event_type.notlike("finance.%")).order_by(E.c.sequence.desc()).limit(MAX_EVENTS))[::-1]
    for e in events:
        e["payload"] = e.get("payload") or {}
    org = conn.execute(select(db.organizations.c.id, db.organizations.c.name).where(db.organizations.c.id == org_id)).first()
    bundle = {
        "format": "aiciv.org-export.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": by_user,
        "organization": dict(org._mapping) if org else {"id": org_id},
        "limits": {"missions": MAX_MISSIONS, "events": MAX_EVENTS, "missions_included": len(missions), "events_included": len(events)},
        "excluded": EXCLUDED,
        "how_to_check": "bundle_sha256 = SHA-256 of this JSON without the bundle_sha256 field, serialized with sorted keys, "
                        "no spaces (separators ',' and ':') and UTF-8 text. The audit section is a fresh check of the whole "
                        "event chain; each event carries its chain_hash and chain_prev.",
        "missions": missions,
        "tasks": tasks,
        "approvals": _rows(conn, select(db.approvals).where(db.approvals.c.organization_id == org_id)),
        "owner_decisions": _rows(conn, select(db.owner_decisions).where(db.owner_decisions.c.organization_id == org_id)),
        "charter": charter.view(conn, org_id),
        "schedules": schedules.listing(conn, org_id),
        "mission_links": _rows(conn, select(db.mission_links).where(db.mission_links.c.organization_id == org_id)),
        "team": team(conn, org_id, by_user)["members"],
        "events": events,
        "events_chain": audit.check_links(events),
        "audit": audit.verify(conn, org_id),
    }
    body = json.dumps(bundle, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
    bundle["bundle_sha256"] = hashlib.sha256(body.encode()).hexdigest()
    return bundle
