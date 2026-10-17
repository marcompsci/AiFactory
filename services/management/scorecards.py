"""Agent scorecards: how reliable each agent has been, week by week, counted from task runs.

The MAST study's advice is to measure failure patterns over time rather than trust a single success rate, and to
compare before and after a change. So each agent gets weekly counts (finished, failed, first-try passes, failures by
kind, time and estimated cost) and a trend that is only called when there's enough data to call it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.engine import Connection

from services.core import db

from .reliability import _mode_for

MIN_TASKS_FOR_TREND = 3
MAX_ROWS = 20000


def _week(iso: str) -> str:
    d = datetime.fromisoformat(iso).astimezone(timezone.utc).date()
    return (d - timedelta(days=d.weekday())).isoformat()  # the Monday that starts its week


def _ms(a: str | None, b: str | None) -> int | None:
    try:
        return int((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() * 1000) if a and b else None
    except ValueError:
        return None


def scorecards(conn: Connection, org_id: str, weeks: int = 4) -> dict:
    now = datetime.now(timezone.utc)
    this_monday = now.date() - timedelta(days=now.weekday())
    week_keys = [(this_monday - timedelta(weeks=i)).isoformat() for i in range(weeks - 1, -1, -1)]
    since = week_keys[0]
    agents = {a.id: a for a in conn.execute(select(db.agents.c.id, db.agents.c.name, db.agents.c.role)
                                            .where(db.agents.c.organization_id == org_id)).fetchall()}

    def blank() -> dict:
        return {"finished": 0, "failed": 0, "first_try": 0, "runs": 0, "failed_runs": 0, "busy_ms": 0, "cost_usd": 0.0, "modes": {}}

    cards = {aid: {w: blank() for w in week_keys} for aid in agents}
    runs = conn.execute(select(db.task_runs.c.task_id, db.task_runs.c.attempt, db.task_runs.c.status, db.task_runs.c.error,
                               db.task_runs.c.started_at, db.task_runs.c.finished_at, db.tasks.c.agent_id)
                        .join(db.tasks, db.tasks.c.id == db.task_runs.c.task_id)
                        .where(db.task_runs.c.organization_id == org_id, db.task_runs.c.started_at >= since)
                        .order_by(db.task_runs.c.started_at.desc()).limit(MAX_ROWS)).fetchall()  # newest first if capped
    truncated = len(runs) >= MAX_ROWS
    runs = list(reversed(runs))
    by_task: dict[str, list] = {}
    for r in runs:
        by_task.setdefault(r.task_id, [])
        if r.agent_id not in cards:
            continue
        w = _week(r.started_at)
        if w not in cards[r.agent_id]:
            continue
        c = cards[r.agent_id][w]
        c["runs"] += 1
        c["busy_ms"] += max(0, _ms(r.started_at, r.finished_at) or 0)
        if r.status == "FAILED":
            c["failed_runs"] += 1
            m = _mode_for(r.error)
            c["modes"][m] = c["modes"].get(m, 0) + 1
    # a task counts in the week its last run finished; "first try" = its only run (ever, not just in the window) passed
    tasks: dict = {}
    ids = list(by_task)
    for i in range(0, len(ids), 500):  # chunked: SQLite caps the number of bound parameters
        chunk = ids[i:i + 500]
        tasks.update({t.id: t for t in conn.execute(select(db.tasks.c.id, db.tasks.c.status, db.tasks.c.agent_id, db.tasks.c.updated_at)
                                                    .where(db.tasks.c.id.in_(chunk))).fetchall()})
        for r in conn.execute(select(db.task_runs.c.task_id, db.task_runs.c.status).where(db.task_runs.c.task_id.in_(chunk))
                              .order_by(db.task_runs.c.attempt)).fetchall():
            by_task[r.task_id].append(r)
    for tid, rs in by_task.items():
        t = tasks.get(tid)
        if t is None or t.agent_id not in cards or t.status not in ("COMPLETED", "FAILED"):
            continue
        w = _week(t.updated_at)
        if w not in cards[t.agent_id]:
            continue
        c = cards[t.agent_id][w]
        if t.status == "COMPLETED":
            c["finished"] += 1
            c["first_try"] += int(len(rs) == 1 and rs[0].status == "COMPLETED")
        else:
            c["failed"] += 1
    for u in conn.execute(select(db.usage_records.c.agent_id, db.usage_records.c.created_at, db.usage_records.c.estimated_cost_usd)
                          .where(db.usage_records.c.organization_id == org_id, db.usage_records.c.created_at >= since)
                          .order_by(db.usage_records.c.created_at.desc()).limit(MAX_ROWS)).fetchall():
        if u.agent_id in cards and (w := _week(u.created_at)) in cards[u.agent_id]:
            cards[u.agent_id][w]["cost_usd"] = round(cards[u.agent_id][w]["cost_usd"] + float(u.estimated_cost_usd or 0), 6)

    out = []
    for aid, ws in cards.items():
        series = []
        for w in week_keys:
            c = ws[w]
            done = c["finished"] + c["failed"]
            series.append({"week": w, **c, "tasks": done,
                           "first_try_rate": round(c["first_try"] / c["finished"], 3) if c["finished"] else None,
                           "success_rate": round(c["finished"] / done, 3) if done else None})
        last, prev = series[-1], series[-2] if len(series) > 1 else None
        trend = "not enough data"
        if prev and last["tasks"] >= MIN_TASKS_FOR_TREND and prev["tasks"] >= MIN_TASKS_FOR_TREND:
            d = (last["success_rate"] or 0) - (prev["success_rate"] or 0)
            trend = "improving" if d >= 0.1 else "slipping" if d <= -0.1 else "steady"
        total = {k: sum(s[k] for s in series) for k in ("finished", "failed", "first_try", "runs", "failed_runs", "busy_ms")}
        total["cost_usd"] = round(sum(s["cost_usd"] for s in series), 6)
        modes: dict[str, int] = {}
        for s in series:
            for m, n in s["modes"].items():
                modes[m] = modes.get(m, 0) + n
        if not total["runs"] and not total["cost_usd"]:
            continue
        done = total["finished"] + total["failed"]
        out.append({"agent_id": aid, "agent": agents[aid].name, "role": agents[aid].role, "weeks": series, "trend": trend,
                    "total": {**total, "success_rate": round(total["finished"] / done, 3) if done else None,
                              "first_try_rate": round(total["first_try"] / total["finished"], 3) if total["finished"] else None,
                              "avg_run_ms": int(total["busy_ms"] / total["runs"]) if total["runs"] else None},
                    "top_failure": max(modes.items(), key=lambda kv: kv[1])[0] if modes else None})
    out.sort(key=lambda a: -(a["total"]["finished"] + a["total"]["failed"]))
    return {"weeks": week_keys, "agents": out, "method": "records", "cost_is_estimate": True, "truncated": truncated,
            "trend_rule": f"success rate this week vs last, called only with {MIN_TASKS_FOR_TREND}+ tasks in both weeks"}


def scorecard(conn: Connection, org_id: str, agent_id: str, weeks: int = 4) -> dict | None:
    return next((a for a in scorecards(conn, org_id, weeks)["agents"] if a["agent_id"] == agent_id), None)
