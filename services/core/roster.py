"""Who has signed in to this organization, with the role they had at their latest sign-in (V6.24).

Roles come from each sign-in (Supabase app_metadata or the owner email list), so the server never held a list of
owners. This roster is that list, as last seen: work that acts later on someone's behalf (a schedule, a follow-on)
checks it, so a person who is no longer an owner stops having things run in their name. A role change is written at
once; otherwise a sign-in is written at most every few minutes, so this adds no write to most requests.
"""
from __future__ import annotations

import logging
import threading
import time

from sqlalchemy import insert, select, update

log = logging.getLogger("aiciv.roster")

REFRESH_SECONDS = 300
_seen: dict[tuple[str, str], tuple[str, float]] = {}
_lock = threading.Lock()


def clear() -> None:
    with _lock:
        _seen.clear()


def record(org_id: str, user_id: str, role: str, mode: str, email: str | None = None) -> None:
    key = (org_id, user_id)
    now = time.monotonic()
    with _lock:
        hit = _seen.get(key)
        if hit and hit[0] == role and now - hit[1] < REFRESH_SECONDS:
            return
        _seen[key] = (role, now)
    try:
        from . import db
        from .events import emit, transaction
        M = db.org_members
        with transaction() as conn:
            row = conn.execute(select(M.c.role).where(M.c.organization_id == org_id, M.c.user_id == user_id)).first()
            if row is None:
                conn.execute(insert(M).values(organization_id=org_id, user_id=user_id, role=role, mode=mode, email=email))
                emit(conn, "team.member_seen", org_id=org_id, payload={"user_id": user_id, "role": role})
            else:
                values = {"role": role, "mode": mode, "last_seen": db.utcnow()}
                if email:
                    values["email"] = email
                conn.execute(update(M).where(M.c.organization_id == org_id, M.c.user_id == user_id).values(**values))
                if row.role != role:
                    emit(conn, "team.role_changed", org_id=org_id, payload={"user_id": user_id, "from": row.role, "to": role})
    except Exception:  # the roster must never block a sign-in (e.g. before the database is ready)
        with _lock:
            _seen.pop(key, None)
        log.debug("couldn't record sign-in", exc_info=True)


def team(conn, org_id: str, me: str) -> dict:
    from . import db
    M, S = db.org_members, db.mission_schedules
    counts: dict[str, int] = {}
    for r in conn.execute(select(S.c.created_by, S.c.enabled).where(S.c.organization_id == org_id)).fetchall():
        if r.enabled:
            counts[r.created_by] = counts.get(r.created_by, 0) + 1
    members = [{"user_id": r.user_id, "role": r.role, "mode": r.mode, "email": r.email, "first_seen": r.first_seen,
                "last_seen": r.last_seen, "you": r.user_id == me, "active_schedules": counts.get(r.user_id, 0)}
               for r in conn.execute(select(M).where(M.c.organization_id == org_id).order_by(M.c.last_seen.desc())).fetchall()]
    orphaned = [{"schedule_id": r.id, "title": r.title, "created_by": r.created_by} for r in conn.execute(
        select(S.c.id, S.c.title, S.c.created_by).where(S.c.organization_id == org_id, S.c.enabled == 1)).fetchall()
        if not any(m["user_id"] == r.created_by and m["role"] == "owner" for m in members)]
    return {"members": members, "schedules_without_an_owner": orphaned,
            "note": "Roles are as of each person's latest sign-in. Schedules run only while their creator is still an owner."}
