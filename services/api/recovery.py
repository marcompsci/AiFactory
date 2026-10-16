"""Recovery plans (services/management/recovery.py): the General Manager's proposal after a failed mission. Anyone
signed in can read them; only the owner approves or declines, and approving starts a new mission through the same
path as any other (charter caps, emergency stop and approvals all still apply)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from services.api.finance import owner
from services.core import db
from services.core.auth import Principal, authenticate
from services.core.events import transaction
from services.management import recovery

router = APIRouter(prefix="/api/recovery")


def member(request: Request) -> Principal:
    return authenticate(request)


def _pending(conn, plan_id: str, p: Principal) -> dict:
    plan = recovery.plan(conn, plan_id)
    if plan is None or plan["organization_id"] != p.organization_id:
        raise HTTPException(404, "plan not found")
    if plan["status"] != "PENDING":
        raise HTTPException(409, f"this plan is {plan['status'].lower()}")
    return plan


@router.get("")
def list_plans(status: str | None = None, p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        return {"plans": recovery.plans(conn, p.organization_id, status=status)}


@router.post("/{plan_id}/approve")
def approve(plan_id: str, p: Principal = Depends(owner)) -> dict:
    from services.api import main
    with db.get_engine().connect() as conn:
        plan = _pending(conn, plan_id, p)
    params = plan["params"]
    m = main.create_mission(main.MissionIn(prompt=params["prompt"], title=params.get("title"), budget_usd=params.get("budget_usd"),
                                           repository_id=params.get("repository_id"), idempotency_key=f"recovery:{plan_id}"), p)
    with transaction() as conn:
        _pending(conn, plan_id, p)
        recovery.decide(conn, plan_id, user_id=p.user_id, approve=True, new_mission_id=m["id"])
        return {"plan": recovery.plan(conn, plan_id), "mission": m}


@router.post("/{plan_id}/decline")
def decline(plan_id: str, p: Principal = Depends(owner)) -> dict:
    with transaction() as conn:
        _pending(conn, plan_id, p)
        recovery.decide(conn, plan_id, user_id=p.user_id, approve=False)
        return {"plan": recovery.plan(conn, plan_id)}
