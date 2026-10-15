"""Factory tools. Read-only. `sync_*` only run in a factory_sync mission (see registry._check_factory) and only when the
owner linked that source; `read_claude_code_memory` is shared with the other agents as a research aid."""
from __future__ import annotations

from sqlalchemy import select

from services.core import db
from services.core.events import emit, transaction
from services.tools.registry import ToolContext, ToolFailed, tool

from . import claude_code as CC
from . import github as GH


def linked(conn, org_id: str, kind: str) -> bool:
    r = conn.execute(select(db.factory_links.c.enabled).where(db.factory_links.c.organization_id == org_id, db.factory_links.c.kind == kind)).first()
    return bool(r and r.enabled)


def _save(conn, org: str, kind: str, data: dict, mission_id: str | None) -> None:
    conn.execute(db.factory_snapshots.insert().values(id=db.new_id(), organization_id=org, kind=kind, data=data, mission_id=mission_id))
    # keep the last 20 snapshots per source
    old = conn.execute(select(db.factory_snapshots.c.id).where(db.factory_snapshots.c.organization_id == org, db.factory_snapshots.c.kind == kind)
                       .order_by(db.factory_snapshots.c.synced_at.desc()).offset(20)).fetchall()
    if old:
        conn.execute(db.factory_snapshots.delete().where(db.factory_snapshots.c.id.in_([r.id for r in old])))


@tool("sync_claude_code", factory=True, description="Read recent Claude Code sessions, completed tasks and memory on this computer (read-only).")
def sync_claude_code(ctx: ToolContext) -> dict:
    with db.get_engine().connect() as conn:
        if not linked(conn, ctx.org_id, "claude_code"):
            raise ToolFailed("Claude Code is not linked")
    if not CC.available():
        raise ToolFailed("no Claude Code data found on the computer running the API")
    sess = CC.sessions()
    mem = CC.memory_files(sess)
    data = {"sessions": [CC.public(s) for s in sess], "memory": [{k: v for k, v in m.items() if not k.startswith("_")} for m in mem],
            "completed_recent": sum(len(s["completed_tasks"]) for s in sess), "active": sum(1 for s in sess if s.get("active"))}
    with transaction() as conn:
        _save(conn, ctx.org_id, "claude_code", data, ctx.mission_id)
        emit(conn, "factory.synced", mission_id=ctx.mission_id, agent_id=ctx.agent_id, execution_mode=ctx.execution_mode,
             payload={"kind": "claude_code", "sessions": len(sess), "memory_files": len(mem), "completed_tasks": data["completed_recent"]})
    return {"status": "synced", "count": len(sess), "memory_files": len(mem), "completed_tasks": data["completed_recent"]}


@tool("sync_github_activity", factory=True, description="Read recent commits, pull requests, Actions runs and claude issues for authorized repositories.")
def sync_github_activity(ctx: ToolContext) -> dict:
    with db.get_engine().connect() as conn:
        if not linked(conn, ctx.org_id, "github"):
            raise ToolFailed("GitHub is not linked")
        repos = conn.execute(select(db.lab_repositories).where(db.lab_repositories.c.organization_id == ctx.org_id,
                                                               db.lab_repositories.c.status == "ACTIVE")).fetchall()
    if not repos:
        raise ToolFailed("no authorized repositories; connect one in App Lab first")
    data = {"repos": []}
    for r in repos:
        try:
            data["repos"].append(GH.activity(r))
        except Exception as exc:  # noqa: BLE001 — one repository never blocks the others; recorded, not hidden
            data["repos"].append({"repo": r.full_name, "errors": [type(exc).__name__]})
    with transaction() as conn:
        _save(conn, ctx.org_id, "github", data, ctx.mission_id)
        emit(conn, "factory.synced", mission_id=ctx.mission_id, agent_id=ctx.agent_id, execution_mode=ctx.execution_mode,
             payload={"kind": "github", "repos": len(repos), "pulls": sum(len(x.get("pulls", [])) for x in data["repos"]),
                      "runs": sum(len(x.get("runs", [])) for x in data["repos"])})
    return {"status": "synced", "count": len(repos)}


@tool("read_claude_code_memory", description="Search Claude Code's memory (CLAUDE.md and auto memory) for project conventions and lessons.")
def read_claude_code_memory(ctx: ToolContext, query: str = "") -> dict:
    with db.get_engine().connect() as conn:
        if not linked(conn, ctx.org_id, "claude_code"):
            return {"status": "not_linked", "count": 0, "hits": []}
    hits = CC.search_memory(query[:200])
    return {"status": "ok", "count": len(hits), "hits": hits}
