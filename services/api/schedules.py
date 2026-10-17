"""Scheduled missions (services/management/schedules.py). Anyone signed in can see them; only the owner creates,
pauses, resumes or deletes one."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from services.api.finance import owner
from services.core import db
from services.core.auth import Principal, authenticate
from services.core.events import transaction
from services.management import schedules

router = APIRouter(prefix="/api/schedules")


def member(request: Request) -> Principal:
    return authenticate(request)


class ScheduleIn(BaseModel):
    kind: str = Field(pattern="^(run_tests|market_research)$")
    params: dict = Field(default_factory=dict)
    cadence: str = Field(pattern="^(daily|weekly|weekdays)$")
    weekday: int | None = Field(default=None, ge=0, le=6)
    hour: int = Field(ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    tz: str = Field(default="UTC", max_length=64)
    title: str = Field(min_length=3, max_length=160)


class EnabledIn(BaseModel):
    enabled: bool


@router.get("")
def list_schedules(p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        return {"schedules": schedules.listing(conn, p.organization_id)}


@router.post("", status_code=201)
def create(body: ScheduleIn, p: Principal = Depends(owner)) -> dict:
    params = body.params if body.kind == "market_research" else {"prompt": "Run the test suite of the connected repository and report which tests fail."}
    try:
        with transaction() as conn:
            return schedules.create(conn, org_id=p.organization_id, user_id=p.user_id, kind=body.kind, params=params, cadence=body.cadence,
                                    weekday=body.weekday, hour=body.hour, minute=body.minute, tz=body.tz, title=body.title)
    except schedules.ScheduleError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/{sid}/enabled")
def set_enabled(sid: str, body: EnabledIn, p: Principal = Depends(owner)) -> dict:
    try:
        with transaction() as conn:
            return schedules.set_enabled(conn, p.organization_id, sid, body.enabled)
    except schedules.ScheduleError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{sid}/skip")
def skip(sid: str, p: Principal = Depends(owner)) -> dict:
    """Skip the next run only; the one after happens as usual."""
    try:
        with transaction() as conn:
            return schedules.skip_next(conn, p.organization_id, sid)
    except schedules.ScheduleError as exc:
        raise HTTPException(404 if "not found" in str(exc) else 409, str(exc)) from exc


@router.post("/{sid}/run-now")
def run_now(sid: str, p: Principal = Depends(owner)) -> dict:
    """Start one run now, as you (quiet hours don't hold work you start yourself; the emergency stop does). The regular
    slots are unchanged. A second tap within a few seconds returns the run that just started."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    with db.get_engine().connect() as conn:
        s = schedules.get(conn, p.organization_id, sid)
    if s is None:
        raise HTTPException(404, "schedule not found")
    from sqlalchemy import or_, update
    S = db.mission_schedules
    with transaction() as conn:  # claim the run (inside the write lock), so two taps can't both start one
        claimed = conn.execute(update(S).where(S.c.id == sid, or_(S.c.last_run_at.is_(None),
                                                                  S.c.last_run_at < (now - timedelta(seconds=10)).isoformat()))
                               .values(last_run_at=now.isoformat())).rowcount
    if not claimed:
        return {"mission_id": s.get("last_mission_id"), "schedule": s, "repeat": True}
    mid, err = schedules.start(s, slot_key="now:" + now.strftime("%Y%m%dT%H%M%S"), user_id=p.user_id)
    with transaction() as conn:
        schedules.record_run(conn, sid, mission_id=mid, error=err)
    if err:
        raise HTTPException(409, err)
    with db.get_engine().connect() as conn:
        return {"mission_id": mid, "schedule": schedules.get(conn, p.organization_id, sid), "repeat": False}


@router.delete("/{sid}")
def remove(sid: str, p: Principal = Depends(owner)) -> dict:
    try:
        with transaction() as conn:
            schedules.remove(conn, p.organization_id, sid)
    except schedules.ScheduleError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True}
