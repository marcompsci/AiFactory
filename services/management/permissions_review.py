"""Least-privilege review: tools an agent may use but hasn't, so the owner can take them away.

An agent should hold only the tools its work needs. This lists every grant with how often it was used in the last
`days` and whether any mission plan needs it, and suggests revoking grants that are both unused and in no plan.
Nothing is revoked automatically: the owner revokes one tool at a time, a revocation survives restarts (the seed
skips it), and restoring one (loosening) needs a fresh step-up. Every change is an event and a manager decision.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Connection

from services.core import db
from services.core.config import load_seed
from services.core.events import emit
from services.orchestrator.plan import KINDS, plan_for

from .manager import record_decision


class ReviewError(ValueError):
    pass


def plan_tools() -> dict[str, set[str]]:
    """agent key -> every tool some mission plan asks that agent to use."""
    keys = {a["key"] for a in load_seed()["agents"]}
    every_factory_task = ["claude_sync", "github_sync", "codex_sync", "codex_usage", "claude_usage"]
    out: dict[str, set[str]] = {}
    for kind in KINDS:
        for k in sorted(keys) + [None]:
            params = {"tasks": every_factory_task, **({"agent_key": k} if k else {})}
            try:
                graph = plan_for(kind, params)
            except Exception:  # a parameter combination a kind doesn't accept
                continue
            for t in graph:
                out.setdefault(t.agent_key, set()).update(t.permitted_tools)
    return out


_CODE_TOOLS: set[str] | None = None


def code_tools() -> set[str]:
    """Tool names the services call directly (pipelines, handlers), found by scanning the source once."""
    global _CODE_TOOLS
    if _CODE_TOOLS is None:
        root = Path(__file__).resolve().parents[1]
        text = "\n".join(p.read_text(errors="ignore") for p in root.rglob("*.py")
                         if "tools/registry.py" not in str(p) and p.name != "permissions_review.py")
        names = {a for agent in load_seed()["agents"] for a in agent["tools"]}
        calls = re.findall(r"(?:\.tool|execute_tool|_tool|run_tool)\(\s*(?:[\w.]+\s*,\s*)?[\"']([a-z_]+)[\"']", text)
        _CODE_TOOLS = names & set(calls)
    return _CODE_TOOLS


def review(conn: Connection, org_id: str, days: int = 30) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    agents = conn.execute(select(db.agents.c.id, db.agents.c.key, db.agents.c.name, db.agents.c.role)
                          .where(db.agents.c.organization_id == org_id).order_by(db.agents.c.name)).fetchall()
    ids = [a.id for a in agents]
    grants: dict[str, list[str]] = {}
    for r in conn.execute(select(db.agent_capabilities).where(db.agent_capabilities.c.agent_id.in_(ids))).fetchall():
        grants.setdefault(r.agent_id, []).append(r.tool_name)
    used = {(r.agent_id, r.tool_name): (r.n, r.last) for r in conn.execute(
        select(db.tool_executions.c.agent_id, db.tool_executions.c.tool_name, func.count().label("n"),
               func.max(db.tool_executions.c.started_at).label("last"))
        .where(db.tool_executions.c.organization_id == org_id, db.tool_executions.c.started_at >= since)
        .group_by(db.tool_executions.c.agent_id, db.tool_executions.c.tool_name)).fetchall()}
    revoked = [dict(r._mapping) for r in conn.execute(select(db.capability_revocations)
                                                      .where(db.capability_revocations.c.organization_id == org_id,
                                                             db.capability_revocations.c.restored_at.is_(None))
                                                      .order_by(db.capability_revocations.c.revoked_at.desc())).fetchall()]
    needed = plan_tools()
    in_code = code_tools()
    first = conn.execute(select(func.min(db.events.c.occurred_at)).where(db.events.c.organization_id == org_id)).scalar()
    history_ok = bool(first) and first <= since  # suggest only after a full period of records
    out, suggestions = [], 0
    for a in agents:
        rows = []
        for tool in sorted(grants.get(a.id, [])):
            n, last = used.get((a.id, tool), (0, None))
            in_plan = tool in needed.get(a.key, set())
            called = tool in in_code
            suggest = history_ok and n == 0 and not in_plan and not called
            suggestions += suggest
            rows.append({"id": f"{a.id}:{tool}", "tool": tool, "uses": int(n), "last_used": last, "in_plan": in_plan,
                         "suggestion": "revoke" if suggest else "keep",
                         "in_code": called,
                         "why": ("Unused for %d days, and no plan or pipeline asks for it." % days) if suggest else
                                f"Used {n} time(s) in {days} days." if n else
                                "A mission plan needs it." if in_plan else
                                "A pipeline calls it directly." if called else
                                f"Unused so far; suggestions start after {days} days of records."})
        out.append({"agent_id": a.id, "agent": a.name, "role": a.role, "grants": rows,
                    "revoked": [r for r in revoked if r["agent_id"] == a.id]})
    return {"days": days, "agents": out, "suggestions": suggestions, "method": "records", "enough_history": history_ok,
            "note": "Nothing is revoked automatically. Revoking is immediate; restoring needs a fresh step-up."}


def revoke(conn: Connection, *, org_id: str, agent_id: str, tool: str, user_id: str, reason: str) -> dict:
    a = conn.execute(select(db.agents).where(db.agents.c.id == agent_id, db.agents.c.organization_id == org_id)).first()
    if a is None:
        raise ReviewError("agent not found")
    if not conn.execute(select(db.agent_capabilities).where(db.agent_capabilities.c.agent_id == agent_id,
                                                           db.agent_capabilities.c.tool_name == tool)).first():
        raise ReviewError(f"{a.name} doesn't have {tool}")
    in_plan = tool in plan_tools().get(a.key, set())
    conn.execute(delete(db.agent_capabilities).where(db.agent_capabilities.c.agent_id == agent_id, db.agent_capabilities.c.tool_name == tool))
    rid = db.new_id()
    conn.execute(insert(db.capability_revocations).values(id=rid, organization_id=org_id, agent_id=agent_id, tool_name=tool,
                                                          reason=reason[:500], revoked_by=user_id))
    warning = f"A mission plan asks {a.name} to use {tool}; those steps will now be refused." if in_plan else None
    record_decision(conn, decision_type="escalation", subject_type="agent", subject_id=agent_id, outcome="permission_revoked",
                    rationale=f"The owner revoked {tool} from {a.name}. {reason}".strip(), org_id=org_id)
    emit(conn, "permission.revoked", agent_id=agent_id, org_id=org_id,
         payload={"tool": tool, "agent": a.name, "reason": reason[:300], "revocation_id": rid, "in_plan": in_plan})
    return {"revocation_id": rid, "warning": warning}


def restore(conn: Connection, *, org_id: str, revocation_id: str, user_id: str) -> dict:
    r = conn.execute(select(db.capability_revocations).where(db.capability_revocations.c.id == revocation_id,
                                                            db.capability_revocations.c.organization_id == org_id)).first()
    if r is None or r.restored_at:
        raise ReviewError("nothing to restore")
    res = conn.execute(update(db.capability_revocations).where(db.capability_revocations.c.id == revocation_id,
                                                               db.capability_revocations.c.restored_at.is_(None))
                       .values(restored_by=user_id, restored_at=db.utcnow()))
    if (res.rowcount or 0) != 1:
        raise ReviewError("nothing to restore")
    if not conn.execute(select(db.agent_capabilities).where(db.agent_capabilities.c.agent_id == r.agent_id,
                                                           db.agent_capabilities.c.tool_name == r.tool_name)).first():
        conn.execute(insert(db.agent_capabilities).values(agent_id=r.agent_id, tool_name=r.tool_name))
    emit(conn, "permission.restored", agent_id=r.agent_id, org_id=org_id, payload={"tool": r.tool_name, "revocation_id": revocation_id})
    return {"restored": r.tool_name}
