"""Agent tools for the company knowledge base. Read-only for agents; the owner manages it in the app."""
from __future__ import annotations

from services.core import db
from services.core.events import emit, transaction
from services.tools.registry import ToolContext, ToolFailed, tool

from . import kb


@tool("search_knowledge_base", description="Search the Phoronomics / Phoronomic Studios knowledge base for docs and skills.")
def search_knowledge_base(ctx: ToolContext, query: str = "", kind: str | None = None) -> dict:
    with db.get_engine().connect() as conn:
        hits = kb.search(conn, ctx.org_id, query[:300], k=6, kind=kind if kind in kb.KINDS else None)
    return {"status": "ok", "count": len(hits),
            "hits": [{k: h[k] for k in ("slug", "title", "kind", "company_name", "description", "excerpt")} for h in hits]}


@tool("read_knowledge_document", description="Read one knowledge base document or skill in full by its slug.")
def read_knowledge_document(ctx: ToolContext, slug: str = "") -> dict:
    with db.get_engine().connect() as conn:
        row = kb.get(conn, ctx.org_id, kb.slugify(slug))
    if row is None:
        raise ToolFailed(f"no knowledge base entry '{slug}'")
    with transaction() as conn:
        emit(conn, "knowledge.consulted", mission_id=ctx.mission_id, agent_id=ctx.agent_id, execution_mode=ctx.execution_mode,
             payload={"slug": row.slug, "title": row.title, "kind": row.kind})
    return {"status": "ok", "count": 1, "slug": row.slug, "title": row.title, "kind": row.kind, "body": row.body[:20000]}
