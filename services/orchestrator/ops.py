"""State-changing operations shared by the runner and the API. Each writes state + event atomically."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection

from services.core import db
from services.core.config import get_settings
from services.core.events import emit, transaction
from services.core.state import assert_transition


def mission_row(conn: Connection, mission_id: str):
    return conn.execute(select(db.missions).where(db.missions.c.id == mission_id)).first()


def set_mission_status(conn: Connection, mission_id: str, target: str, **extra) -> None:
    m = mission_row(conn, mission_id)
    assert_transition("mission", m.status, target)
    if m.status == target and not extra:
        return
    conn.execute(update(db.missions).where(db.missions.c.id == mission_id).values(status=target, updated_at=db.utcnow(), **extra))
    event = {"COMPLETED": "mission.completed", "FAILED": "mission.failed", "CANCELLED": "mission.cancelled"}.get(target)
    if target == "RUNNING" and m.status == "QUEUED":
        event = "mission.started"
    emit(conn, event or "mission.status_changed", mission_id=mission_id, execution_mode=m.execution_mode,
         payload={"from": m.status, "to": target, **{k: v for k, v in extra.items() if k in ("failure_reason", "outcome")}})


def set_task_status(conn: Connection, task_id: str, target: str, outputs: dict | None = None, error: str | None = None) -> None:
    t = conn.execute(select(db.tasks).where(db.tasks.c.id == task_id)).first()
    assert_transition("task", t.status, target)
    values: dict = {"status": target, "updated_at": db.utcnow()}
    if outputs is not None:
        values["outputs"] = outputs
    if target == "RUNNING" and t.status == "PENDING":
        values["attempt"] = t.attempt + 1
    conn.execute(update(db.tasks).where(db.tasks.c.id == task_id).values(**values))
    mode = mission_row(conn, t.mission_id).execution_mode
    ev = {"RUNNING": "task.started", "COMPLETED": "task.completed", "FAILED": "task.failed"}.get(target, "task.progress")
    payload = {"task_id": task_id, "key": t.key, "title": t.title, "status": target, "district": t.district,
               "attempt": values.get("attempt", t.attempt)}
    if error:
        payload["error"] = error[:1000]
    if t.status == "WAITING_FOR_APPROVAL" and target == "RUNNING":
        ev = "task.progress"
    emit(conn, ev, mission_id=t.mission_id, agent_id=t.agent_id, execution_mode=mode, payload=payload)


def set_agent_state(conn: Connection, agent_id: str, target: str, mission_id: str | None = None, mode: str = "live") -> None:
    a = conn.execute(select(db.agents).where(db.agents.c.id == agent_id)).first()
    current = a.execution_state
    if current == target:
        return
    assert_transition("agent", current, target)
    conn.execute(update(db.agents).where(db.agents.c.id == agent_id).values(execution_state=target, updated_at=db.utcnow()))
    emit(conn, "agent.status_changed", mission_id=mission_id, agent_id=agent_id, execution_mode=mode,
         payload={"from": current, "to": target})


def reset_agent(conn: Connection, agent_id: str, reason: str) -> None:
    """Recovery only (worker restart / cancellation): force IDLE and log why. Not a normal transition."""
    a = conn.execute(select(db.agents).where(db.agents.c.id == agent_id)).first()
    if a.execution_state == "IDLE":
        return
    conn.execute(update(db.agents).where(db.agents.c.id == agent_id).values(execution_state="IDLE", updated_at=db.utcnow()))
    emit(conn, "agent.status_changed", agent_id=agent_id, payload={"from": a.execution_state, "to": "IDLE", "reason": reason})


def request_move(conn: Connection, agent_id: str, district: str, waypoint: str | None, mission_id: str | None, mode: str) -> bool:
    pos = conn.execute(select(db.agent_positions).where(db.agent_positions.c.agent_id == agent_id)).first()
    if pos and pos.district == district and pos.waypoint == waypoint:
        return False
    conn.execute(update(db.agent_positions).where(db.agent_positions.c.agent_id == agent_id).values(
        movement_state="MOVING", updated_at=db.utcnow()))
    emit(conn, "agent.movement_requested", mission_id=mission_id, agent_id=agent_id, execution_mode=mode,
         payload={"from_district": pos.district if pos else None, "to_district": district, "waypoint": waypoint})
    return True


def arrive(conn: Connection, agent_id: str, district: str, waypoint: str | None, mission_id: str | None, mode: str) -> None:
    conn.execute(update(db.agent_positions).where(db.agent_positions.c.agent_id == agent_id).values(
        district=district, waypoint=waypoint, movement_state="STATIONARY", updated_at=db.utcnow()))
    emit(conn, "agent.arrived", mission_id=mission_id, agent_id=agent_id, execution_mode=mode,
         payload={"district": district, "waypoint": waypoint})


def message(conn: Connection, *, mission_id: str | None, from_agent: str | None, to_agent: str | None, kind: str, body: str,
            mode: str, org_id: str) -> None:
    mid = db.new_id()
    conn.execute(insert(db.agent_messages).values(id=mid, organization_id=org_id, mission_id=mission_id, from_agent_id=from_agent,
                                                  to_agent_id=to_agent, kind=kind, body=body[:4000]))
    emit(conn, "agent.message", mission_id=mission_id, agent_id=from_agent, execution_mode=mode,
         payload={"message_id": mid, "to_agent_id": to_agent, "kind": kind, "body": body[:4000]})


# ------------------------------------------------------------------ costs

class BudgetExceeded(RuntimeError):
    pass


def spent_today(conn: Connection, org_id: str) -> float:
    day = datetime.now(timezone.utc).date().isoformat()
    v = conn.execute(select(func.coalesce(func.sum(db.usage_records.c.estimated_cost_usd), 0.0)).where(
        db.usage_records.c.organization_id == org_id, db.usage_records.c.created_at >= day)).scalar()
    return float(v or 0)


def agent_spent(conn: Connection, mission_id: str, agent_id: str) -> float:
    v = conn.execute(select(func.coalesce(func.sum(db.usage_records.c.estimated_cost_usd), 0.0)).where(
        db.usage_records.c.mission_id == mission_id, db.usage_records.c.agent_id == agent_id)).scalar()
    return float(v or 0)


def check_budget(conn: Connection, mission_id: str, agent_id: str, org_id: str) -> None:
    m = mission_row(conn, mission_id)
    org = conn.execute(select(db.organizations).where(db.organizations.c.id == org_id)).first()
    agent = conn.execute(select(db.agents).where(db.agents.c.id == agent_id)).first()
    if m.spent_usd_estimated >= m.budget_usd:
        raise BudgetExceeded(f"mission budget ${m.budget_usd:.2f} reached (estimated)")
    if agent_spent(conn, mission_id, agent_id) >= agent.max_usd_per_mission:
        raise BudgetExceeded(f"{agent.name}'s per-mission limit ${agent.max_usd_per_mission:.2f} reached (estimated)")
    if spent_today(conn, org_id) >= org.daily_budget_usd:
        raise BudgetExceeded(f"daily cap ${org.daily_budget_usd:.2f} reached (estimated)")
    if agent.department_id:
        dept = conn.execute(select(db.departments).where(db.departments.c.id == agent.department_id)).first()
        day = datetime.now(timezone.utc).date().isoformat()
        dept_spent = conn.execute(select(func.coalesce(func.sum(db.usage_records.c.estimated_cost_usd), 0.0))
                                  .join(db.agents, db.agents.c.id == db.usage_records.c.agent_id)
                                  .where(db.agents.c.department_id == dept.id, db.usage_records.c.created_at >= day)).scalar() or 0.0
        if dept_spent >= dept.daily_budget_usd:
            raise BudgetExceeded(f"{dept.name} daily budget ${dept.daily_budget_usd:.2f} reached (estimated)")
    from services.management import charter  # the owner's stricter rules (services/management/charter.py)
    broken = charter.budget_violation(conn, org_id=org_id, agent_id=agent_id, agent_name=agent.name,
                                      mission_budget=m.budget_usd, mission_spent=m.spent_usd_estimated)
    if broken:
        raise BudgetExceeded(broken)


def record_usage(conn: Connection, *, org_id: str, mission_id: str, agent_id: str, provider: str, model: str,
                 input_tokens: int, output_tokens: int, estimated_cost_usd: float) -> None:
    conn.execute(insert(db.usage_records).values(id=db.new_id(), organization_id=org_id, mission_id=mission_id, agent_id=agent_id,
                                                 provider=provider, model=model, input_tokens=input_tokens,
                                                 output_tokens=output_tokens, estimated_cost_usd=estimated_cost_usd))
    m = mission_row(conn, mission_id)
    spent = round(m.spent_usd_estimated + estimated_cost_usd, 6)
    conn.execute(update(db.missions).where(db.missions.c.id == mission_id).values(spent_usd_estimated=spent))
    warn = spent >= m.budget_usd * get_settings().cost_warning_ratio
    emit(conn, "usage.recorded", mission_id=mission_id, agent_id=agent_id, execution_mode=m.execution_mode,
         payload={"provider": provider, "model": model, "input_tokens": input_tokens, "output_tokens": output_tokens,
                  "estimated_cost_usd": estimated_cost_usd, "mission_spent_estimated_usd": spent,
                  "mission_budget_usd": m.budget_usd, "warning": warn, "cost_is_estimate": True})


def run_in_txn(fn, *args, **kwargs):
    with transaction() as conn:
        return fn(conn, *args, **kwargs)
