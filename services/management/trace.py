"""Mission trace: one ordered timeline of everything that happened in a mission, with totals per agent.

Observability write-ups on agent systems keep landing on the same advice: the trace is the most useful single
thing to capture (every step, tool call and model call with its cost), and spend should be visible per agent.
This builds that trace from records the runner already keeps; nothing is estimated here except model cost, which
is the gateway's estimate and is labelled as one.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from services.core import db

MAX_ITEMS = 1500
PER_SOURCE = 1000  # newest first from each source; totals below come from SQL sums, not from the capped lists


def _ms(a: str | None, b: str | None) -> int | None:
    try:
        return max(0, int((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() * 1000)) if a and b else None
    except ValueError:
        return None


def mission_trace(conn: Connection, mission_id: str) -> dict:
    m = conn.execute(select(db.missions).where(db.missions.c.id == mission_id)).first()
    agents = {a.id: a for a in conn.execute(select(db.agents.c.id, db.agents.c.name, db.agents.c.role)
                                            .where(db.agents.c.organization_id == m.organization_id)).fetchall()}
    tasks = {t.id: t for t in conn.execute(select(db.tasks).where(db.tasks.c.mission_id == mission_id)).fetchall()}
    name = lambda aid: agents[aid].name if aid in agents else ""  # noqa: E731
    items: list[dict] = []

    def add(at, kind, title, *, agent_id=None, task_id=None, detail="", status=None, duration_ms=None, cost_usd=None,
            tokens=None, ref=None):
        items.append({"at": at, "kind": kind, "title": title, "agent_id": agent_id, "agent": name(agent_id), "task_id": task_id,
                      "task": tasks[task_id].title if task_id in tasks else None, "detail": (detail or "")[:400], "status": status,
                      "duration_ms": duration_ms, "cost_usd": cost_usd, "tokens": tokens, "ref": ref})

    add(m.created_at, "mission", f"Mission created: {m.title}", detail=m.prompt, status="CREATED", ref=f"mission:{m.id}")
    for e in conn.execute(select(db.events.c.occurred_at, db.events.c.payload, db.events.c.sequence)
                          .where(db.events.c.mission_id == mission_id, db.events.c.event_type == "mission.status_changed")
                          .order_by(db.events.c.sequence)).fetchall():
        p = e.payload or {}
        add(e.occurred_at, "mission", f"Mission {str(p.get('to', '')).lower().replace('_', ' ')}" + (" (paused)" if p.get("paused") else ""),
            detail=p.get("pause_reason") or p.get("failure_reason") or "", status=p.get("to"), ref=f"event:{e.sequence}")

    ids = list(tasks)
    if ids:
        for r in conn.execute(select(db.task_runs).where(db.task_runs.c.task_id.in_(ids))
                              .order_by(db.task_runs.c.started_at.desc()).limit(PER_SOURCE)).fetchall():
            t = tasks[r.task_id]
            add(r.started_at, "step", f"{t.title} (attempt {r.attempt})", agent_id=t.agent_id, task_id=t.id, detail=r.error or "",
                status=r.status, duration_ms=_ms(r.started_at, r.finished_at), ref=f"task_run:{r.id}")
    for x in conn.execute(select(db.tool_executions).where(db.tool_executions.c.mission_id == mission_id)
                          .order_by(db.tool_executions.c.started_at.desc()).limit(PER_SOURCE)).fetchall():
        add(x.started_at, "tool", x.tool_name, agent_id=x.agent_id, task_id=x.task_id, detail=x.output_excerpt or "",
            status=x.status, duration_ms=x.duration_ms, ref=f"tool_execution:{x.id}")
    for u in conn.execute(select(db.usage_records).where(db.usage_records.c.mission_id == mission_id)
                          .order_by(db.usage_records.c.created_at.desc()).limit(PER_SOURCE)).fetchall():
        add(u.created_at, "model", f"AI call · {u.model}", agent_id=u.agent_id, detail=u.provider,
            cost_usd=round(float(u.estimated_cost_usd or 0), 6), tokens=int(u.input_tokens or 0) + int(u.output_tokens or 0),
            ref=f"usage:{u.id}")
    for msg in conn.execute(select(db.agent_messages).where(db.agent_messages.c.mission_id == mission_id)
                            .order_by(db.agent_messages.c.created_at.desc()).limit(PER_SOURCE)).fetchall():
        to = f" → {name(msg.to_agent_id)}" if msg.to_agent_id else ""
        add(msg.created_at, "message", f"{msg.kind.replace('_', ' ').capitalize()}{to}", agent_id=msg.from_agent_id, detail=msg.body,
            ref=f"message:{msg.id}")
    for a in conn.execute(select(db.approvals).where(db.approvals.c.mission_id == mission_id)).fetchall():
        t = tasks.get(a.task_id)
        add(a.created_at, "approval", f"Approval requested: {a.action.replace('_', ' ')}", agent_id=t.agent_id if t else None,
            task_id=a.task_id, detail=a.summary, status="PENDING", ref=f"approval:{a.id}")
        if a.decided_at:
            add(a.decided_at, "approval", f"Approval {a.status.lower()}", task_id=a.task_id, status=a.status, ref=f"approval:{a.id}")
    subjects = ids + [mission_id]
    for d in conn.execute(select(db.manager_decisions).where(db.manager_decisions.c.subject_id.in_(subjects))).fetchall():
        add(d.created_at, "decision", f"Manager: {d.decision_type.replace('_', ' ')} · {d.outcome.replace('_', ' ')}",
            agent_id=d.manager_agent_id, task_id=d.subject_id if d.subject_id in tasks else None, detail=d.rationale,
            ref=f"decision:{d.id}")
    for g in conn.execute(select(db.goal_checkpoints).where(db.goal_checkpoints.c.mission_id == mission_id)).fetchall():
        add(g.created_at, "check", f"Check: {g.status.replace('_', ' ')}", detail="; ".join(g.findings or []), status=g.status,
            ref=f"goal_checkpoint:{g.id}")
    for l in conn.execute(select(db.memory_entries).where(db.memory_entries.c.mission_id == mission_id,
                                                         db.memory_entries.c.content.like("Lesson: %"))).fetchall():
        add(l.created_at, "lesson", "Lesson learned", agent_id=l.agent_id, detail=l.content[len("Lesson: "):], ref=l.source)

    items.sort(key=lambda i: (i["at"] or "", i["kind"] != "mission"))
    # per-agent totals
    per: dict[str, dict] = {}
    for i in items:
        aid = i["agent_id"]
        if not aid:
            continue
        a = per.setdefault(aid, {"agent_id": aid, "agent": i["agent"], "steps": 0, "failed_steps": 0, "tool_calls": 0, "model_calls": 0,
                                 "tokens": 0, "cost_usd": 0.0, "busy_ms": 0})
        if i["kind"] == "step":
            a["steps"] += 1
            a["failed_steps"] += i["status"] == "FAILED"
            a["busy_ms"] += i["duration_ms"] or 0
        elif i["kind"] == "tool":
            a["tool_calls"] += 1
        elif i["kind"] == "model":
            a["model_calls"] += 1
            a["tokens"] += i["tokens"] or 0
            a["cost_usd"] = round(a["cost_usd"] + (i["cost_usd"] or 0), 6)
    end = m.updated_at if m.status in ("COMPLETED", "FAILED", "CANCELLED") else (items[-1]["at"] if items else m.updated_at)
    u = conn.execute(select(func.count(), func.coalesce(func.sum(db.usage_records.c.estimated_cost_usd), 0.0),
                            func.coalesce(func.sum(db.usage_records.c.input_tokens + db.usage_records.c.output_tokens), 0))
                     .where(db.usage_records.c.mission_id == mission_id)).first()
    tools = conn.execute(select(func.count()).select_from(db.tool_executions).where(db.tool_executions.c.mission_id == mission_id)).scalar()
    failed = conn.execute(select(func.count()).select_from(db.task_runs).where(db.task_runs.c.task_id.in_(ids),
                                                                               db.task_runs.c.status == "FAILED")).scalar() if ids else 0
    totals = {"items": len(items), "wall_ms": _ms(m.created_at, end), "cost_usd": round(float(u[1]), 6), "tokens": int(u[2]),
              "tool_calls": int(tools or 0), "model_calls": int(u[0]), "failed_steps": int(failed or 0)}
    truncated = len(items) > MAX_ITEMS
    if truncated:  # keep the start (mission created) and the newest entries, where a failure usually is
        items = items[:1] + items[-(MAX_ITEMS - 1):]
    return {"mission": {"id": m.id, "title": m.title, "status": m.status, "execution_mode": m.execution_mode, "budget_usd": m.budget_usd},
            "items": items, "truncated": truncated,
            "by_agent": sorted(per.values(), key=lambda a: -a["busy_ms"]), "totals": totals, "cost_is_estimate": True}
