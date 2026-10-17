"""Saved requests (V6.29, services/management/saved.py): anyone signed in can see them; saving, starting and deleting
need the operator role, the same as starting a mission."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from services.core import db
from services.core.auth import Principal, authenticate
from services.management import saved

router = APIRouter(prefix="/api")


def member(request: Request) -> Principal:
    return authenticate(request)


def operator(request: Request) -> Principal:
    from services.api.finance import operator as op  # the operator role plus the mutation rate limit
    return op(request)


class SavedIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    kind: str = Field(pattern="^(fix_failing_test|run_tests|market_research)$")
    prompt: str | None = Field(default=None, max_length=4000)
    params: dict = Field(default_factory=dict)
    title: str | None = Field(default=None, max_length=120)
    budget_usd: float | None = Field(default=None, gt=0, le=50)
    priority: str = Field(default="normal", pattern="^(urgent|normal|low)$")


class NameIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)


def _err(exc: saved.SavedError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


@router.get("/saved-requests")
def list_saved(p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        return {"saved_requests": saved.listing(conn, p.organization_id)}


@router.post("/saved-requests", status_code=201)
def create(body: SavedIn, p: Principal = Depends(operator)) -> dict:
    from services.api.links import RUN_TESTS_PROMPT
    spec = body.model_dump(exclude={"name", "priority"})
    if body.kind == "run_tests" and not body.prompt:
        spec["prompt"] = RUN_TESTS_PROMPT
    try:
        return saved.save(p, body.name, spec, body.priority)
    except saved.SavedError as exc:
        raise _err(exc) from exc


@router.post("/missions/{mission_id}/save", status_code=201)
def save_mission(mission_id: str, body: NameIn, p: Principal = Depends(operator)) -> dict:
    try:
        return saved.save_from_mission(p, mission_id, body.name)
    except saved.SavedError as exc:
        raise _err(exc) from exc


@router.post("/saved-requests/{sid}/start", status_code=201)
def start(sid: str, p: Principal = Depends(operator)) -> dict:
    try:
        return saved.start(p, sid)
    except saved.SavedError as exc:
        raise _err(exc) from exc


@router.delete("/saved-requests/{sid}")
def remove(sid: str, p: Principal = Depends(operator)) -> dict:
    try:
        saved.remove(p, sid)
    except saved.SavedError as exc:
        raise _err(exc) from exc
    return {"ok": True}
