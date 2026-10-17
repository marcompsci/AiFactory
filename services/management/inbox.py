"""The owner's inbox: everything that is waiting for a decision, in one list.

Mission approvals, recovery plans, releases at the Owner's Tower, money approvals and (once there's enough history)
permission suggestions. Sorted so that what expires soonest comes first, then what has waited longest. Nothing here
decides anything: each item links to the screen where you decide it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.engine import Connection

from services.core import db

from .recovery import EXPIRES_AFTER


def _age_min(iso: str | None, now: datetime) -> int | None:
    try:
        return max(0, int((now - datetime.fromisoformat(iso)).total_seconds() // 60)) if iso else None
    except ValueError:
        return None


def inbox(conn: Connection, org_id: str) -> dict:
    now = datetime.now(timezone.utc)
    items: list[dict] = []
    for a in conn.execute(select(db.approvals).where(db.approvals.c.organization_id == org_id, db.approvals.c.status == "PENDING")
                          .limit(200)).fetchall():
        title = conn.execute(select(db.missions.c.title).where(db.missions.c.id == a.mission_id)).scalar()
        items.append({"kind": "approval", "id": a.id, "title": a.summary or a.action.replace("_", " "), "detail": title,
                      "mission_id": a.mission_id, "created_at": a.created_at, "expires_at": None})
    for r in conn.execute(select(db.recovery_plans, db.missions.c.title.label("mt"))
                          .join(db.missions, db.missions.c.id == db.recovery_plans.c.mission_id)
                          .where(db.recovery_plans.c.organization_id == org_id, db.recovery_plans.c.status == "PENDING").limit(200)).fetchall():
        exp = (datetime.fromisoformat(r.created_at) + EXPIRES_AFTER).isoformat() if r.created_at else None
        items.append({"kind": "recovery_plan", "id": r.id, "title": r.summary, "detail": r.mt, "mission_id": r.mission_id,
                      "created_at": r.created_at, "expires_at": exp})
    for o in conn.execute(select(db.opportunities.c.id, db.opportunities.c.title, db.opportunities.c.updated_at)
                          .where(db.opportunities.c.organization_id == org_id, db.opportunities.c.status == "OWNER_APPROVAL").limit(200)).fetchall():
        items.append({"kind": "release", "id": o.id, "title": f"Release decision: {o.title}", "detail": "Waiting at the Owner's Tower",
                      "mission_id": None, "created_at": o.updated_at, "expires_at": None})
    for f in conn.execute(select(db.financial_approvals).where(db.financial_approvals.c.organization_id == org_id,
                                                              db.financial_approvals.c.status == "REQUESTED").limit(200)).fetchall():
        amount = f"{f.amount_minor / 100:.2f} {f.currency}" if f.amount_minor is not None else ""
        items.append({"kind": "money", "id": f.id, "title": f"{f.action_type.replace('_', ' ').capitalize()} {amount}".strip(),
                      "detail": f.recipient or "", "mission_id": None, "created_at": f.created_at, "expires_at": f.expires_at,
                      "simulated": f.data_mode != "live" if f.data_mode else None})
    from .permissions_review import review
    pr = review(conn, org_id)
    if pr["suggestions"]:
        items.append({"kind": "permissions", "id": "permissions", "title": f"{pr['suggestions']} unused tool grant(s) to review",
                      "detail": "Least-privilege review", "mission_id": None, "created_at": None, "expires_at": None})
    for i in items:
        i["age_minutes"] = _age_min(i["created_at"], now)
        try:
            left = (datetime.fromisoformat(i["expires_at"]) - now).total_seconds() / 3600 if i["expires_at"] else None
        except ValueError:
            left = None
        i["hours_left"] = round(left, 1) if left is not None else None
        i["urgent"] = left is not None and left <= 24
    far = (now + timedelta(days=3650)).isoformat()
    items.sort(key=lambda i: (i["expires_at"] or far, i["created_at"] or far))
    counts: dict[str, int] = {}
    for i in items:
        counts[i["kind"]] = counts.get(i["kind"], 0) + 1
    return {"items": items, "total": len(items), "counts": counts, "urgent": sum(i["urgent"] for i in items)}
