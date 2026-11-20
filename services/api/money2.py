"""Money routes, round 2 (V6.128–V6.157, services/management/money2.py). Reads need a member; changes need an
operator (with the mutation rate limit). Nothing here moves money: it records and adds up what you type in."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from services.api.money import TZ, _read, _write
from services.api.mytasks import member, operator
from services.core.auth import Principal
from services.management import money2 as m

router = APIRouter(prefix="/api/money")
Month = Query(default=None, max_length=7)


def ok() -> dict:
    return {"ok": True}


# V6.129 spending, V6.130 category limits
class ExpenseIn(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)
    category: str = Field(min_length=1, max_length=40)
    day: str | None = Field(default=None, max_length=10)
    note: str | None = Field(default=None, max_length=300)
    tz: str | None = Field(default="UTC", max_length=64)


class CategoryIn(BaseModel):
    category: str = Field(min_length=1, max_length=40)
    limit: float | None = Field(default=None, ge=0, le=1_000_000)


@router.get("/spending")
def spending(tz: str = TZ, month: str | None = Month, p: Principal = Depends(member)) -> dict:
    return _read(m.spending, p.organization_id, tz, month)


@router.post("/spending", status_code=201)
def log_expense(body: ExpenseIn, p: Principal = Depends(operator)) -> dict:
    return _write(m.log_expense, p, body.amount, body.category, body.day, body.note, body.tz)


@router.delete("/spending/{eid}")
def remove_expense(eid: str, p: Principal = Depends(operator)) -> dict:
    _write(m.remove_expense, p, eid)
    return ok()


@router.put("/spending/limits")
def set_limit(body: CategoryIn, p: Principal = Depends(operator)) -> dict:
    return _write(m.set_category_budget, p, body.category, body.limit)


# V6.131 accounts and balances
class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    kind: Literal["checking", "savings", "cash"] = "checking"
    balance: float | None = Field(default=None, ge=-1_000_000, le=1_000_000)
    tz: str | None = Field(default="UTC", max_length=64)


class BalanceIn(BaseModel):
    balance: float = Field(ge=-1_000_000, le=1_000_000)
    day: str | None = Field(default=None, max_length=10)
    tz: str | None = Field(default="UTC", max_length=64)


@router.get("/accounts")
def accounts(p: Principal = Depends(member)) -> dict:
    return {"accounts": _read(m.accounts, p.organization_id)}


@router.post("/accounts", status_code=201)
def add_account(body: AccountIn, p: Principal = Depends(operator)) -> dict:
    return _write(m.add_account, p, body.name, body.kind, body.balance, body.tz)


@router.post("/accounts/{aid}/balance", status_code=201)
def check_in(aid: str, body: BalanceIn, p: Principal = Depends(operator)) -> dict:
    _write(m.check_in, p, aid, body.balance, body.day, body.tz)
    return ok()


@router.delete("/accounts/{aid}")
def remove_account(aid: str, p: Principal = Depends(operator)) -> dict:
    _write(m.remove_account, p, aid)
    return ok()


# V6.132/V6.133 safe to spend, V6.154 paycheck split
@router.get("/safe-to-spend")
def safe_to_spend(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.safe_to_spend, p.organization_id, tz)


@router.get("/paycheck-split")
def paycheck_split(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.paycheck_split, p.organization_id, tz)


# V6.134–V6.137 debts and payoff
class DebtIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    kind: Literal["card", "loan", "other"] | None = None
    balance: float | None = Field(default=None, ge=0, le=1_000_000)
    apr: float | None = Field(default=None, ge=0, le=100)
    min_payment: float | None = Field(default=None, ge=0, le=1_000_000)
    card_id: str | None = Field(default=None, max_length=36)


@router.get("/debts")
def debts(tz: str = TZ, extra: float = Query(default=0, ge=0, le=1_000_000), p: Principal = Depends(member)) -> dict:
    return {"debts": _read(m.debt_list, p.organization_id), "payoff": _read(m.payoff, p.organization_id, tz, extra)}


@router.post("/debts", status_code=201)
def add_debt(body: DebtIn, p: Principal = Depends(operator)) -> dict:
    return _write(m.save_debt, p, None, body.model_dump(exclude_unset=True))


@router.patch("/debts/{did}")
def edit_debt(did: str, body: DebtIn, p: Principal = Depends(operator)) -> dict:
    return _write(m.save_debt, p, did, body.model_dump(exclude_unset=True))


@router.delete("/debts/{did}")
def remove_debt(did: str, p: Principal = Depends(operator)) -> dict:
    _write(m.remove_debt, p, did)
    return ok()


# V6.138/V6.139 paydown targets
@router.get("/paydown")
def paydown(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.paydown, p.organization_id, tz)


# V6.140 calendar
@router.get("/calendar.ics")
def calendar(tz: str = TZ, p: Principal = Depends(member)) -> Response:
    body = _read(m.calendar_ics, p.organization_id, tz)
    return Response(body, media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="bills-and-paydays.ics"', "Cache-Control": "no-store"})


# V6.141–V6.143 bill checks and extras
class ExtrasIn(BaseModel):
    autopay_account_id: str | None = Field(default=None, max_length=36)
    late_fee: float | None = Field(default=None, ge=0, le=100_000)
    grace_days: int | None = Field(default=None, ge=0, le=60)


@router.get("/bill-checks")
def bill_checks(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.bill_checks, p.organization_id, tz)


@router.put("/bills/{bid}/extras")
def set_extras(bid: str, body: ExtrasIn, p: Principal = Depends(operator)) -> dict:
    _write(m.set_extras, p, bid, body.model_dump(exclude_unset=True))
    return ok()


@router.get("/bills/{bid}/call-script")
def call_script(bid: str, tz: str = TZ, years: int | None = Query(default=None, ge=1, le=60),
                competitor_price: float | None = Query(default=None, gt=0, le=100_000), p: Principal = Depends(member)) -> dict:
    return _read(m.call_script, p.organization_id, bid, tz, years, competitor_price)


# V6.144/V6.145 gigs, settings
class SettingsIn(BaseModel):
    mileage_rate: float | None = Field(default=None, ge=0, le=10)
    tax_pct: float | None = Field(default=None, ge=0, le=60)
    emergency_goal_id: str | None = Field(default=None, max_length=36)
    gig_sources: list[str] | None = Field(default=None, max_length=20)


class GigCostIn(BaseModel):
    source: str = Field(min_length=1, max_length=60)
    amount: float | None = Field(default=None, ge=0, le=1_000_000)
    miles: float | None = Field(default=None, ge=0, le=2000)
    day: str | None = Field(default=None, max_length=10)
    note: str | None = Field(default=None, max_length=300)
    tz: str | None = Field(default="UTC", max_length=64)


@router.get("/settings")
def get_settings(p: Principal = Depends(member)) -> dict:
    return _read(m.settings, p.organization_id)


@router.patch("/settings")
def save_settings(body: SettingsIn, p: Principal = Depends(operator)) -> dict:
    return _write(m.save_settings, p, body.model_dump(exclude_unset=True))


@router.get("/gigs")
def gigs(tz: str = TZ, days: int = Query(default=30, ge=7, le=365), p: Principal = Depends(member)) -> dict:
    return _read(m.gigs, p.organization_id, tz, days)


@router.post("/gigs/costs", status_code=201)
def log_gig_cost(body: GigCostIn, p: Principal = Depends(operator)) -> dict:
    return _write(m.log_gig_cost, p, body.source, body.amount, body.miles, body.day, body.note, body.tz)


@router.delete("/gigs/costs/{cid}")
def remove_gig_cost(cid: str, p: Principal = Depends(operator)) -> dict:
    _write(m.remove_gig_cost, p, cid)
    return ok()


# V6.146 checklist
class CheckIn(BaseModel):
    done: bool = True


@router.get("/checklist")
def checklist(p: Principal = Depends(member)) -> dict:
    return _read(m.checklist, p.organization_id)


@router.put("/checklist/{key}")
def check_item(key: str, body: CheckIn, p: Principal = Depends(operator)) -> dict:
    _write(m.check_item, p, key[:40], body.done)
    return ok()


# V6.148 cashback
class CashbackIn(BaseModel):
    card: str = Field(min_length=1, max_length=60)
    amount: float = Field(gt=0, le=1_000_000)
    day: str | None = Field(default=None, max_length=10)
    tz: str | None = Field(default="UTC", max_length=64)


@router.get("/cashback")
def cashback(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.cashback, p.organization_id, tz)


@router.post("/cashback", status_code=201)
def log_cashback(body: CashbackIn, p: Principal = Depends(operator)) -> dict:
    return _write(m.log_cashback, p, body.card, body.amount, body.day, body.tz)


@router.delete("/cashback/{cid}")
def remove_cashback(cid: str, p: Principal = Depends(operator)) -> dict:
    _write(m.remove_cashback, p, cid)
    return ok()


# V6.149 emergency fund, V6.150 net worth, V6.151 review, V6.152 streak
class AssetIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    value: float = Field(ge=0, le=1_000_000)


@router.get("/emergency")
def emergency(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.emergency, p.organization_id, tz)


@router.get("/net-worth")
def net_worth(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.net_worth, p.organization_id, tz)


@router.post("/net-worth/assets", status_code=201)
def add_asset(body: AssetIn, p: Principal = Depends(operator)) -> dict:
    return _write(m.save_asset, p, None, body.name, body.value)


@router.put("/net-worth/assets/{aid}")
def edit_asset(aid: str, body: AssetIn, p: Principal = Depends(operator)) -> dict:
    return _write(m.save_asset, p, aid, body.name, body.value)


@router.delete("/net-worth/assets/{aid}")
def remove_asset(aid: str, p: Principal = Depends(operator)) -> dict:
    _write(m.remove_asset, p, aid)
    return ok()


@router.post("/net-worth/snapshot", status_code=201)
def snapshot(tz: str = TZ, p: Principal = Depends(operator)) -> dict:
    return _write(m.snapshot, p, tz)


@router.get("/review")
def review(tz: str = TZ, month: str | None = Month, p: Principal = Depends(member)) -> dict:
    return _read(m.review, p.organization_id, tz, month)


@router.get("/streak")
def streak(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.streak, p.organization_id, tz)


# V6.153 split bills
class SplitIn(BaseModel):
    person: str = Field(min_length=1, max_length=40)
    share: float = Field(gt=0, le=1_000_000)


class ReceivedIn(BaseModel):
    period: str = Field(min_length=4, max_length=7)
    received: bool = True


@router.get("/splits")
def splits(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.splits, p.organization_id, tz)


@router.post("/bills/{bid}/splits", status_code=201)
def add_split(bid: str, body: SplitIn, p: Principal = Depends(operator)) -> dict:
    return _write(m.add_split, p, bid, body.person, body.share)


@router.delete("/splits/{sid}")
def remove_split(sid: str, p: Principal = Depends(operator)) -> dict:
    _write(m.remove_split, p, sid)
    return ok()


@router.put("/splits/{sid}/received")
def received(sid: str, body: ReceivedIn, p: Principal = Depends(operator)) -> dict:
    _write(m.mark_received, p, sid, body.period, body.received)
    return ok()
