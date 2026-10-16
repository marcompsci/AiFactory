"""The owner's charter (services/management/charter.py): anyone signed in can read it; only the owner amends it, and
loosening a rule needs a fresh step-up (authenticator code, or a Supabase session that just did MFA)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from services.api.finance import _require_step_up, owner
from services.core import db
from services.core.auth import Principal, authenticate
from services.core.events import transaction
from services.management import charter

router = APIRouter(prefix="/api/charter")
PURPOSE = "charter"


def member(request: Request) -> Principal:
    return authenticate(request)


class QuietIn(BaseModel):
    start: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    tz: str = Field(default="UTC", max_length=64)


class CharterIn(BaseModel):
    agent_daily_usd: float | None = Field(default=None, ge=0.01, le=charter.MAX_USD)
    mission_budget_cap_usd: float | None = Field(default=None, ge=0.01, le=charter.MAX_USD)
    quiet_hours: QuietIn | None = None
    note: str = Field(default="", max_length=1000)


@router.get("")
def read(p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        return charter.view(conn, p.organization_id)


@router.put("")
def amend(body: CharterIn, p: Principal = Depends(owner), x_step_up: str | None = Header(default=None)) -> dict:
    rules = body.model_dump(exclude={"note"}, exclude_none=True)
    method = _require_step_up(p, x_step_up, PURPOSE) if (x_step_up or p.mfa_fresh) else None
    try:
        with transaction() as conn:
            return charter.amend(conn, org_id=p.organization_id, user_id=p.user_id, new_rules=rules, note=body.note,
                                 step_up_method=method)
    except charter.CharterError as exc:
        raise HTTPException(422, str(exc)) from exc
    except PermissionError as exc:  # loosening without a step-up: ask for one
        raise HTTPException(401, {"code": "step_up_required", "message": str(exc), "purpose": PURPOSE}) from exc
