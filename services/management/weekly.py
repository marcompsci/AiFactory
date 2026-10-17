"""The weekly report (V6.23): the last seven days, day by day, against the seven before. Counted from the records by
rules, like the daily brief: no model writes it and nothing is invented. Money is the gateway's estimate and is
labelled as one. Days are the caller's local days (V6.27: the phone and the City send their time zone; an unknown
zone falls back to UTC).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from services.core import db

MAX_ROWS = 100_000


def zone(tz: str | None):
    try:
        return ZoneInfo(tz or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _day(v, z=timezone.utc) -> str:
    d = v if isinstance(v, datetime) else datetime.fromisoformat(str(v))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(z).date().isoformat()


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _change(now_n: float, before: float) -> str:
    if before == 0:
        return "new this week" if now_n else "none either week"
    pct = round((now_n - before) / before * 100)
    return "same as the week before" if pct == 0 else f"{'up' if pct > 0 else 'down'} {abs(pct)}% on the week before"


def report(conn: Connection, org_id: str, now: datetime | None = None, tz: str | None = "UTC") -> dict:
    z = zone(tz)
    now = now or datetime.now(timezone.utc)
    local_today = now.astimezone(z).date()
    first_day = local_today - timedelta(days=6)   # seven local days including today
    days = [(first_day + timedelta(days=i)).isoformat() for i in range(7)]
    # local midnights as UTC instants for the queries (zoneinfo picks the right offset on daylight-saving days)
    start = datetime(first_day.year, first_day.month, first_day.day, tzinfo=z).astimezone(timezone.utc)
    p_day = first_day - timedelta(days=7)
    prev = datetime(p_day.year, p_day.month, p_day.day, tzinfo=z).astimezone(timezone.utc)
    per_day = {d: {"date": d, "completed": 0, "failed": 0, "spend_usd": 0.0} for d in days}

    M = db.missions
    week = {"completed": 0, "failed": 0, "spend_usd": 0.0}
    before = {"completed": 0, "failed": 0, "spend_usd": 0.0}
    for r in conn.execute(select(M.c.status, M.c.updated_at).where(M.c.organization_id == org_id, M.c.updated_at >= prev.isoformat(),
                                                                   M.c.status.in_(["COMPLETED", "FAILED"])).limit(MAX_ROWS)).fetchall():
        d, key = _day(r.updated_at, z), r.status.lower()
        if d in per_day:
            per_day[d][key] += 1
            week[key] += 1
        else:
            before[key] += 1
    U = db.usage_records
    for r in conn.execute(select(U.c.created_at, U.c.estimated_cost_usd).where(U.c.organization_id == org_id,
                                                                              U.c.created_at >= prev.isoformat()).limit(MAX_ROWS)).fetchall():
        d, usd = _day(r.created_at, z), float(r.estimated_cost_usd or 0)
        if d in per_day:
            per_day[d]["spend_usd"] += usd
            week["spend_usd"] += usd
        else:
            before["spend_usd"] += usd
    for d in per_day.values():
        d["spend_usd"] = round(d["spend_usd"], 4)
    week["spend_usd"], before["spend_usd"] = round(week["spend_usd"], 4), round(before["spend_usd"], 4)

    E = db.events
    kinds = ("schedule.ran", "schedule.auto_paused", "mission.rerun", "mission.followup_started", "records.exported")
    ev: dict[str, int] = {k: 0 for k in kinds}
    sched_ok = sched_err = 0
    for r in conn.execute(select(E.c.event_type, E.c.payload).where(E.c.organization_id == org_id, E.c.occurred_at >= start.isoformat(),
                                                                    E.c.event_type.in_(kinds)).limit(MAX_ROWS)).fetchall():
        ev[r.event_type] += 1
        if r.event_type == "schedule.ran":
            if (r.payload or {}).get("mission_id"):
                sched_ok += 1
            else:
                sched_err += 1

    A = db.approvals
    decided = dict(conn.execute(select(A.c.status, func.count()).where(A.c.organization_id == org_id, A.c.status != "PENDING",
                                                                       A.c.decided_at >= start.isoformat()).group_by(A.c.status)).fetchall())
    T = db.tasks
    names = {a.id: a.name for a in conn.execute(select(db.agents.c.id, db.agents.c.name).where(db.agents.c.organization_id == org_id))}
    top = [{"agent_id": r.agent_id, "agent": names.get(r.agent_id, ""), "tasks_completed": int(r.n)} for r in conn.execute(
        select(T.c.agent_id, func.count().label("n")).where(T.c.organization_id == org_id, T.c.status == "COMPLETED",
                                                            T.c.updated_at >= start.isoformat())
        .group_by(T.c.agent_id).order_by(func.count().desc()).limit(5)).fetchall()]

    parts = [f"{_plural(week['completed'], 'mission')} finished ({_change(week['completed'], before['completed'])})"]
    if week["failed"]:
        parts.append(f"{week['failed']} failed")
    parts.append(f"about ${week['spend_usd']:.2f} estimated spend ({_change(week['spend_usd'], before['spend_usd'])})")
    if sched_ok or sched_err:
        parts.append(f"schedules ran {_plural(sched_ok, 'time')}" + (f", {sched_err} couldn't start" if sched_err else ""))
    if ev["schedule.auto_paused"]:
        parts.append(f"{_plural(ev['schedule.auto_paused'], 'schedule')} paused itself")
    if top:
        parts.append(f"busiest: {top[0]['agent']} ({_plural(top[0]['tasks_completed'], 'task')})")
    headline = "This week: " + "; ".join(parts) + "."
    busiest_day = max(per_day.values(), key=lambda d: (d["completed"] + d["failed"], d["spend_usd"]))
    return {"generated_at": now.isoformat(), "from": start.isoformat(), "to": now.isoformat(), "days": list(per_day.values()),
            "week": week, "previous_week": before, "headline": headline,
            "schedules": {"started": sched_ok, "could_not_start": sched_err, "auto_paused": ev["schedule.auto_paused"]},
            "reruns": ev["mission.rerun"], "followups_started": ev["mission.followup_started"],
            "approvals_decided": {k.lower(): int(v) for k, v in decided.items()}, "top_agents": top,
            "busiest_day": busiest_day["date"] if busiest_day["completed"] + busiest_day["failed"] else None,
            "is_estimate": True, "tz": getattr(z, "key", "UTC"),
            "method": "records; seven local days including today, compared with the seven before"}


def spoken(r: dict) -> str:
    lines = [r["headline"]]
    if r["busiest_day"]:
        lines.append(f"The busiest day was {datetime.fromisoformat(r['busiest_day']).strftime('%A')}.")
    if r["approvals_decided"]:
        lines.append("Approvals you decided: " + ", ".join(f"{v} {k}" for k, v in r["approvals_decided"].items()) + ".")
    lines.append("Spend figures are estimates, not bills.")
    return " ".join(lines)
