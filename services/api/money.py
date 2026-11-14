"""Money routes (V6.113–V6.127, services/management/money.py). Reads need a member; changes need an operator (with the
mutation rate limit). Nothing here moves money: it records and adds up what you type in."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from services.api.mytasks import member, operator
from services.core import db
from services.core.auth import Principal
from services.management import money
from services.management.taskplus import PlusError

router = APIRouter(prefix="/api/money")
TZ = Query(default="UTC", max_length=64)


def _err(exc: PlusError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


def _read(fn, *a):
    with db.get_engine().connect() as conn:
        try:
            return fn(conn, *a)
        except PlusError as exc:
            raise _err(exc) from exc


def _write(fn, *a, **k):
    try:
        return fn(*a, **k)
    except PlusError as exc:
        raise _err(exc) from exc


@router.get("/overview")
def overview(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(money.overview, p.organization_id, tz)


# income
class IncomeIn(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)
    source: str = Field(min_length=1, max_length=60)
    day: str | None = Field(default=None, max_length=10)
    hours: float | None = Field(default=None, gt=0, le=24)
    note: str | None = Field(default=None, max_length=300)
    tz: str | None = Field(default="UTC", max_length=64)


@router.get("/income")
def income(tz: str = TZ, days: int = Query(default=90, ge=7, le=730), p: Principal = Depends(member)) -> dict:
    return _read(money.income, p.organization_id, tz, days)


@router.post("/income", status_code=201)
def log_income(body: IncomeIn, p: Principal = Depends(operator)) -> dict:
    return _write(money.log_income, p, body.amount, body.source, body.day, body.hours, body.note, body.tz)


@router.delete("/income/{iid}")
def remove_income(iid: str, p: Principal = Depends(operator)) -> dict:
    _write(money.remove_income, p, iid)
    return {"ok": True}


# paydays and the planner
class ScheduleIn(BaseModel):
    name: str | None = Field(default=None, max_length=60)
    cadence: str = Field(pattern="^(weekly|biweekly|semimonthly|monthly)$")
    anchor_day: str = Field(max_length=10)
    amount: float | None = Field(default=None, ge=0, le=1_000_000)


@router.get("/pay")
def pay(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return {"schedules": _read(money.schedules, p.organization_id, tz)}


@router.post("/pay", status_code=201)
def add_pay(body: ScheduleIn, p: Principal = Depends(operator)) -> dict:
    return _write(money.add_schedule, p, body.name or "", body.cadence, body.anchor_day, body.amount)


@router.delete("/pay/{sid}")
def remove_pay(sid: str, p: Principal = Depends(operator)) -> dict:
    _write(money.remove_schedule, p, sid)
    return {"ok": True}


@router.get("/planner")
def planner(tz: str = TZ, periods: int = Query(default=4, ge=1, le=8), p: Principal = Depends(member)) -> dict:
    return _read(money.planner, p.organization_id, tz, periods)


# savings
class SavingsIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    target: float = Field(gt=0, le=10_000_000)
    deadline: str | None = Field(default=None, max_length=10)
    monthly_plan: float | None = Field(default=None, ge=0, le=1_000_000)
    tz: str | None = Field(default="UTC", max_length=64)


class DepositIn(BaseModel):
    amount: float = Field(ge=-1_000_000, le=1_000_000)
    day: str | None = Field(default=None, max_length=10)
    tz: str | None = Field(default="UTC", max_length=64)


@router.get("/savings")
def savings(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return {"goals": _read(money.goals, p.organization_id, tz)}


@router.post("/savings", status_code=201)
def add_savings(body: SavingsIn, p: Principal = Depends(operator)) -> dict:
    return _write(money.add_goal, p, body.name, body.target, body.deadline, body.monthly_plan, body.tz)


@router.post("/savings/{gid}/deposits", status_code=201)
def deposit(gid: str, body: DepositIn, p: Principal = Depends(operator)) -> dict:
    _write(money.save_to, p, gid, body.amount, body.day, body.tz)
    return {"goals": _read(money.goals, p.organization_id, body.tz)}


@router.delete("/savings/{gid}")
def remove_savings(gid: str, p: Principal = Depends(operator)) -> dict:
    _write(money.remove_goal, p, gid)
    return {"ok": True}


@router.get("/budget")
def budget(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(money.budget, p.organization_id, tz)


# subscriptions and finding savings
class SubIn(BaseModel):
    subscription: bool | None = None
    reviewed: bool = False


@router.get("/subscriptions")
def subscriptions(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(money.subscriptions, p.organization_id, tz)


@router.post("/bills/{bid}/subscription")
def set_subscription(bid: str, body: SubIn, tz: str = TZ, p: Principal = Depends(operator)) -> dict:
    _write(money.set_subscription, p, bid, body.subscription, body.reviewed)
    return _read(money.subscriptions, p.organization_id, tz)


@router.post("/bills/{bid}/find-savings", status_code=201)
def find_savings(bid: str, tz: str = TZ, p: Principal = Depends(operator)) -> dict:
    """Adds a research task to your list; it isn't started."""
    from services.management.mytasks import TaskError
    try:
        return money.find_savings(p, bid, tz)
    except (PlusError, TaskError) as exc:
        raise HTTPException(exc.status, str(exc)) from exc


# credit
class CardIn(BaseModel):
    name: str | None = Field(default=None, max_length=60)
    limit: float | None = Field(default=None, gt=0, le=1_000_000)
    balance: float | None = Field(default=None, ge=0, le=1_000_000)
    statement_day: int | None = Field(default=None, ge=1, le=31)


@router.get("/credit")
def credit(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(money.credit, p.organization_id, tz)


@router.post("/credit/cards", status_code=201)
def add_card(body: CardIn, p: Principal = Depends(operator)) -> dict:
    return _write(money.save_card, p, None, body.model_dump(exclude_unset=True))


@router.patch("/credit/cards/{cid}")
def edit_card(cid: str, body: CardIn, p: Principal = Depends(operator)) -> dict:
    return _write(money.save_card, p, cid, body.model_dump(exclude_unset=True))


@router.delete("/credit/cards/{cid}")
def remove_card(cid: str, p: Principal = Depends(operator)) -> dict:
    _write(money.remove_card, p, cid)
    return {"ok": True}


@router.get("/on-time")
def on_time(tz: str = TZ, months: int = Query(default=12, ge=1, le=24), p: Principal = Depends(member)) -> dict:
    return _read(money.on_time, p.organization_id, tz, months)
