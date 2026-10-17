"""Run again (V6.21) and follow-on missions (V6.22).

Run again starts a finished mission's work afresh: same kind, request and parameters, through the same functions as a
person starting it (so the emergency stop, charter caps and approvals all apply). Only kinds a person can start
directly can be run again: fixing a failing test, running the tests and market research.

A follow-on is a mission written now that starts when another finishes: "when this completes, run the tests". It waits
as a link; the scheduler's `followups` job starts it once the first mission completes, and cancels it if the first one
fails or is cancelled (nothing builds on a failed step). The request is checked when it's written, so a bad follow-on
is refused up front, not when it's due. It starts as the person who wrote it, and only if their role at their latest
sign-in still lets them start missions.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection

from services.core import db
from services.core.auth import ROLE_RANK, Principal
from services.core.events import emit, transaction

log = logging.getLogger("aiciv.links")

RERUNNABLE = {"fix_failing_test", "run_tests", "market_research"}
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}
MAX_WAITING = 5          # follow-ons waiting on one mission
DOUBLE_TAP = timedelta(seconds=10)  # a second "run again" this soon returns the first one


class LinkError(ValueError):
    def __init__(self, msg: str, status: int = 422) -> None:
        super().__init__(msg)
        self.status = status


def spec_of(m) -> dict:
    """What it takes to start this mission's work again."""
    if m.kind not in RERUNNABLE:
        raise LinkError("only test fixes, test runs and research can be started again")
    params = dict(m.params or {})
    if m.kind == "market_research":
        return {"kind": "market_research", "params": {k: params[k] for k in ("source", "query", "region") if k in params},
                "title": m.title, "prompt": m.prompt}
    return {"kind": m.kind, "prompt": m.prompt, "title": m.title, "params": {}}


def check_spec(spec: dict) -> dict:
    """Validate a follow-on now (the same checks it will face when it starts)."""
    kind = spec.get("kind")
    if kind not in RERUNNABLE:
        raise LinkError("a follow-on can fix a failing test, run the tests or research a market")
    if kind == "market_research":
        from pydantic import ValidationError

        from services.api.v4 import ResearchIn
        try:
            r = ResearchIn(**(spec.get("params") or {}))
        except (ValidationError, TypeError) as exc:
            raise LinkError("research needs a valid topic and source") from exc
        return {"kind": kind, "params": r.model_dump(), "title": spec.get("title") or f"Research '{r.query}'", "prompt": ""}
    from services.orchestrator.plan import PlanError, validate_prompt
    try:
        prompt = validate_prompt(spec.get("prompt") or "")
    except PlanError as exc:
        raise LinkError(str(exc)) from exc
    return {"kind": kind, "prompt": prompt, "title": (spec.get("title") or "")[:120] or None, "params": {}}


def start(spec: dict, p: Principal, *, priority: str = "normal", key: str | None = None) -> str:
    """Start a mission from a spec through the regular functions. Raises HTTPException as they do."""
    from services.api import main, v4
    if spec["kind"] == "market_research":
        mid = v4.start_research(v4.ResearchIn(**spec["params"]), p)["mission_id"]
        if priority != "normal":
            with transaction() as conn:
                conn.execute(insert(db.mission_priorities).values(mission_id=mid, organization_id=p.organization_id,
                                                                  priority=priority, set_by=p.user_id))
            from services.api.main import state
            state.worker.reprioritize(mid, priority)
        return mid
    m = main.create_mission(main.MissionIn(prompt=spec["prompt"], kind=spec["kind"], title=spec.get("title"), priority=priority,
                                           idempotency_key=key), p)
    return m["id"]


def _mission(conn: Connection, org: str, mid: str):
    m = conn.execute(select(db.missions).where(db.missions.c.id == mid)).first()
    if m is None or m.organization_id != org:
        raise LinkError("mission not found", 404)
    return m


def _priority(conn: Connection, mid: str) -> str:
    return conn.execute(select(db.mission_priorities.c.priority).where(db.mission_priorities.c.mission_id == mid)).scalar() or "normal"


# ---------------------------------------------------------------- run again

def rerun(mission_id: str, p: Principal, priority: str | None = None) -> dict:
    now = datetime.now(timezone.utc)
    L = db.mission_links
    with transaction() as conn:
        m = _mission(conn, p.organization_id, mission_id)
        if m.status not in TERMINAL:
            raise LinkError("that mission is still going; you can run it again once it finishes", 409)
        spec = spec_of(m)
        recent = conn.execute(select(L.c.to_mission_id).where(L.c.from_mission_id == mission_id, L.c.kind == "rerun",
                                                              L.c.status == "STARTED", L.c.created_by == p.user_id,
                                                              L.c.created_at >= (now - DOUBLE_TAP).isoformat())
                              .order_by(L.c.created_at.desc()).limit(1)).scalar()
        prio = priority or _priority(conn, mission_id)
    if recent:  # a double tap: hand back the run that just started
        return {"mission_id": recent, "from_mission_id": mission_id, "repeat": True}
    lid = db.new_id()
    new_id = start(spec, p, priority=prio, key=f"rerun:{lid}")
    with transaction() as conn:
        conn.execute(insert(L).values(id=lid, organization_id=p.organization_id, kind="rerun", from_mission_id=mission_id,
                                      to_mission_id=new_id, status="STARTED", spec={**spec, "priority": prio}, created_by=p.user_id))
        emit(conn, "mission.rerun", mission_id=new_id, org_id=p.organization_id,
             payload={"from_mission_id": mission_id, "mission_id": new_id, "title": m.title})
    return {"mission_id": new_id, "from_mission_id": mission_id, "repeat": False}


# ---------------------------------------------------------------- follow-on missions

def add_followup(mission_id: str, p: Principal, spec: dict, priority: str = "normal") -> dict:
    clean = check_spec(spec)
    L = db.mission_links
    with transaction() as conn:
        m = _mission(conn, p.organization_id, mission_id)
        if m.status in ("FAILED", "CANCELLED"):
            raise LinkError(f"that mission {m.status.lower()}, so a follow-on would never start", 409)
        waiting = conn.execute(select(L.c.id).where(L.c.from_mission_id == mission_id, L.c.kind == "followup",
                                                    L.c.status == "WAITING")).fetchall()
        if len(waiting) >= MAX_WAITING:
            raise LinkError(f"a mission can have at most {MAX_WAITING} follow-ons waiting", 409)
        lid = db.new_id()
        conn.execute(insert(L).values(id=lid, organization_id=p.organization_id, kind="followup", from_mission_id=mission_id,
                                      status="WAITING", spec={**clean, "priority": priority}, created_by=p.user_id))
        emit(conn, "mission.followup_added", mission_id=mission_id, org_id=p.organization_id,
             payload={"link_id": lid, "kind": clean["kind"], "title": clean.get("title") or clean.get("prompt", "")[:80]})
    if m.status == "COMPLETED":  # already done: start it now
        tick(only=lid)
    return get(p.organization_id, lid)


def cancel_followup(org: str, link_id: str, user_id: str) -> dict:
    L = db.mission_links
    with transaction() as conn:
        n = conn.execute(update(L).where(L.c.id == link_id, L.c.organization_id == org, L.c.kind == "followup", L.c.status == "WAITING")
                         .values(status="CANCELLED", reason="cancelled by you", updated_at=db.utcnow())).rowcount
        if not n:
            row = conn.execute(select(L.c.status).where(L.c.id == link_id, L.c.organization_id == org)).first()
            if row is None:
                raise LinkError("follow-on not found", 404)
            raise LinkError(f"that follow-on is already {row.status.lower()}", 409)
        emit(conn, "mission.followup_cancelled", org_id=org, payload={"link_id": link_id, "by": user_id})
    return get(org, link_id)


def get(org: str, link_id: str) -> dict:
    with db.get_engine().connect() as conn:
        r = conn.execute(select(db.mission_links).where(db.mission_links.c.id == link_id, db.mission_links.c.organization_id == org)).first()
        return dict(r._mapping) if r else {}


def for_mission(conn: Connection, org: str, mission_id: str) -> dict:
    """Follow-ons waiting on (or started by) this mission, and what it was started from."""
    L = db.mission_links
    after = [dict(r._mapping) for r in conn.execute(select(L).where(L.c.organization_id == org, L.c.from_mission_id == mission_id)
                                                    .order_by(L.c.created_at)).fetchall()]
    origin = conn.execute(select(L).where(L.c.organization_id == org, L.c.to_mission_id == mission_id)).first()
    return {"followups": [a for a in after if a["kind"] == "followup"],
            "reruns": [a for a in after if a["kind"] == "rerun"],
            "started_from": dict(origin._mapping) if origin else None}


def _role_ok(conn: Connection, org: str, user_id: str) -> bool:
    """The writer's role at their latest sign-in still lets them start missions (unknown counts as yes: they had
    operator rights when they wrote it, and the roster may predate them)."""
    role = conn.execute(select(db.org_members.c.role).where(db.org_members.c.organization_id == org,
                                                            db.org_members.c.user_id == user_id)).scalar()
    return role is None or ROLE_RANK.get(role, -1) >= ROLE_RANK["operator"]


def tick(only: str | None = None) -> dict:
    """Start follow-ons whose first mission completed; cancel those whose first mission failed or was cancelled."""
    L, M = db.mission_links, db.missions
    with db.get_engine().connect() as conn:
        q = (select(L.c.id, L.c.organization_id, L.c.spec, L.c.created_by, L.c.from_mission_id, M.c.status.label("first"))
             .join(M, M.c.id == L.c.from_mission_id)
             .where(L.c.kind == "followup", L.c.status == "WAITING", M.c.status.in_(list(TERMINAL))))
        if only:
            q = q.where(L.c.id == only)
        rows = conn.execute(q.limit(50)).fetchall()
    out = {"started": 0, "cancelled": 0, "failed": 0, "held": 0}
    for r in rows:
        with transaction() as conn:  # claim it, so two ticks can't both start it
            if r.first != "COMPLETED":
                n = conn.execute(update(L).where(L.c.id == r.id, L.c.status == "WAITING").values(
                    status="CANCELLED", reason=f"the first mission {r.first.lower()}", updated_at=db.utcnow())).rowcount
                if n:
                    out["cancelled"] += 1
                    emit(conn, "mission.followup_cancelled", mission_id=r.from_mission_id, org_id=r.organization_id,
                         payload={"link_id": r.id, "reason": f"the first mission {r.first.lower()}"})
                continue
            if not _role_ok(conn, r.organization_id, r.created_by):
                n = conn.execute(update(L).where(L.c.id == r.id, L.c.status == "WAITING").values(
                    status="CANCELLED", reason="the person who wrote it can no longer start missions", updated_at=db.utcnow())).rowcount
                out["cancelled"] += n
                continue
            if not conn.execute(update(L).where(L.c.id == r.id, L.c.status == "WAITING")
                                .values(status="STARTING", updated_at=db.utcnow())).rowcount:
                continue
        p = Principal(user_id=r.created_by, organization_id=r.organization_id, role="operator", mode="followup")
        spec = dict(r.spec or {})
        try:
            mid = start(spec, p, priority=spec.get("priority", "normal"), key=f"followup:{r.id}")
        except HTTPException as exc:
            hold = exc.status_code == 409 and "emergency stop" in str(exc.detail)
            with transaction() as conn:  # an emergency stop holds it (it starts once the stop is lifted); anything else fails it
                conn.execute(update(L).where(L.c.id == r.id).values(status="WAITING" if hold else "FAILED",
                                                                    reason=str(exc.detail)[:300], updated_at=db.utcnow()))
            out["held" if hold else "failed"] += 1
            continue
        except Exception as exc:
            log.exception("follow-on %s failed", r.id)
            with transaction() as conn:
                conn.execute(update(L).where(L.c.id == r.id).values(status="FAILED", reason=str(exc)[:300], updated_at=db.utcnow()))
            out["failed"] += 1
            continue
        with transaction() as conn:
            conn.execute(update(L).where(L.c.id == r.id).values(status="STARTED", to_mission_id=mid, reason=None, updated_at=db.utcnow()))
            emit(conn, "mission.followup_started", mission_id=mid, org_id=r.organization_id,
                 payload={"link_id": r.id, "from_mission_id": r.from_mission_id, "mission_id": mid})
        out["started"] += 1
    return out
