"""Claude Code and GitHub factories. Owners and admins can read (session titles and memory are personal); only the
owner links a source or asks for a sync. Everything is read-only."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, update

from services.core import db
from services.core.auth import Principal, authenticate, mutation_limiter
from services.core.events import transaction
from services.factories import claude_code as CC
from services.factories.pipeline import start_sync
from services.finance import audit
from services.finance.permissions import require_finance, require_owner

router = APIRouter(prefix="/api/factories")


def reader(request: Request) -> Principal:
    p = authenticate(request)
    require_finance(p)
    return p


def owner(request: Request) -> Principal:
    p = authenticate(request)
    require_owner(p)
    mutation_limiter.check(p.user_id)
    return p


def _latest(conn, org: str, kind: str):
    return conn.execute(select(db.factory_snapshots).where(db.factory_snapshots.c.organization_id == org, db.factory_snapshots.c.kind == kind)
                        .order_by(db.factory_snapshots.c.synced_at.desc())).first()


@router.get("")
def factories(p: Principal = Depends(reader)):
    with db.get_engine().connect() as conn:
        links = {r.kind: bool(r.enabled) for r in conn.execute(select(db.factory_links).where(db.factory_links.c.organization_id == p.organization_id))}
        out = {}
        for kind in ("claude_code", "github"):
            snap = _latest(conn, p.organization_id, kind)
            out[kind] = {"linked": links.get(kind, False), "synced_at": snap.synced_at if snap else None, "data": snap.data if snap else None}
        out["claude_code"]["found_on_server"] = CC.available()
        out["github"]["repositories"] = [r.full_name for r in conn.execute(select(db.lab_repositories.c.full_name).where(
            db.lab_repositories.c.organization_id == p.organization_id, db.lab_repositories.c.status == "ACTIVE"))]
        running = conn.execute(select(db.missions.c.id, db.missions.c.status).where(db.missions.c.kind == "factory_sync")
                               .order_by(db.missions.c.created_at.desc())).first()
        out["last_sync_mission"] = {"id": running.id, "status": running.status} if running else None
    return out


class LinkIn(BaseModel):
    enabled: bool


@router.post("/{kind}/link")
def link(kind: str, body: LinkIn, p: Principal = Depends(owner)):
    if kind not in ("claude_code", "github"):
        raise HTTPException(status_code=404, detail="unknown factory")
    with transaction() as conn:
        row = conn.execute(select(db.factory_links).where(db.factory_links.c.organization_id == p.organization_id, db.factory_links.c.kind == kind)).first()
        if row:
            conn.execute(update(db.factory_links).where(db.factory_links.c.id == row.id).values(enabled=1 if body.enabled else 0, created_by=p.user_id,
                                                                                             updated_at=db.utcnow()))
        else:
            conn.execute(db.factory_links.insert().values(id=db.new_id(), organization_id=p.organization_id, kind=kind, enabled=1 if body.enabled else 0,
                                                          created_by=p.user_id))
        if not body.enabled:  # unlinking also forgets what was read
            conn.execute(db.factory_snapshots.delete().where(db.factory_snapshots.c.organization_id == p.organization_id,
                                                              db.factory_snapshots.c.kind == kind))
        audit.record(conn, org_id=p.organization_id, actor_type="owner", actor_id=p.user_id, action="factory.link", subject_type="factory",
                     subject_id=None, detail={"kind": kind, "enabled": body.enabled})
        mid = start_sync(conn, p.organization_id) if body.enabled else None
    if mid:
        _enqueue(mid)
    return {"kind": kind, "linked": body.enabled, "sync_mission_id": mid}


@router.post("/sync")
def sync_now(p: Principal = Depends(owner)):
    with transaction() as conn:
        mid = start_sync(conn, p.organization_id, None)
    if mid is None:
        raise HTTPException(status_code=409, detail="nothing linked, or a sync is already running")
    _enqueue(mid)
    return {"mission_id": mid}


def _enqueue(mid: str) -> None:
    try:
        from services.api.main import state
        state.worker.enqueue(mid)
    except Exception:  # noqa: BLE001
        pass
