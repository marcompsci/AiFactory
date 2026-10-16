"""Who works with whom: the town's collaboration network, built only from real records.

Project Sid (Altera, 2024) found that agents' roles persisted only when they had social awareness, a sense of who
they work with. Here the links are concrete: a handoff is a task that waited on another agent's finished task, a
message is one agent writing to another, and a package is work riding the conveyor from one district to another.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.engine import Connection

from services.core import db

MAX_ROWS = 5000


def network(conn: Connection, org_id: str, days: int = 30) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    agents = {a.id: a for a in conn.execute(select(db.agents.c.id, db.agents.c.name, db.agents.c.role, db.agents.c.home_district)
                                            .where(db.agents.c.organization_id == org_id)).fetchall()}
    edges: dict[tuple[str, str], dict] = {}
    flows: dict[tuple[str, str], dict] = {}

    def edge(a: str, b: str, kind: str, at: str) -> None:
        if a == b or a not in agents or b not in agents:
            return
        k = tuple(sorted((a, b)))
        e = edges.setdefault(k, {"a": k[0], "b": k[1], "a_name": agents[k[0]].name, "b_name": agents[k[1]].name,
                                 "handoffs": 0, "messages": 0, "weight": 0, "last_at": ""})
        e[kind] += 1
        e["weight"] += 2 if kind == "handoffs" else 1  # a handoff is joint work; a message is a lighter touch
        e["last_at"] = max(e["last_at"], at or "")

    def flow(src: str | None, dst: str | None, kind: str, at: str) -> None:
        if not src or not dst or src == dst:
            return
        f = flows.setdefault((src, dst), {"from": src, "to": dst, "handoffs": 0, "packages": 0, "weight": 0, "last_at": ""})
        f[kind] += 1
        f["weight"] += 1
        f["last_at"] = max(f["last_at"], at or "")

    counted = [0, 0, 0]
    up = db.tasks.alias("up")
    down = db.tasks.alias("down")
    for r in conn.execute(select(up.c.agent_id.label("a"), up.c.district.label("da"), down.c.agent_id.label("b"),
                                 down.c.district.label("db"), down.c.updated_at.label("at"))
                          .select_from(db.task_dependencies.join(down, down.c.id == db.task_dependencies.c.task_id)
                                       .join(up, up.c.id == db.task_dependencies.c.depends_on_task_id))
                          .where(down.c.organization_id == org_id, up.c.status.in_(["COMPLETED", "SKIPPED"]),
                                 down.c.status.notin_(["PENDING", "CANCELLED"]), down.c.updated_at >= since)
                          .order_by(down.c.updated_at.desc()).limit(MAX_ROWS)).fetchall():
        counted[0] += 1
        edge(r.a, r.b, "handoffs", r.at)
        flow(r.da, r.db, "handoffs", r.at)
    for m in conn.execute(select(db.agent_messages.c.from_agent_id, db.agent_messages.c.to_agent_id, db.agent_messages.c.created_at)
                          .where(db.agent_messages.c.organization_id == org_id, db.agent_messages.c.to_agent_id.isnot(None),
                                 db.agent_messages.c.created_at >= since)
                          .order_by(db.agent_messages.c.created_at.desc()).limit(MAX_ROWS)).fetchall():
        counted[1] += 1
        edge(m.from_agent_id, m.to_agent_id, "messages", m.created_at)
    for p in conn.execute(select(db.logistics_packages.c.origin_district, db.logistics_packages.c.destination_district,
                                 db.logistics_packages.c.created_at)
                          .where(db.logistics_packages.c.organization_id == org_id, db.logistics_packages.c.created_at >= since)
                          .order_by(db.logistics_packages.c.created_at.desc()).limit(MAX_ROWS)).fetchall():
        counted[2] += 1
        flow(p.origin_district, p.destination_district, "packages", p.created_at)

    partners: dict[str, list[dict]] = {}
    for e in edges.values():
        for me, other in ((e["a"], e["b"]), (e["b"], e["a"])):
            partners.setdefault(me, []).append({"agent_id": other, "name": agents[other].name, "role": agents[other].role,
                                                "weight": e["weight"], "handoffs": e["handoffs"], "messages": e["messages"]})
    for v in partners.values():
        v.sort(key=lambda p: -p["weight"])
    return {
        "days": days,
        "edges": sorted(edges.values(), key=lambda e: -e["weight"]),
        "flows": sorted(flows.values(), key=lambda f: -f["weight"]),
        "partners": {k: v[:5] for k, v in partners.items()},
        "agents": [{"id": a.id, "name": a.name, "role": a.role, "home_district": a.home_district} for a in agents.values()],
        "method": "records",
        "truncated": any(n >= MAX_ROWS for n in counted),  # only the newest MAX_ROWS of each kind were read
    }
