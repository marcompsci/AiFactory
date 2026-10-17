"""Saved requests (V6.29): name a mission request once, start it whenever you like.

A saved request holds what a person would type to start a mission (a test fix, a test run or market research), checked
when it's saved with the same checks it faces when it starts. Starting one goes through the same functions as starting
a mission by hand, so the emergency stop, charter caps and approvals all apply, and it starts as the person who presses
start (never as whoever saved it).
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from services.core import db
from services.core.auth import Principal
from services.core.events import emit, transaction

from . import links

MAX_SAVED = 50
DOUBLE_TAP = timedelta(seconds=10)


class SavedError(ValueError):
    def __init__(self, msg: str, status: int = 422) -> None:
        super().__init__(msg)
        self.status = status


def _key(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _row(conn: Connection, org: str, sid: str):
    try:
        uuid.UUID(str(sid))
    except ValueError as exc:
        raise SavedError("saved request not found", 404) from exc
    r = conn.execute(select(db.saved_requests).where(db.saved_requests.c.id == sid, db.saved_requests.c.organization_id == org)).first()
    if r is None:
        raise SavedError("saved request not found", 404)
    return r


def listing(conn: Connection, org: str) -> list[dict]:
    S = db.saved_requests
    return [dict(r._mapping) for r in conn.execute(select(S).where(S.c.organization_id == org).order_by(S.c.name_key)).fetchall()]


def save(p: Principal, name: str, spec: dict, priority: str = "normal") -> dict:
    name = re.sub(r"\s+", " ", name.strip())
    if not 2 <= len(name) <= 60:
        raise SavedError("give it a name of 2 to 60 characters")
    try:
        clean = links.check_spec(spec)
    except links.LinkError as exc:
        raise SavedError(str(exc), exc.status) from exc
    if spec.get("budget_usd") is not None:
        clean["budget_usd"] = float(spec["budget_usd"])
        from . import charter
        with db.get_engine().connect() as conn:
            try:
                charter.check_mission_budget(conn, p.organization_id, clean["budget_usd"])
            except charter.CharterError as exc:
                raise SavedError(str(exc)) from exc
    repo = spec.get("repository_id")
    S = db.saved_requests
    sid = db.new_id()
    try:
        with transaction() as conn:
            n = len(conn.execute(select(S.c.id).where(S.c.organization_id == p.organization_id)).fetchall())
            if n >= MAX_SAVED:
                raise SavedError(f"you already have {MAX_SAVED} saved requests", 409)
            if repo:  # only this organization's repository
                ok = conn.execute(select(db.repositories.c.id).where(db.repositories.c.id == repo,
                                                                     db.repositories.c.organization_id == p.organization_id)).first()
                if ok is None:
                    raise SavedError("that repository isn't one of yours", 404)
                clean["repository_id"] = repo
            conn.execute(insert(S).values(id=sid, organization_id=p.organization_id, name=name, name_key=_key(name), kind=clean["kind"],
                                          spec=clean, priority=priority, created_by=p.user_id, uses=0))
            emit(conn, "saved_request.created", org_id=p.organization_id, payload={"saved_request_id": sid, "name": name, "kind": clean["kind"]})
    except IntegrityError as exc:
        raise SavedError(f"you already have a saved request called \"{name}\"", 409) from exc
    with db.get_engine().connect() as conn:
        return dict(_row(conn, p.organization_id, sid)._mapping)


def save_from_mission(p: Principal, mission_id: str, name: str) -> dict:
    with db.get_engine().connect() as conn:
        try:
            m = links._mission(conn, p.organization_id, mission_id)
            spec = links.spec_of(m)
        except links.LinkError as exc:
            raise SavedError(str(exc), exc.status) from exc
        prio = links._priority(conn, mission_id)
    return save(p, name, spec, prio)


def start(p: Principal, sid: str) -> dict:
    """Start a saved request now, as `p`. Claimed first with a conditional update, so two presses can't both start
    one: a press while it's starting gets 409; a press within a few seconds after it started gets that run back."""
    from fastapi import HTTPException
    from sqlalchemy import or_
    S = db.saved_requests
    now = datetime.now(timezone.utc)
    cutoff = (now - DOUBLE_TAP).isoformat()
    with transaction() as conn:
        r = _row(conn, p.organization_id, sid)
        claimed = conn.execute(update(S).where(S.c.id == sid, or_(S.c.last_used_at.is_(None), S.c.last_used_at < cutoff))
                               .values(last_used_at=now.isoformat(), last_mission_id=None)).rowcount
        if not claimed:
            if r.last_mission_id:
                return {"mission_id": r.last_mission_id, "saved_request_id": sid, "repeat": True}
            raise SavedError("it's starting right now", 409)
    spec = dict(r.spec or {})
    try:
        mid = links.start(spec, p, priority=r.priority, key=f"saved:{sid}:{now.strftime('%Y%m%dT%H%M%S')}")
    except BaseException as exc:
        with transaction() as conn:  # put the claim back, so they can try again straight away
            conn.execute(update(S).where(S.c.id == sid).values(last_used_at=r.last_used_at, last_mission_id=r.last_mission_id))
        if isinstance(exc, (HTTPException, KeyboardInterrupt, SystemExit)):
            raise
        raise SavedError(f"couldn't start it: {exc}"[:300]) from exc
    with transaction() as conn:
        conn.execute(update(S).where(S.c.id == sid).values(uses=(r.uses or 0) + 1, last_mission_id=mid, last_used_at=now.isoformat()))
        emit(conn, "saved_request.started", mission_id=mid, org_id=p.organization_id,
             payload={"saved_request_id": sid, "name": r.name, "mission_id": mid})
    return {"mission_id": mid, "saved_request_id": sid, "repeat": False}


def remove(p: Principal, sid: str) -> None:
    with transaction() as conn:
        r = _row(conn, p.organization_id, sid)
        conn.execute(delete(db.saved_requests).where(db.saved_requests.c.id == sid))
        emit(conn, "saved_request.deleted", org_id=p.organization_id, payload={"saved_request_id": sid, "name": r.name})


def find(conn: Connection, org: str, text: str) -> dict | None:
    """The saved request a phrase names ("start nightly tests", "run my etsy research"), or None."""
    t = _key(text)
    rows = listing(conn, org)
    exact = [r for r in rows if r["name_key"] == t]
    if exact:
        return exact[0]
    hits = [r for r in rows if r["name_key"] in t]
    return max(hits, key=lambda r: len(r["name_key"])) if hits else None
