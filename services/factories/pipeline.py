"""Keeps the factories current: a factory_sync mission every AICIV_FACTORY_SYNC_MINUTES (default 5) while a source is
linked, so Coda and Rook visibly walk to their consoles and do the reading as real, logged tool calls."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select

from services.core import db
from services.core.events import transaction
from services.management.hierarchy import agent_by_key
from services.management.pipeline import create_mission


def linked_kinds(conn, org: str) -> list[str]:
    return [r.kind for r in conn.execute(select(db.factory_links.c.kind).where(db.factory_links.c.organization_id == org,
                                                                               db.factory_links.c.enabled == 1))]


def start_sync(conn, org: str, created_by: str | None = None) -> str | None:
    from services.model_gateway import plans

    kinds = linked_kinds(conn, org)
    meters = plans.enabled() or "codex" in kinds or "claude_code" in kinds
    if not kinds and not meters:
        return None
    running = conn.execute(select(db.missions.c.id).where(db.missions.c.kind == "factory_sync",
                                                          db.missions.c.status.notin_(("COMPLETED", "FAILED", "CANCELLED")))).first()
    if running:
        return None
    tasks = [t for t, k in (("claude_sync", "claude_code"), ("github_sync", "github"), ("codex_sync", "codex")) if k in kinds]
    if meters:
        tasks += ["codex_usage", "claude_usage"]
    return create_mission(conn, org_id=org, kind="factory_sync", title="Factory check-in: Claude Code, Codex, GitHub and plan usage",
                          prompt="Read-only: refresh the factory boards and the plan usage meters.", params={"tasks": tasks},
                          opportunity_id=None, created_by=created_by or agent_by_key(conn, "claude_liaison").id)


def tick(enqueue: Callable[[str], None]) -> dict:
    every = float(os.environ.get("AICIV_FACTORY_SYNC_MINUTES", "5"))
    now = datetime.now(timezone.utc)
    started = None
    with transaction() as conn:
        from services.model_gateway import plans

        orgs = {r[0] for r in conn.execute(select(db.factory_links.c.organization_id).where(db.factory_links.c.enabled == 1).distinct())}
        if plans.enabled():
            orgs |= {r[0] for r in conn.execute(select(db.organizations.c.id))}
        for org in sorted(orgs):
            last = conn.execute(select(db.missions.c.created_at).where(db.missions.c.kind == "factory_sync", db.missions.c.organization_id == org)
                                .order_by(db.missions.c.created_at.desc())).first()
            if last and now - datetime.fromisoformat(str(last.created_at).replace("Z", "+00:00")) < timedelta(minutes=every):
                continue
            started = start_sync(conn, org)
    if started:
        enqueue(started)
    return {"started": bool(started)}
