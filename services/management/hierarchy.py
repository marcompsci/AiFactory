"""OWNER -> GENERAL MANAGER -> DEPARTMENT SUPERVISORS -> SPECIALIST AGENTS.

Reports always go to the agent's assigned supervisor. Reporting uncertainty, failure or missing data never
changes an agent's budget, permissions or assignment — reports carry information, not scores.
"""
from __future__ import annotations

from sqlalchemy import insert, select
from sqlalchemy.engine import Connection

from services.core import db
from services.core.events import emit

REPORT_KINDS = {"progress", "blocker", "completed_package", "quality_concern", "estimate", "resource_request"}


def agent_by_key(conn: Connection, key: str):
    return conn.execute(select(db.agents).where(db.agents.c.key == key)).first()


def general_manager(conn: Connection):
    return conn.execute(select(db.agents).where(db.agents.c.tier == "general_manager")).first()


def supervisor_of(conn: Connection, agent_id: str) -> str | None:
    r = conn.execute(select(db.agent_reporting_lines.c.supervisor_agent_id).where(db.agent_reporting_lines.c.agent_id == agent_id)).first()
    return r.supervisor_agent_id if r else None


def chain_of_command(conn: Connection, agent_id: str) -> list[str]:
    chain, seen, cur = [], {agent_id}, supervisor_of(conn, agent_id)
    while cur and cur not in seen:
        chain.append(cur)
        seen.add(cur)
        cur = supervisor_of(conn, cur)
    return chain  # ends at the GM; the GM reports to the owner


def department_of(conn: Connection, agent_id: str):
    a = conn.execute(select(db.agents.c.department_id).where(db.agents.c.id == agent_id)).first()
    if not a or not a.department_id:
        return None
    return conn.execute(select(db.departments).where(db.departments.c.id == a.department_id)).first()


def submit_report(conn: Connection, *, org_id: str, agent_id: str, kind: str, body: str, mission_id: str | None = None,
                  task_id: str | None = None, data: dict | None = None, mode: str = "live") -> str:
    if kind not in REPORT_KINDS:
        raise ValueError(f"unknown report kind {kind}")
    rid = db.new_id()
    sup = supervisor_of(conn, agent_id)
    conn.execute(insert(db.agent_reports).values(id=rid, organization_id=org_id, agent_id=agent_id, supervisor_agent_id=sup,
                                                 mission_id=mission_id, task_id=task_id, kind=kind, body=body[:2000], data=data or {}))
    emit(conn, "report.submitted", mission_id=mission_id, agent_id=agent_id, execution_mode=mode,
         payload={"report_id": rid, "kind": kind, "to_agent_id": sup, "body": body[:500], "data": data or {}})
    return rid
