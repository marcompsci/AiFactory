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
