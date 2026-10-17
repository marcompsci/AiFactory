"""Reliability insights: why agents failed, sorted into the MAST taxonomy (services/management/reliability.py)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from services.core import db
from services.core.auth import Principal, authenticate
from services.management import reliability

router = APIRouter(prefix="/api/insights")


def member(request: Request) -> Principal:
    return authenticate(request)


@router.get("/failures")
def failures(days: int = Query(30, ge=1, le=365), p: Principal = Depends(member)) -> dict:
    """Every failure in the period with its MAST label, plus counts by category, failure mode and agent."""
    with db.get_engine().connect() as conn:
        return reliability.failure_labels(conn, p.organization_id, days)


@router.get("/lessons")
def lessons(p: Principal = Depends(member)) -> dict:
    """What each agent has learned from its own runs (rule-written, each citing its run)."""
    from sqlalchemy import select
    with db.get_engine().connect() as conn:
        agents = conn.execute(select(db.agents.c.id, db.agents.c.name, db.agents.c.role)
                              .where(db.agents.c.organization_id == p.organization_id).order_by(db.agents.c.name)).fetchall()
        out = [{"agent_id": a.id, "agent": a.name, "role": a.role, "lessons": reliability.lessons_for(conn, a.id, limit=5)} for a in agents]
    return {"agents": [a for a in out if a["lessons"]], "trust": "hypothesis"}


@router.get("/missions/{mission_id}/trace")
def mission_trace(mission_id: str, p: Principal = Depends(member)) -> dict:
    """Everything that happened in one mission, in order, with totals per agent (services/management/trace.py)."""
    from fastapi import HTTPException
    from sqlalchemy import select

    from services.management.trace import mission_trace as build
    with db.get_engine().connect() as conn:
        m = conn.execute(select(db.missions.c.organization_id).where(db.missions.c.id == mission_id)).first()
        if m is None or m.organization_id != p.organization_id:
            raise HTTPException(404, "mission not found")
        return build(conn, mission_id)


@router.get("/collaboration")
def collaboration(days: int = Query(30, ge=1, le=365), p: Principal = Depends(member)) -> dict:
    """Who works with whom (handoffs and messages) and which districts send each other work (handoffs and packages)."""
    from services.management.collaboration import network
    with db.get_engine().connect() as conn:
        return network(conn, p.organization_id, days)


@router.get("/brief")
def daily_brief(hours: int = Query(24, ge=1, le=168), p: Principal = Depends(member)) -> dict:
    """The daily brief, counted from the records (services/management/brief.py)."""
    from services.management.brief import brief
    with db.get_engine().connect() as conn:
        return brief(conn, p.organization_id, hours)


@router.get("/weekly")
def weekly_report(tz: str = Query("UTC", max_length=64), p: Principal = Depends(member)) -> dict:
    """The last seven local days (your time zone; unknown zones fall back to UTC) against the seven before, counted
    from the records (services/management/weekly.py)."""
    from services.management.weekly import report
    with db.get_engine().connect() as conn:
        return report(conn, p.organization_id, tz=tz)


@router.get("/scorecards")
def agent_scorecards(weeks: int = Query(4, ge=2, le=26), p: Principal = Depends(member)) -> dict:
    """Each agent's reliability week by week, counted from task runs (services/management/scorecards.py)."""
    from services.management.scorecards import scorecards
    with db.get_engine().connect() as conn:
        return scorecards(conn, p.organization_id, weeks)


@router.get("/audit/verify")
def audit_verify(p: Principal = Depends(member)) -> dict:
    """Recompute the event chain and report the first place it was altered, if any (services/core/audit.py)."""
    from services.core import audit
    with db.get_engine().connect() as conn:
        return audit.verify_throttled(conn, p.organization_id)


@router.get("/audit/missions/{mission_id}")
def audit_export(mission_id: str, p: Principal = Depends(member)):
    """One mission's audit file: its record, trace, checks, recovery plans and chained events, plus a bundle hash."""
    from fastapi import HTTPException
    from fastapi.responses import JSONResponse
    from sqlalchemy import select

    from services.core import audit
    with db.get_engine().connect() as conn:
        m = conn.execute(select(db.missions.c.organization_id).where(db.missions.c.id == mission_id)).first()
        if m is None or m.organization_id != p.organization_id:
            raise HTTPException(404, "mission not found")
        bundle = audit.mission_export(conn, mission_id)
    return JSONResponse(bundle, headers={"Content-Disposition": f'attachment; filename="mission-{mission_id[:8]}-audit.json"'})


@router.get("/inbox")
def owner_inbox(p: Principal = Depends(member)) -> dict:
    """Everything waiting for a decision, soonest-to-expire first (services/management/inbox.py)."""
    from services.management.inbox import inbox
    with db.get_engine().connect() as conn:
        return inbox(conn, p.organization_id)


@router.get("/search")
def search_records(q: str = Query("", max_length=100), p: Principal = Depends(member)) -> dict:
    """Text search across missions, steps, messages, lessons, decisions and artifacts (services/management/search.py)."""
    from services.management.search import search
    with db.get_engine().connect() as conn:
        return search(conn, p.organization_id, q)


@router.get("/forecast")
def spend_forecast(p: Principal = Depends(member)) -> dict:
    """Where today's estimated spend is heading, per agent, and who will hit a cap (services/management/forecast.py)."""
    from services.management.forecast import forecast
    with db.get_engine().connect() as conn:
        return forecast(conn, p.organization_id)
