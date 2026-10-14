"""Mission / agent / project / shared memory.

Trust levels are explicit: `verified` facts must cite a tool execution or artifact as `source`;
anything a model wrote is stored as `hypothesis`. Nothing is promoted automatically.
Local search is substring matching; in Postgres the `embedding vector(1536)` column backs pgvector
similarity search (services/memory/README.md).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, insert, or_, select
from sqlalchemy.engine import Connection

from services.core import db

SCOPES = {"mission", "agent", "project", "shared"}
TRUST = {"verified", "hypothesis"}


def remember(conn: Connection, *, org_id: str, scope: str, trust: str, content: str, source: str,
             mission_id: str | None = None, agent_id: str | None = None, ttl_days: int | None = None) -> str:
    if scope not in SCOPES or trust not in TRUST:
        raise ValueError("bad scope/trust")
    if trust == "verified" and not source.startswith(("tool_execution:", "artifact:")):
        raise ValueError("verified memory must cite a tool execution or artifact")
    mid = db.new_id()
    expires = (datetime.now(timezone.utc) + timedelta(days=ttl_days)).isoformat() if ttl_days else None
    conn.execute(insert(db.memory_entries).values(id=mid, organization_id=org_id, scope=scope, trust=trust, content=content[:4000],
                                                  source=source, mission_id=mission_id, agent_id=agent_id, expires_at=expires))
    return mid


def search(conn: Connection, org_id: str, query: str = "", limit: int = 50, trust: str | None = None) -> list[dict]:
    q = select(db.memory_entries).where(db.memory_entries.c.organization_id == org_id)
    if query:
        q = q.where(db.memory_entries.c.content.ilike(f"%{query}%"))
    if trust:
        q = q.where(db.memory_entries.c.trust == trust)
    now = db.utcnow()
    q = q.where(or_(db.memory_entries.c.expires_at.is_(None), db.memory_entries.c.expires_at > now))
    return [dict(r._mapping) for r in conn.execute(q.order_by(db.memory_entries.c.created_at.desc()).limit(limit))]


def forget(conn: Connection, org_id: str, memory_id: str) -> bool:
    res = conn.execute(delete(db.memory_entries).where(db.memory_entries.c.organization_id == org_id, db.memory_entries.c.id == memory_id))
    return res.rowcount > 0


def purge_expired(conn: Connection) -> int:
    return conn.execute(delete(db.memory_entries).where(db.memory_entries.c.expires_at.is_not(None),
                                                        db.memory_entries.c.expires_at <= db.utcnow())).rowcount
