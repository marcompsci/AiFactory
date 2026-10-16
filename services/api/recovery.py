"""Recovery plans (services/management/recovery.py): the General Manager's proposal after a failed mission. Anyone
signed in can read them; only the owner approves or declines, and approving starts a new mission through the same
path as any other (charter caps, emergency stop and approvals all still apply)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

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
    """Claim the plan first (only one approve or decline can win), then start the mission; if the mission can't be
    created (emergency stop, charter cap), the plan goes back to waiting."""
    from services.api import main
    with transaction() as conn:
        plan = _pending(conn, plan_id, p)
        if not recovery.claim(conn, plan_id, user_id=p.user_id, approve=True):
            raise HTTPException(409, "this plan was already decided")
    params = plan["params"]
    try:
        m = main.create_mission(main.MissionIn(prompt=params["prompt"], title=params.get("title"), budget_usd=params.get("budget_usd"),
                                               repository_id=params.get("repository_id"), idempotency_key=f"recovery:{plan_id}"), p)
    except Exception:
        with transaction() as conn:
            recovery.release(conn, plan_id)
        raise
    with transaction() as conn:
        recovery.announce(conn, plan_id, m["id"])
        return {"plan": recovery.plan(conn, plan_id), "mission": m}


@router.post("/{plan_id}/decline")
def decline(plan_id: str, p: Principal = Depends(owner)) -> dict:
    with transaction() as conn:
        _pending(conn, plan_id, p)
        if not recovery.claim(conn, plan_id, user_id=p.user_id, approve=False):
            raise HTTPException(409, "this plan was already decided")
        recovery.announce(conn, plan_id)
        return {"plan": recovery.plan(conn, plan_id)}
