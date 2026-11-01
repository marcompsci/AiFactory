"""The owner's task list (V6.43–V6.49, services/management/mytasks.py). Anyone signed in can read it; adding, changing
and starting tasks need the operator role (with the mutation rate limit), the same as starting a mission."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from services.core import db
from services.core.auth import Principal, authenticate
from services.management import capture, mytasks

router = APIRouter(prefix="/api")


def member(request: Request) -> Principal:
    return authenticate(request)


def operator(request: Request) -> Principal:
    from services.api.finance import operator as op  # the operator role plus the mutation rate limit
    return op(request)


class TaskIn(BaseModel):
    text: str | None = Field(default=None, max_length=400)   # quick capture: parsed like the preview
    title: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=4000)
    kind: str | None = Field(default=None, pattern="^(code|research|write|personal)$")
    priority: str | None = Field(default=None, pattern="^(urgent|normal|low)$")
    due_at: str | None = Field(default=None, max_length=40)
    repeat: str | None = Field(default=None, pattern="^(none|daily|weekdays|weekly)$")
    budget_usd: float | None = Field(default=None, gt=0, le=50)
    repository_id: str | None = Field(default=None, max_length=36)
    tz: str | None = Field(default="UTC", max_length=64)


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=4000)
    kind: str | None = Field(default=None, pattern="^(code|research|write|personal)$")
    priority: str | None = Field(default=None, pattern="^(urgent|normal|low)$")
    due_at: str | None = Field(default=None, max_length=40)
    repeat: str | None = Field(default=None, pattern="^(none|daily|weekdays|weekly)$")
    budget_usd: float | None = Field(default=None, gt=0, le=50)
    repository_id: str | None = Field(default=None, max_length=36)
    clear_due: bool = False


class RedoIn(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class DoneIn(BaseModel):
    tz: str | None = Field(default="UTC", max_length=64)


def _err(exc: mytasks.TaskError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


@router.get("/my-tasks")
def list_tasks(include_done: bool = True, p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        return {"tasks": mytasks.listing(conn, p.organization_id, include_done=include_done)}


@router.get("/my-tasks/today")
def today(tz: str = Query(default="UTC", max_length=64), p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        return mytasks.today(conn, p.organization_id, tz)


@router.get("/my-tasks/parse")
def parse(text: str = Query(min_length=1, max_length=400), tz: str = Query(default="UTC", max_length=64),
          p: Principal = Depends(member)) -> dict:
    """The quick-capture preview: exactly what adding this text would save. Nothing is stored."""
    return capture.parse(text, tz)


@router.post("/my-tasks", status_code=201)
def create(body: TaskIn, p: Principal = Depends(operator)) -> dict:
    extra = body.model_dump(exclude={"text", "tz"}, exclude_none=True)
    try:
        if body.text:
            return mytasks.create_from_text(p, body.text, body.tz, extra)
        if not body.title:
            raise mytasks.TaskError("give the task a title or some text")
        return mytasks.create(p, extra)
    except mytasks.TaskError as exc:
        raise _err(exc) from exc


@router.get("/my-tasks/{tid}")
def detail(tid: str, p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        try:
            return mytasks.get(conn, p.organization_id, tid)
        except mytasks.TaskError as exc:
            raise _err(exc) from exc


@router.patch("/my-tasks/{tid}")
def edit(tid: str, body: TaskPatch, p: Principal = Depends(operator)) -> dict:
    fields = body.model_dump(exclude={"clear_due"}, exclude_unset=True)
    if body.clear_due:
        fields["due_at"] = None
    try:
        return mytasks.edit(p, tid, fields)
    except mytasks.TaskError as exc:
        raise _err(exc) from exc


@router.post("/my-tasks/{tid}/do")
def do_it(tid: str, p: Principal = Depends(operator)) -> dict:
    try:
        return mytasks.do_it(p, tid)
    except mytasks.TaskError as exc:
        raise _err(exc) from exc


@router.post("/my-tasks/{tid}/redo")
def redo(tid: str, body: RedoIn, p: Principal = Depends(operator)) -> dict:
    try:
        return mytasks.do_it(p, tid, body.note or "")
    except mytasks.TaskError as exc:
        raise _err(exc) from exc


@router.post("/my-tasks/{tid}/done")
def done(tid: str, body: DoneIn | None = None, p: Principal = Depends(operator)) -> dict:
    try:
        return mytasks.complete(p, tid, (body.tz if body else None) or "UTC")
    except mytasks.TaskError as exc:
        raise _err(exc) from exc


@router.post("/my-tasks/{tid}/reopen")
def reopen(tid: str, p: Principal = Depends(operator)) -> dict:
    try:
        return mytasks.set_status(p, tid, "OPEN")
    except mytasks.TaskError as exc:
        raise _err(exc) from exc


@router.post("/my-tasks/{tid}/drop")
def drop(tid: str, p: Principal = Depends(operator)) -> dict:
    try:
        return mytasks.set_status(p, tid, "DROPPED")
    except mytasks.TaskError as exc:
        raise _err(exc) from exc


@router.delete("/my-tasks/{tid}")
def remove(tid: str, p: Principal = Depends(operator)) -> dict:
    try:
        mytasks.remove(p, tid)
    except mytasks.TaskError as exc:
        raise _err(exc) from exc
    return {"ok": True}
