"""Spend forecast: at today's pace, where will each agent's estimated AI spend end the day, and will it hit a cap?

Method (stated in every response): the pace is today's estimated spend divided by the hours since the first spend
today (at least half an hour, so one early call doesn't look like a flood), carried forward to midnight UTC. It's an
estimate of an estimate; it needs at least MIN_CALLS AI calls today before it says anything.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from services.core import db

from . import charter

MIN_CALLS = 3
MIN_HOURS = 0.5


def _project(spent: float, first: str | None, calls: int, now: datetime, end: datetime, cap: float | None) -> dict:
    if calls < MIN_CALLS or not first:
        return {"spent": round(spent, 4), "projected": None, "per_hour": None, "hits_cap_at": None, "enough_data": False}
    hours = max(MIN_HOURS, (now - datetime.fromisoformat(first)).total_seconds() / 3600)
    rate = spent / hours
    projected = spent + rate * max(0.0, (end - now).total_seconds() / 3600)
    hits = None
    if cap is not None and rate > 0 and spent < cap and projected >= cap:
        hits = (now + timedelta(hours=(cap - spent) / rate)).isoformat()
    elif cap is not None and spent >= cap:
        hits = now.isoformat()  # already there
    return {"spent": round(spent, 4), "projected": round(projected, 4), "per_hour": round(rate, 4), "hits_cap_at": hits, "enough_data": True}


def forecast(conn: Connection, org_id: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = day + timedelta(days=1)
    U = db.usage_records
    rows = conn.execute(select(U.c.agent_id, func.sum(U.c.estimated_cost_usd).label("usd"), func.min(U.c.created_at).label("first"),
                               func.count().label("n"))
                        .where(U.c.organization_id == org_id, U.c.created_at >= day.isoformat()).group_by(U.c.agent_id)).fetchall()
    names = {a.id: a.name for a in conn.execute(select(db.agents.c.id, db.agents.c.name).where(db.agents.c.organization_id == org_id))}
    rules = charter.rules(conn, org_id)
    cap = rules.get("agent_daily_usd")
    agents = []
    for r in rows:
        p = _project(float(r.usd or 0), r.first, int(r.n), now, end, cap)
        agents.append({"agent_id": r.agent_id, "agent": names.get(r.agent_id, ""), "calls": int(r.n), **p})
    agents.sort(key=lambda a: -(a["projected"] or a["spent"]))
    budget = conn.execute(select(db.organizations.c.daily_budget_usd).where(db.organizations.c.id == org_id)).scalar()
    total_spent = sum(float(r.usd or 0) for r in rows)
    first = min((r.first for r in rows), default=None)
    total = _project(total_spent, first, sum(int(r.n) for r in rows), now, end, budget)
    warnings = [{"agent": a["agent"], "agent_id": a["agent_id"], "hits_cap_at": a["hits_cap_at"], "cap": cap}
                for a in agents if a["hits_cap_at"]]
    if total["hits_cap_at"]:
        warnings.append({"agent": "Everyone together", "agent_id": None, "hits_cap_at": total["hits_cap_at"], "cap": budget})
    return {"as_of": now.isoformat(), "day_ends": end.isoformat(), "agents": agents, "total": {**total, "daily_budget_usd": budget},
            "agent_daily_cap_usd": cap, "warnings": warnings, "is_estimate": True,
            "method": f"today's pace (spend ÷ hours since the first spend, at least {MIN_HOURS} h) carried to midnight UTC; "
                      f"needs {MIN_CALLS}+ AI calls"}
