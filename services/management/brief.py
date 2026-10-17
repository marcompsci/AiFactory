"""The daily brief: what happened in the last day, written by rules from the records (no model, nothing invented).

Every number here is counted from a table; money is the gateway's estimate and is labelled as one. The headline is
composed from those counts, so it can never claim more than the records show.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from services.core import db

from . import charter
from .reliability import LESSON_PREFIX


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def brief(conn: Connection, org_id: str, hours: int = 24) -> dict:
    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=hours)).isoformat()
    M = db.missions
    window = (M.c.organization_id == org_id) & (M.c.updated_at >= since)
    counts = dict(conn.execute(select(M.c.status, func.count()).where(window, M.c.status.in_(["COMPLETED", "FAILED"]))
                               .group_by(M.c.status)).fetchall())
    finished = conn.execute(select(M.c.id, M.c.title, M.c.status, M.c.outcome, M.c.failure_reason, M.c.execution_mode, M.c.updated_at)
                            .where(window, M.c.status.in_(["COMPLETED", "FAILED"]))
                            .order_by(M.c.updated_at.desc()).limit(50)).fetchall()
    objectives: dict[str, str] = {}
    ids = [r.id for r in finished]
    if ids:  # each mission's latest objective check, whenever it was made
        for g in conn.execute(select(db.goal_checkpoints.c.mission_id, db.goal_checkpoints.c.status)
                              .where(db.goal_checkpoints.c.mission_id.in_(ids), db.goal_checkpoints.c.status.like("objective_%"))
                              .order_by(db.goal_checkpoints.c.created_at)).fetchall():
            objectives[g.mission_id] = g.status
    completed = [{"id": r.id, "title": r.title, "outcome": r.outcome, "objective": objectives.get(r.id),
                  "simulation": r.execution_mode == "simulation"} for r in finished if r.status == "COMPLETED"]
    failed = [{"id": r.id, "title": r.title, "reason": r.failure_reason, "simulation": r.execution_mode == "simulation"}
              for r in finished if r.status == "FAILED"]
    running = conn.execute(select(func.count()).select_from(M).where(
        M.c.organization_id == org_id, M.c.status.notin_(["COMPLETED", "FAILED", "CANCELLED"]))).scalar() or 0

    approvals = conn.execute(select(func.count()).select_from(db.approvals).where(
        db.approvals.c.organization_id == org_id, db.approvals.c.status == "PENDING")).scalar() or 0
    recovery = [dict(r._mapping) for r in conn.execute(
        select(db.recovery_plans.c.id, db.recovery_plans.c.summary, db.recovery_plans.c.mission_id)
        .where(db.recovery_plans.c.organization_id == org_id, db.recovery_plans.c.status == "PENDING")).fetchall()]
    releases = conn.execute(select(func.count()).select_from(db.opportunities).where(
        db.opportunities.c.organization_id == org_id, db.opportunities.c.status == "OWNER_APPROVAL")).scalar() or 0

    day = now.date().isoformat()
    U = db.usage_records
    spend_rows = conn.execute(select(U.c.agent_id, func.sum(U.c.estimated_cost_usd).label("usd"))
                              .where(U.c.organization_id == org_id, U.c.created_at >= day).group_by(U.c.agent_id)).fetchall()
    names = {a.id: a.name for a in conn.execute(select(db.agents.c.id, db.agents.c.name)
                                                .where(db.agents.c.organization_id == org_id)).fetchall()}
    by_agent = sorted(({"agent_id": r.agent_id, "agent": names.get(r.agent_id, ""), "usd": round(float(r.usd or 0), 4)}
                       for r in spend_rows), key=lambda a: -a["usd"])
    org = conn.execute(select(db.organizations.c.daily_budget_usd).where(db.organizations.c.id == org_id)).first()
    rules = charter.rules(conn, org_id)
    cap = rules.get("agent_daily_usd")
    near_cap = [a for a in by_agent if cap and a["usd"] >= 0.8 * cap]
    spend = {"today_usd": round(sum(a["usd"] for a in by_agent), 4), "daily_budget_usd": org.daily_budget_usd if org else None,
             "by_agent": by_agent[:5], "agent_daily_cap_usd": cap, "near_cap": near_cap, "is_estimate": True}

    lessons = [{"agent": names.get(r.agent_id, ""), "lesson": r.content[len(LESSON_PREFIX):], "source": r.source}
               for r in conn.execute(select(db.memory_entries.c.agent_id, db.memory_entries.c.content, db.memory_entries.c.source)
                                     .where(db.memory_entries.c.organization_id == org_id, db.memory_entries.c.created_at >= since,
                                            db.memory_entries.c.content.like(LESSON_PREFIX + "%"))
                                     .order_by(db.memory_entries.c.created_at.desc()).limit(5)).fetchall()]
    loops = conn.execute(select(func.count()).select_from(db.manager_decisions).where(
        db.manager_decisions.c.organization_id == org_id, db.manager_decisions.c.created_at >= since,
        db.manager_decisions.c.outcome.in_(["loop_stopped", "looping"]))).scalar() or 0

    waiting = approvals + len(recovery) + releases
    n_done, n_failed = int(counts.get("COMPLETED", 0)), int(counts.get("FAILED", 0))
    parts = []
    if n_done or n_failed:
        parts.append(f"{_plural(n_done, 'mission')} finished" + (f" and {n_failed} failed" if n_failed else ""))
    else:
        parts.append("No missions finished")
    parts.append(f"{_plural(waiting, 'thing')} waiting for you" if waiting else "nothing is waiting for you")
    if near_cap:
        parts.append(f"{', '.join(a['agent'] for a in near_cap)} near the daily cap")
    from .forecast import forecast
    fc = forecast(conn, org_id, now)
    if fc["warnings"]:
        at = [w["agent"] for w in fc["warnings"] if w.get("already")]
        soon = [w["agent"] for w in fc["warnings"] if not w.get("already")]
        if at:
            parts.append(f"{', '.join(at[:3])} reached a cap")
        if soon:
            parts.append(f"at today's pace {', '.join(soon[:3])} will hit a cap today")
    span = "day" if hours == 24 else "week" if hours == 168 else f"{hours} hours"
    headline = f"In the last {span}: " + "; ".join(parts) + "."

    return {"generated_at": now.isoformat(), "hours": hours, "headline": headline,
            "completed": completed, "failed": failed, "running": running, "counts": {"completed": n_done, "failed": n_failed},
            "waiting": {"approvals": approvals, "recovery_plans": recovery, "releases": releases, "total": waiting},
            "spend": spend, "lessons": lessons, "loops_caught": loops,
            "quiet_now": charter.quiet_now(rules), "forecast_warnings": fc["warnings"], "method": "records"}


def spoken(b: dict) -> str:
    """The brief as one paragraph, for Atlas in the City."""
    lines = [b["headline"]]
    if b["failed"]:
        lines.append("Failed: " + "; ".join(f["title"] for f in b["failed"][:3]) + ".")
    if b["waiting"]["recovery_plans"]:
        lines.append(f"I drafted {_plural(len(b['waiting']['recovery_plans']), 'recovery plan')}; they run only if you approve.")
    s = b["spend"]
    lines.append(f"Spend today is about ${s['today_usd']:.2f} (estimated).")
    if b["lessons"]:
        lines.append(f"{b['lessons'][0]['agent']} learned: {b['lessons'][0]['lesson']}")
    if b["quiet_now"]:
        lines.append("Quiet hours are on, so scheduled work is waiting.")
    return " ".join(lines)
