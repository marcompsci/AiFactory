"""The money game. Owners and admins see the money; other members see ranks, levels and activity only.
Scores come exclusively from the scheduled scorer (services/game/scoring.py); there is no endpoint that writes one."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from services.core import db
from services.core.auth import Principal, authenticate, mutation_limiter
from services.core.events import transaction
from services.finance import audit
from services.finance.permissions import FINANCE_READ_ROLES, require_owner
from services.game import scoring

router = APIRouter(prefix="/api/game")


def member(request: Request) -> Principal:
    return authenticate(request)


def owner(request: Request) -> Principal:
    p = authenticate(request)
    require_owner(p)
    mutation_limiter.check(p.user_id)
    return p


@router.get("")
def game(p: Principal = Depends(member), season: str | None = None):
    with transaction() as conn:   # may create the current season row
        out = scoring.leaderboard(conn, p.organization_id, season)
        out["links"] = [dict(r._mapping) for r in conn.execute(select(db.revenue_links).where(
            db.revenue_links.c.organization_id == p.organization_id, db.revenue_links.c.active == 1))]
    if p.role not in FINANCE_READ_ROLES:  # money stays with owners and admins
        for r in out["leaderboard"]:
            for k in ("verified_minor", "simulated_minor", "lifetime_verified_minor", "by_kind"):
                r.pop(k, None)
        out["plays"] = [{k: v for k, v in x.items() if k not in ("amount_minor", "evidence")} for x in out["plays"]]
        out.pop("totals", None)
        out["links"] = []
        out["amounts_hidden"] = True
    return out


class LinkIn(BaseModel):
    merchant: str = Field(min_length=1, max_length=120)
    opportunity_id: str = Field(min_length=36, max_length=36)


@router.post("/revenue-links", status_code=201)
def create_link(body: LinkIn, p: Principal = Depends(owner)):
    """The owner states that revenue from this payer comes from a product the agents built. Only revenue posted after
    this moment is attributed, so a link can never claim past income."""
    with transaction() as conn:
        opp = conn.execute(select(db.opportunities).where(db.opportunities.c.id == body.opportunity_id,
                                                          db.opportunities.c.organization_id == p.organization_id)).first()
        if opp is None:
            raise HTTPException(status_code=404, detail="unknown product / opportunity")
        lid = db.new_id()
        conn.execute(db.revenue_links.insert().values(id=lid, organization_id=p.organization_id, merchant=body.merchant.strip(),
                                                      opportunity_id=opp.id, created_by=p.user_id))
        audit.record(conn, org_id=p.organization_id, actor_type="owner", actor_id=p.user_id, action="game.revenue_link_created",
                     subject_type="revenue_link", subject_id=lid, detail={"merchant": body.merchant.strip(), "opportunity_id": opp.id})
    return {"id": lid, "merchant": body.merchant.strip(), "opportunity_id": opp.id, "attributes_from": "now"}


@router.post("/revenue-links/{link_id}/deactivate")
def deactivate_link(link_id: str, p: Principal = Depends(owner)):
    with transaction() as conn:
        n = conn.execute(update(db.revenue_links).where(db.revenue_links.c.id == link_id,
                                                        db.revenue_links.c.organization_id == p.organization_id).values(active=0)).rowcount
        if not n:
            raise HTTPException(status_code=404, detail="unknown link")
        audit.record(conn, org_id=p.organization_id, actor_type="owner", actor_id=p.user_id, action="game.revenue_link_deactivated",
                     subject_type="revenue_link", subject_id=link_id)
    return {"id": link_id, "active": False}
