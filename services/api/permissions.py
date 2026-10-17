"""Least-privilege review (services/management/permissions_review.py). Anyone signed in can read it; only the owner
revokes (immediate) or restores (needs a fresh step-up, since it widens what an agent can do)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from services.api.finance import _require_step_up, owner
from services.core import db
from services.core.auth import Principal, authenticate
from services.core.events import transaction
from services.management import permissions_review as pr

router = APIRouter(prefix="/api/permissions")


def member(request: Request) -> Principal:
    return authenticate(request)


class RevokeIn(BaseModel):
    agent_id: str = Field(min_length=1, max_length=64)
    tool: str = Field(min_length=1, max_length=80)
    reason: str = Field(default="", max_length=500)


class RestoreIn(BaseModel):
    revocation_id: str = Field(min_length=1, max_length=64)


@router.get("/review")
def review(days: int = Query(30, ge=1, le=365), p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        return pr.review(conn, p.organization_id, days)


@router.post("/revoke")
def revoke(body: RevokeIn, p: Principal = Depends(owner)) -> dict:
    try:
        with transaction() as conn:
            return pr.revoke(conn, org_id=p.organization_id, agent_id=body.agent_id, tool=body.tool, user_id=p.user_id, reason=body.reason)
    except pr.ReviewError as exc:
        raise HTTPException(404, str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(409, "already revoked") from exc


@router.post("/restore")
def restore(body: RestoreIn, p: Principal = Depends(owner), x_step_up: str | None = Header(default=None)) -> dict:
    _require_step_up(p, x_step_up, "permissions")
    try:
        with transaction() as conn:
            return pr.restore(conn, org_id=p.organization_id, revocation_id=body.revocation_id, user_id=p.user_id)
    except pr.ReviewError as exc:
        raise HTTPException(409, str(exc)) from exc
