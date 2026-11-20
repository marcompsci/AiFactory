"""Money routes, round 3 (V6.158–V6.187, services/management/money3.py). Reads need a member; changes need an
operator (with the mutation rate limit). Nothing here moves money."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from services.api.money import TZ, _read, _write
from services.api.mytasks import member, operator
from services.core.auth import Principal
from services.management import money3 as m

router = APIRouter(prefix="/api/money")


def ok() -> dict:
    return {"ok": True}


class Tz(BaseModel):
    tz: str | None = Field(default="UTC", max_length=64)


# V6.158 paste a bill (reads the text you send and saves nothing)
class PasteIn(Tz):
    text: str = Field(min_length=1, max_length=5000)


@router.post("/bills/parse")
def parse_bill(body: PasteIn, p: Principal = Depends(operator)) -> dict:
    return _write(m.parse_bill, body.text, body.tz)


# V6.159 due-date moves, V6.162 history, V6.161 confirmation numbers
@router.get("/due-date-moves")
def moves(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.due_date_moves, p.organization_id, tz)


@router.get("/bills/{bid}/history")
def history(bid: str, tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.bill_history, p.organization_id, bid, tz)


class NoteIn(BaseModel):
    period: str = Field(min_length=4, max_length=7)
    confirmation: str | None = Field(default=None, max_length=60)
    method: str | None = Field(default=None, max_length=40)


@router.put("/bills/{bid}/payment-note")
def payment_note(bid: str, body: NoteIn, p: Principal = Depends(operator)) -> dict:
    _write(m.set_payment_note, p, bid, body.period, body.confirmation, body.method)
    return ok()


# V6.163/V6.164 forecast
@router.get("/forecast")
def forecast(tz: str = TZ, days: int = Query(default=30, ge=7, le=60), buffer: float = Query(default=100, ge=0, le=100_000),
             p: Principal = Depends(member)) -> dict:
    return _read(m.forecast, p.organization_id, tz, days, buffer)


# V6.165–V6.169 credit watch, habits, history; V6.170 card bills
@router.get("/credit-watch")
def credit_watch(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.credit_watch, p.organization_id, tz)


class OnIn(BaseModel):
    on: bool = True


@router.put("/credit-watch/{kind}/{bureau}")
def mark_bureau(kind: str, bureau: str, body: OnIn, p: Principal = Depends(operator)) -> dict:
    _write(m.mark_bureau, p, kind[:10], bureau[:12], body.on)
    return ok()


class DisputeIn(Tz):
    bureau: Literal["equifax", "experian", "transunion", "other"]
    item: str = Field(min_length=1, max_length=120)
    sent_on: str | None = Field(default=None, max_length=10)
    note: str | None = Field(default=None, max_length=300)


class DisputeUpdate(Tz):
    status: Literal["open", "fixed", "denied"]
    note: str | None = Field(default=None, max_length=300)


@router.post("/disputes", status_code=201)
def add_dispute(body: DisputeIn, p: Principal = Depends(operator)) -> dict:
    return _write(m.add_dispute, p, body.bureau, body.item, body.sent_on, body.note, body.tz)


@router.patch("/disputes/{did}")
def update_dispute(did: str, body: DisputeUpdate, p: Principal = Depends(operator)) -> dict:
    _write(m.update_dispute, p, did, body.status, body.note, body.tz)
    return ok()


@router.delete("/disputes/{did}")
def remove_dispute(did: str, p: Principal = Depends(operator)) -> dict:
    _write(m.remove_dispute, p, did)
    return ok()


@router.get("/credit-habits")
def habits(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.habits, p.organization_id, tz)


@router.get("/utilization-history")
def utilization_history(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.utilization_history, p.organization_id, tz)


class CardBillIn(Tz):
    due_day: int = Field(ge=1, le=31)


@router.put("/credit/cards/{cid}/bill")
def card_bill(cid: str, body: CardBillIn, p: Principal = Depends(operator)) -> dict:
    return _write(m.card_bill, p, cid, body.due_day, body.tz)


@router.get("/card-bills")
def card_bills(p: Principal = Depends(member)) -> dict:
    return {"links": _read(m.card_bill_links, p.organization_id)}


# V6.171 income goal, V6.172 best days
class GoalIn(BaseModel):
    monthly: float | None = Field(default=None, ge=0, le=1_000_000)


@router.get("/income-goal")
def income_goal(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.income_goal, p.organization_id, tz)


@router.put("/income-goal")
def set_income_goal(body: GoalIn, p: Principal = Depends(operator)) -> dict:
    _write(m.set_income_goal, p, body.monthly)
    return ok()


@router.get("/best-days")
def best_days(tz: str = TZ, source: str | None = Query(default=None, max_length=60), p: Principal = Depends(member)) -> dict:
    return _read(m.best_days, p.organization_id, tz, 90, source)


# V6.173 wins, V6.174 selling, V6.175 owed
class WinIn(Tz):
    title: str = Field(min_length=1, max_length=80)
    amount: float = Field(gt=0, le=1_000_000)
    monthly: bool = False
    day: str | None = Field(default=None, max_length=10)


@router.get("/wins")
def wins(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.wins, p.organization_id, tz)


@router.post("/wins", status_code=201)
def add_win(body: WinIn, p: Principal = Depends(operator)) -> dict:
    return _write(m.add_win, p, body.title, body.amount, body.monthly, body.day, body.tz)


@router.delete("/wins/{wid}")
def remove_win(wid: str, p: Principal = Depends(operator)) -> dict:
    _write(m.remove_win, p, wid)
    return ok()


class ItemIn(Tz):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    asking: float | None = Field(default=None, ge=0, le=1_000_000)
    sold: float | None = Field(default=None, ge=0, le=1_000_000)
    where_listed: str | None = Field(default=None, max_length=60)


@router.get("/selling")
def selling(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.selling, p.organization_id, tz)


@router.post("/selling", status_code=201)
def add_item(body: ItemIn, p: Principal = Depends(operator)) -> dict:
    return _write(m.save_item, p, None, body.model_dump(exclude_unset=True, exclude={"tz"}), body.tz)


@router.patch("/selling/{iid}")
def edit_item(iid: str, body: ItemIn, p: Principal = Depends(operator)) -> dict:
    return _write(m.save_item, p, iid, body.model_dump(exclude_unset=True, exclude={"tz"}), body.tz)


@router.delete("/selling/{iid}")
def remove_item(iid: str, p: Principal = Depends(operator)) -> dict:
    _write(m.remove_item, p, iid)
    return ok()


class OwedIn(BaseModel):
    who: str = Field(min_length=1, max_length=40)
    amount: float = Field(gt=0, le=1_000_000)
    why: str | None = Field(default=None, max_length=120)
    expected_on: str | None = Field(default=None, max_length=10)


class ReceivedIn(Tz):
    received: bool = True


@router.get("/owed")
def owed(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.owed, p.organization_id, tz)


@router.post("/owed", status_code=201)
def add_owed(body: OwedIn, p: Principal = Depends(operator)) -> dict:
    return _write(m.add_owed, p, body.who, body.amount, body.why, body.expected_on)


@router.put("/owed/{oid}/received")
def mark_owed(oid: str, body: ReceivedIn, p: Principal = Depends(operator)) -> dict:
    _write(m.mark_owed, p, oid, body.received, body.tz)
    return ok()


@router.delete("/owed/{oid}")
def remove_owed(oid: str, p: Principal = Depends(operator)) -> dict:
    _write(m.remove_owed, p, oid)
    return ok()


# V6.176 round-ups, V6.177 no-spend, V6.178 set-asides
@router.get("/round-ups")
def round_ups(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.round_ups, p.organization_id, tz)


class NoSpendIn(Tz):
    day: str | None = Field(default=None, max_length=10)
    on: bool = True


@router.get("/no-spend")
def no_spend(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.no_spend, p.organization_id, tz)


@router.put("/no-spend")
def toggle_no_spend(body: NoSpendIn, p: Principal = Depends(operator)) -> dict:
    _write(m.toggle_no_spend, p, body.day, body.on, body.tz)
    return ok()


@router.get("/set-asides")
def set_asides(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.sinking_funds, p.organization_id, tz)


@router.post("/set-asides/{bid}/goal", status_code=201)
def fund_goal(bid: str, body: Tz, p: Principal = Depends(operator)) -> dict:
    return _write(m.fund_goal, p, bid, body.tz)


# V6.179–V6.185 assistant
@router.get("/todos")
def todos(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.todos, p.organization_id, tz)


@router.get("/weekly")
def weekly(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.weekly, p.organization_id, tz)


@router.get("/afford")
def afford(amount: float = Query(gt=0, le=1_000_000), tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.afford, p.organization_id, amount, tz)


@router.get("/projections")
def projections(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.projections, p.organization_id, tz)


@router.get("/export")
def export(p: Principal = Depends(member)) -> dict:
    return _read(m.export, p.organization_id)


@router.get("/setup")
def setup(tz: str = TZ, p: Principal = Depends(member)) -> dict:
    return _read(m.setup, p.organization_id, tz)
