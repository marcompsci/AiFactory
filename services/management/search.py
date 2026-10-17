"""Search the records: missions, steps, agent messages, lessons, manager decisions and artifacts, in one list.

Plain case-insensitive substring matching on the stored text (no model, nothing summarised), scoped to the caller's
organization. Each result says where it came from and, when it belongs to a mission, links to that mission's trace.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.engine import Connection

from services.core import db

PER_KIND = 15


def _snippet(text: str, q: str, width: int = 140) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    i = t.lower().find(q.lower())
    if i < 0:
        return t[:width]
    start = max(0, i - width // 3)
    out = t[start:start + width]
    return ("…" if start else "") + out + ("…" if start + width < len(t) else "")


def search(conn: Connection, org_id: str, q: str) -> dict:
    q = q.strip()[:100]
    if len(q) < 2:
        return {"query": q, "results": [], "total": 0}
    like = f"%{q}%"
    out: list[dict] = []
    agents = {a.id: a.name for a in conn.execute(select(db.agents.c.id, db.agents.c.name).where(db.agents.c.organization_id == org_id))}
    M = db.missions
    for r in conn.execute(select(M.c.id, M.c.title, M.c.prompt, M.c.failure_reason, M.c.status, M.c.updated_at)
                          .where(M.c.organization_id == org_id, (M.c.title.ilike(like)) | (M.c.prompt.ilike(like)) | (M.c.failure_reason.ilike(like)))
                          .order_by(M.c.updated_at.desc()).limit(PER_KIND)).fetchall():
        text = next((x for x in (r.title, r.failure_reason, r.prompt) if x and q.lower() in x.lower()), r.title)
        out.append({"kind": "mission", "title": r.title, "snippet": _snippet(text, q), "mission_id": r.id, "at": r.updated_at,
                    "status": r.status, "ref": f"mission:{r.id}"})
    T = db.tasks
    for r in conn.execute(select(T.c.id, T.c.title, T.c.mission_id, T.c.agent_id, T.c.status, T.c.updated_at)
                          .where(T.c.organization_id == org_id, T.c.title.ilike(like)).order_by(T.c.updated_at.desc()).limit(PER_KIND)).fetchall():
        out.append({"kind": "step", "title": r.title, "snippet": f"{agents.get(r.agent_id, '')} · {r.status.lower()}", "mission_id": r.mission_id,
                    "at": r.updated_at, "status": r.status, "ref": f"task:{r.id}"})
    A = db.agent_messages
    for r in conn.execute(select(A.c.id, A.c.body, A.c.mission_id, A.c.from_agent_id, A.c.created_at)
                          .where(A.c.organization_id == org_id, A.c.body.ilike(like)).order_by(A.c.created_at.desc()).limit(PER_KIND)).fetchall():
        out.append({"kind": "message", "title": f"{agents.get(r.from_agent_id, 'Agent')} said", "snippet": _snippet(r.body, q),
                    "mission_id": r.mission_id, "at": r.created_at, "status": None, "ref": f"message:{r.id}"})
    E = db.memory_entries
    for r in conn.execute(select(E.c.id, E.c.content, E.c.mission_id, E.c.agent_id, E.c.source, E.c.created_at)
                          .where(E.c.organization_id == org_id, E.c.content.ilike(like)).order_by(E.c.created_at.desc()).limit(PER_KIND)).fetchall():
        kind = "lesson" if r.content.startswith("Lesson: ") else "memory"
        out.append({"kind": kind, "title": f"{agents.get(r.agent_id, 'Shared')} · {kind}", "snippet": _snippet(r.content, q),
                    "mission_id": r.mission_id, "at": r.created_at, "status": None, "ref": r.source})
    D = db.manager_decisions
    for r in conn.execute(select(D.c.id, D.c.decision_type, D.c.outcome, D.c.rationale, D.c.subject_type, D.c.subject_id, D.c.created_at)
                          .where(D.c.organization_id == org_id, D.c.rationale.ilike(like)).order_by(D.c.created_at.desc()).limit(PER_KIND)).fetchall():
        out.append({"kind": "decision", "title": f"Manager: {r.decision_type.replace('_', ' ')} · {r.outcome.replace('_', ' ')}",
                    "snippet": _snippet(r.rationale, q), "mission_id": r.subject_id if r.subject_type == "mission" else None,
                    "at": r.created_at, "status": None, "ref": f"decision:{r.id}"})
    R = db.artifacts
    for r in conn.execute(select(R.c.id, R.c.title, R.c.kind, R.c.mission_id, R.c.created_at)
                          .where(R.c.organization_id == org_id, R.c.title.ilike(like)).order_by(R.c.created_at.desc()).limit(PER_KIND)).fetchall():
        out.append({"kind": "artifact", "title": r.title, "snippet": r.kind, "mission_id": r.mission_id, "at": r.created_at,
                    "status": None, "ref": f"artifact:{r.id}"})
    out.sort(key=lambda x: x["at"] or "", reverse=True)
    counts: dict[str, int] = {}
    for x in out:
        counts[x["kind"]] = counts.get(x["kind"], 0) + 1
    return {"query": q, "results": out, "total": len(out), "counts": counts, "method": "text match"}
