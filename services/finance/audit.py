"""Tamper-evident financial audit log (THREAT_MODEL F12).

Rows are append-only (database triggers) and each row's hash covers its content and the previous row's hash,
so editing or deleting any row (even with direct database access, bypassing the trigger) breaks `verify()`.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import func, insert, select
from sqlalchemy.engine import Connection

from services.core import db

from .redaction import scrub

GENESIS = "0" * 64


def _digest(prev: str, row: dict) -> str:
    body = json.dumps({k: row[k] for k in ("organization_id", "seq", "actor_type", "actor_id", "action", "subject_type",
                                           "subject_id", "detail", "created_at")}, sort_keys=True, default=str)
    return hashlib.sha256((prev + body).encode()).hexdigest()


def _safe(detail: dict) -> dict:
    out = {}
    for k, v in (detail or {}).items():
        out[k] = scrub(v) if isinstance(v, str) else v
    return out


def record(conn: Connection, *, org_id: str, actor_type: str, actor_id: str | None, action: str, subject_type: str,
           subject_id: str | None, detail: dict | None = None) -> str:
    # Callers hold the process write lock (events.transaction); Postgres additionally enforces unique(org, seq).
    last = conn.execute(select(db.financial_audit_events.c.seq, db.financial_audit_events.c.hash)
                        .where(db.financial_audit_events.c.organization_id == org_id)
                        .order_by(db.financial_audit_events.c.seq.desc()).limit(1)).first()
    seq = (last.seq + 1) if last else 1
    prev = last.hash if last else GENESIS
    row = {"id": db.new_id(), "organization_id": org_id, "seq": seq, "actor_type": actor_type, "actor_id": actor_id, "action": action,
           "subject_type": subject_type, "subject_id": subject_id, "detail": _safe(detail or {}), "created_at": db.utcnow()}
    row["prev_hash"] = prev
    row["hash"] = _digest(prev, row)
    conn.execute(insert(db.financial_audit_events).values(**row))
    return row["id"]


def verify(conn: Connection, org_id: str) -> dict:
    rows = conn.execute(select(db.financial_audit_events).where(db.financial_audit_events.c.organization_id == org_id)
                        .order_by(db.financial_audit_events.c.seq)).fetchall()
    prev = GENESIS
    for i, r in enumerate(rows, start=1):
        d = dict(r._mapping)
        if d["seq"] != i or d["prev_hash"] != prev or _digest(prev, d) != d["hash"]:
            return {"ok": False, "entries": len(rows), "broken_at_seq": d["seq"]}
        prev = d["hash"]
    return {"ok": True, "entries": len(rows), "head": prev}


def count(conn: Connection, org_id: str) -> int:
    return conn.execute(select(func.count()).select_from(db.financial_audit_events)
                        .where(db.financial_audit_events.c.organization_id == org_id)).scalar() or 0
