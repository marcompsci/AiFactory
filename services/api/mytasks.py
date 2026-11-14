"""The owner's task list (V6.43–V6.49, services/management/mytasks.py). Anyone signed in can read it; adding, changing
and starting tasks need the operator role (with the mutation rate limit), the same as starting a mission."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from services.core import db
from services.core.auth import Principal, authenticate
from services.management import capture, mytasks, taskextra, taskmore, taskplus

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
    repeat: str | None = Field(default=None, max_length=12)
    budget_usd: float | None = Field(default=None, gt=0, le=50)
    repository_id: str | None = Field(default=None, max_length=36)
    list_name: str | None = Field(default=None, max_length=41)
    estimate_minutes: int | None = Field(default=None, ge=5, le=600)
    items: list[str] | None = Field(default=None, max_length=50)
    links: list[str] | None = Field(default=None, max_length=20)
    client_ref: str | None = Field(default=None, pattern="^[A-Za-z0-9-]{8,64}$")  # sending the same add twice makes one task
    tz: str | None = Field(default="UTC", max_length=64)


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=4000)
    kind: str | None = Field(default=None, pattern="^(code|research|write|personal)$")
    priority: str | None = Field(default=None, pattern="^(urgent|normal|low)$")
    due_at: str | None = Field(default=None, max_length=40)
    repeat: str | None = Field(default=None, max_length=12)
    budget_usd: float | None = Field(default=None, gt=0, le=50)
    repository_id: str | None = Field(default=None, max_length=36)
    list_name: str | None = Field(default=None, max_length=41)
    estimate_minutes: int | None = Field(default=None, ge=5, le=600)
    blocked_by: str | None = Field(default=None, max_length=36)
    clear_due: bool = False


class RedoIn(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class DoneIn(BaseModel):
    tz: str | None = Field(default="UTC", max_length=64)


def _err(exc: mytasks.TaskError | taskplus.PlusError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


Errors = (mytasks.TaskError, taskplus.PlusError)


@router.get("/my-tasks")
def list_tasks(include_done: bool = True, q: str | None = Query(default=None, max_length=120),
               p: Principal = Depends(member)) -> dict:
    """Your tasks; with `q`, only those whose title, notes, list, checklist or links mention every word (V6.90)."""
    with db.get_engine().connect() as conn:
        tasks = mytasks.listing(conn, p.organization_id, include_done=include_done)
        if q and q.strip():
            hits = taskmore.search_ids(conn, p.organization_id, q)
            tasks = [t for t in tasks if t["id"] in hits]
        return {"tasks": tasks}


@router.get("/my-tasks/today")
def today(tz: str = Query(default="UTC", max_length=64), p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        return mytasks.today(conn, p.organization_id, tz)


@router.get("/my-tasks/parse")
def parse(text: str = Query(min_length=1, max_length=400), tz: str = Query(default="UTC", max_length=64),
          p: Principal = Depends(member)) -> dict:
    """The quick-capture preview: exactly what adding this text would save. Nothing is stored."""
    rest, urls = taskmore.take_urls(text)
    out = capture.parse(rest, tz)
    out["links"] = urls
    out["repeat_label"] = capture.repeat_label(out["repeat"])
    return out


@router.post("/my-tasks", status_code=201)
def create(body: TaskIn, p: Principal = Depends(operator)) -> dict:
    extra = body.model_dump(exclude={"text", "tz"}, exclude_none=True)
    try:
        if body.text:
            return mytasks.create_from_text(p, body.text, body.tz, extra)
        if not body.title:
            raise mytasks.TaskError("give the task a title or some text")
        return mytasks.create(p, extra)
    except Errors as exc:
        raise _err(exc) from exc


class ItemsIn(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=50)


class ItemPatch(BaseModel):
    text: str | None = Field(default=None, max_length=200)
    done: bool | None = None


class SnoozeIn(BaseModel):
    preset: str | None = Field(default=None, pattern="^(later|tonight|tomorrow|next_week|wake)$")
    until: str | None = Field(default=None, max_length=40)
    tz: str | None = Field(default="UTC", max_length=64)


class TemplateIn(BaseModel):
    name: str | None = Field(default=None, max_length=60)


class UseTemplateIn(BaseModel):
    due_at: str | None = Field(default=None, max_length=40)


class FocusIn(BaseModel):
    minutes: int = Field(ge=1, le=240)
    started_at: str | None = Field(default=None, max_length=40)


class FeedbackIn(BaseModel):
    rating: int = Field(ge=-1, le=1)
    reason: str | None = Field(default=None, max_length=300)


class BulkIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=100)
    action: str = Field(pattern="^(done|drop|next_week|due)$")
    due_at: str | None = Field(default=None, max_length=40)
    tz: str | None = Field(default="UTC", max_length=64)


# ---------------------------------------------------------------- V6.72 templates, V6.77 plan, V6.80 results, V6.84 review

@router.get("/my-tasks/templates")
def list_templates(p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        return {"templates": taskplus.templates(conn, p.organization_id)}


@router.post("/my-tasks/templates/{tmpl}/use", status_code=201)
def use_template(tmpl: str, body: UseTemplateIn | None = None, p: Principal = Depends(operator)) -> dict:
    try:
        return taskplus.use_template(p, tmpl, body.due_at if body else None)
    except Errors as exc:
        raise _err(exc) from exc


@router.delete("/my-tasks/templates/{tmpl}")
def delete_template(tmpl: str, p: Principal = Depends(operator)) -> dict:
    try:
        taskplus.delete_template(p, tmpl)
    except Errors as exc:
        raise _err(exc) from exc
    return {"ok": True}


@router.get("/my-tasks/plan")
def plan(tz: str = Query(default="UTC", max_length=64), start: str = Query(default="09:00", max_length=5),
         end: str = Query(default="18:00", max_length=5), busy: list[str] = Query(default=[], max_length=60),
         p: Principal = Depends(member)) -> dict:
    """`busy`: "start,end" times from your phone's calendar (V6.103); titles are never sent."""
    with db.get_engine().connect() as conn:
        try:
            return taskplus.plan_day(conn, p.organization_id, tz, start, end, busy=taskextra.parse_busy(busy))
        except Errors as exc:
            raise _err(exc) from exc


@router.get("/my-tasks/results")
def results(q: str | None = Query(default=None, max_length=120), kind: str | None = Query(default=None, pattern="^(research|write|personal)$"),
            limit: int = Query(default=50, ge=1, le=200), p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        return {"results": taskplus.results(conn, p.organization_id, q, kind, limit)}


@router.get("/my-tasks/review")
def review(tz: str = Query(default="UTC", max_length=64), p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        return taskplus.review(conn, p.organization_id, tz)


@router.post("/my-tasks/bulk")
def bulk(body: BulkIn, p: Principal = Depends(operator)) -> dict:
    try:
        return taskplus.bulk(p, body.ids, body.action, body.tz, body.due_at)
    except Errors as exc:
        raise _err(exc) from exc


@router.get("/insights/tasks")
def task_insights(tz: str = Query(default="UTC", max_length=64), days: int = Query(default=14, ge=7, le=60),
                  p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        return taskplus.insights(conn, p.organization_id, tz, days)


@router.get("/insights/agent-quality")
def agent_quality(p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        return {"agents": taskplus.agent_quality(conn, p.organization_id)}


@router.get("/my-tasks/habits")
def habit_list(tz: str = Query(default="UTC", max_length=64), p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        return {"habits": taskmore.habits(conn, p.organization_id, tz)}


@router.get("/my-tasks/digest")
def day_digest(tz: str = Query(default="UTC", max_length=64), day: str = Query(default="today", pattern="^(today|tomorrow|[2-6])$"),
               p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        return taskmore.digest(conn, p.organization_id, tz, day)


@router.get("/my-tasks/month")
def month_view(year: int = Query(ge=2000, le=2100), month: int = Query(ge=1, le=12), tz: str = Query(default="UTC", max_length=64),
               p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        return taskextra.month(conn, p.organization_id, year, month, tz)


@router.get("/my-tasks/fit")
def fit(minutes: int = Query(ge=5, le=480), tz: str = Query(default="UTC", max_length=64), p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        return taskextra.fit(conn, p.organization_id, minutes, tz)


@router.get("/my-tasks/shutdown")
def shutdown(tz: str = Query(default="UTC", max_length=64), p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        return taskextra.shutdown(conn, p.organization_id, tz)


class CloseDayIn(BaseModel):
    tz: str | None = Field(default="UTC", max_length=64)
    move: bool = False
    note: str | None = Field(default=None, max_length=1000)


@router.post("/my-tasks/shutdown")
def close_day(body: CloseDayIn, p: Principal = Depends(operator)) -> dict:
    return taskextra.close_day(p, body.tz, body.move, body.note)


@router.get("/my-tasks/archive")
def archive(q: str | None = Query(default=None, max_length=120), limit: int = Query(default=100, ge=1, le=500),
            p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        return {"tasks": taskextra.archive(conn, p.organization_id, q, limit)}


@router.get("/my-tasks/export")
def export(format: str = Query(default="json", pattern="^(json|csv)$"), p: Principal = Depends(member)) -> Response:
    with db.get_engine().connect() as conn:
        body, ctype = taskextra.export(conn, p.organization_id, format)
    return Response(body, media_type=ctype, headers={"Content-Disposition": f'attachment; filename="my-tasks.{format}"'})


class DumpIn(BaseModel):
    text: str = Field(min_length=1, max_length=40_000)
    format: str = Field(default="lines", pattern="^(lines|csv)$")
    tz: str | None = Field(default="UTC", max_length=64)
    dry_run: bool = True


@router.post("/my-tasks/dump")
def dump(body: DumpIn, p: Principal = Depends(operator)) -> dict:
    """V6.98 brain dump / V6.109 import: with dry_run (the default) only shows what would be added."""
    try:
        if body.dry_run:
            return {"preview": taskextra.dump_preview(body.text, body.tz, body.format)}
        return taskextra.dump_add(p, body.text, body.tz, body.format)
    except Errors as exc:
        raise _err(exc) from exc


@router.get("/my-tasks/{tid}")
def detail(tid: str, tz: str = Query(default="UTC", max_length=64), p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        try:
            return mytasks.get(conn, p.organization_id, tid, tz)
        except Errors as exc:
            raise _err(exc) from exc


@router.patch("/my-tasks/{tid}")
def edit(tid: str, body: TaskPatch, p: Principal = Depends(operator)) -> dict:
    fields = body.model_dump(exclude={"clear_due"}, exclude_unset=True)
    if body.clear_due:
        fields["due_at"] = None
    try:
        return mytasks.edit(p, tid, fields)
    except Errors as exc:
        raise _err(exc) from exc


@router.post("/my-tasks/{tid}/do")
def do_it(tid: str, p: Principal = Depends(operator)) -> dict:
    try:
        return mytasks.do_it(p, tid)
    except Errors as exc:
        raise _err(exc) from exc


@router.post("/my-tasks/{tid}/redo")
def redo(tid: str, body: RedoIn, p: Principal = Depends(operator)) -> dict:
    try:
        return mytasks.do_it(p, tid, body.note or "")
    except Errors as exc:
        raise _err(exc) from exc


@router.post("/my-tasks/{tid}/done")
def done(tid: str, body: DoneIn | None = None, p: Principal = Depends(operator)) -> dict:
    try:
        return mytasks.complete(p, tid, (body.tz if body else None) or "UTC")
    except Errors as exc:
        raise _err(exc) from exc


@router.post("/my-tasks/{tid}/reopen")
def reopen(tid: str, p: Principal = Depends(operator)) -> dict:
    try:
        return mytasks.set_status(p, tid, "OPEN")
    except Errors as exc:
        raise _err(exc) from exc


@router.post("/my-tasks/{tid}/drop")
def drop(tid: str, p: Principal = Depends(operator)) -> dict:
    try:
        return mytasks.set_status(p, tid, "DROPPED")
    except Errors as exc:
        raise _err(exc) from exc


@router.delete("/my-tasks/{tid}")
def remove(tid: str, p: Principal = Depends(operator)) -> dict:
    try:
        mytasks.remove(p, tid)
    except Errors as exc:
        raise _err(exc) from exc
    return {"ok": True}


# ---------------------------------------------------------------- per task: checklist, snooze, template, focus, estimate, feedback

@router.post("/my-tasks/{tid}/items", status_code=201)
def add_items(tid: str, body: ItemsIn, p: Principal = Depends(operator)) -> dict:
    try:
        return {"items": taskplus.add_items(p, tid, body.texts)}
    except Errors as exc:
        raise _err(exc) from exc


@router.patch("/my-tasks/{tid}/items/{iid}")
def edit_item(tid: str, iid: str, body: ItemPatch, p: Principal = Depends(operator)) -> dict:
    try:
        return {"items": taskplus.edit_item(p, tid, iid, body.text, body.done)}
    except Errors as exc:
        raise _err(exc) from exc


@router.delete("/my-tasks/{tid}/items/{iid}")
def remove_item(tid: str, iid: str, p: Principal = Depends(operator)) -> dict:
    try:
        return {"items": taskplus.remove_item(p, tid, iid)}
    except Errors as exc:
        raise _err(exc) from exc


@router.post("/my-tasks/{tid}/snooze")
def snooze(tid: str, body: SnoozeIn, p: Principal = Depends(operator)) -> dict:
    try:
        taskplus.snooze(p, tid, body.preset, body.until, body.tz)
        with db.get_engine().connect() as conn:
            return mytasks.get(conn, p.organization_id, tid)
    except Errors as exc:
        raise _err(exc) from exc


@router.post("/my-tasks/{tid}/template", status_code=201)
def save_template(tid: str, body: TemplateIn | None = None, p: Principal = Depends(operator)) -> dict:
    try:
        return taskplus.save_template(p, tid, body.name if body else None)
    except Errors as exc:
        raise _err(exc) from exc


@router.post("/my-tasks/{tid}/focus", status_code=201)
def focus(tid: str, body: FocusIn, p: Principal = Depends(operator)) -> dict:
    try:
        return taskplus.log_focus(p, tid, body.minutes, body.started_at)
    except Errors as exc:
        raise _err(exc) from exc


@router.get("/my-tasks/{tid}/estimate")
def estimate(tid: str, p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        try:
            return taskplus.estimate(conn, p.organization_id, tid)
        except Errors as exc:
            raise _err(exc) from exc


@router.post("/my-tasks/{tid}/feedback")
def feedback(tid: str, body: FeedbackIn, p: Principal = Depends(operator)) -> dict:
    try:
        return taskplus.give_feedback(p, tid, body.rating, body.reason)
    except Errors as exc:
        raise _err(exc) from exc


# ---------------------------------------------------------------- V6.88–V6.97

class LinkIn(BaseModel):
    url: str = Field(min_length=10, max_length=2048)
    title: str | None = Field(default=None, max_length=120)


@router.post("/my-tasks/{tid}/undo-done")
def undo_done(tid: str, p: Principal = Depends(operator)) -> dict:
    try:
        return taskmore.undo_done(p, tid)
    except Errors as exc:
        raise _err(exc) from exc


@router.get("/my-tasks/{tid}/history")
def task_history(tid: str, p: Principal = Depends(member)) -> dict:
    try:
        with db.get_engine().connect() as conn:
            return {"history": taskmore.history(conn, p.organization_id, tid)}
    except Errors as exc:
        raise _err(exc) from exc


@router.post("/my-tasks/{tid}/links", status_code=201)
def add_link(tid: str, body: LinkIn, p: Principal = Depends(operator)) -> dict:
    try:
        return {"links": taskmore.add_link(p, tid, body.url, body.title)}
    except Errors as exc:
        raise _err(exc) from exc


@router.delete("/my-tasks/{tid}/links/{lid}")
def remove_link(tid: str, lid: str, p: Principal = Depends(operator)) -> dict:
    try:
        return {"links": taskmore.remove_link(p, tid, lid)}
    except Errors as exc:
        raise _err(exc) from exc


# ---------------------------------------------------------------- V6.98–V6.112

@router.post("/my-tasks/{tid}/items/{iid}/promote", status_code=201)
def promote(tid: str, iid: str, p: Principal = Depends(operator)) -> dict:
    try:
        return taskextra.promote_item(p, tid, iid)
    except Errors as exc:
        raise _err(exc) from exc


class GoalLinkIn(BaseModel):
    goal_id: str | None = Field(default=None, max_length=36)


@router.post("/my-tasks/{tid}/goal")
def link_goal(tid: str, body: GoalLinkIn, p: Principal = Depends(operator)) -> dict:
    try:
        taskextra.link_goal(p, tid, body.goal_id)
        with db.get_engine().connect() as conn:
            return mytasks.get(conn, p.organization_id, tid)
    except Errors as exc:
        raise _err(exc) from exc


class WaitingIn(BaseModel):
    person: str | None = Field(default=None, max_length=60)
    follow_up_at: str | None = Field(default=None, max_length=40)


@router.post("/my-tasks/{tid}/waiting")
def waiting(tid: str, body: WaitingIn, p: Principal = Depends(operator)) -> dict:
    try:
        taskextra.set_waiting(p, tid, body.person, body.follow_up_at)
        with db.get_engine().connect() as conn:
            return mytasks.get(conn, p.organization_id, tid)
    except Errors as exc:
        raise _err(exc) from exc


# bills you track (V6.100–V6.101): nothing here pays anything

class BillIn(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    amount: float | None = Field(default=None, ge=0, le=1_000_000)
    cadence: str | None = Field(default=None, pattern="^(monthly|yearly)$")
    due_day: int | None = Field(default=None, ge=1, le=31)
    due_month: int | None = Field(default=None, ge=1, le=12)
    autopay: bool | None = None
    link_url: str | None = Field(default=None, max_length=2048)
    notes: str | None = Field(default=None, max_length=1000)
    remind_days: int | None = Field(default=None, ge=0, le=14)
    active: bool | None = None
    tz: str | None = Field(default="UTC", max_length=64)


@router.get("/bills")
def list_bills(tz: str = Query(default="UTC", max_length=64), all: bool = False, p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        return {"bills": taskextra.bills(conn, p.organization_id, tz, include_inactive=all)}


@router.get("/bills/summary")
def bill_summary(tz: str = Query(default="UTC", max_length=64), p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        return taskextra.bill_summary(conn, p.organization_id, tz)


@router.post("/bills", status_code=201)
def add_bill(body: BillIn, p: Principal = Depends(operator)) -> dict:
    try:
        return taskextra.add_bill(p, body.model_dump(exclude={"tz"}, exclude_unset=True), body.tz)
    except Errors as exc:
        raise _err(exc) from exc


@router.patch("/bills/{bid}")
def edit_bill(bid: str, body: BillIn, p: Principal = Depends(operator)) -> dict:
    try:
        return taskextra.edit_bill(p, bid, body.model_dump(exclude={"tz"}, exclude_unset=True), body.tz)
    except Errors as exc:
        raise _err(exc) from exc


@router.delete("/bills/{bid}")
def remove_bill(bid: str, p: Principal = Depends(operator)) -> dict:
    try:
        taskextra.remove_bill(p, bid)
    except Errors as exc:
        raise _err(exc) from exc
    return {"ok": True}


class PaidIn(BaseModel):
    period: str | None = Field(default=None, max_length=7)
    amount: float | None = Field(default=None, ge=0, le=1_000_000)
    tz: str | None = Field(default="UTC", max_length=64)


@router.post("/bills/{bid}/paid")
def bill_paid(bid: str, body: PaidIn, p: Principal = Depends(operator)) -> dict:
    """You paid it somewhere else; this only records that."""
    try:
        return taskextra.mark_paid(p, bid, body.period, body.amount, body.tz)
    except Errors as exc:
        raise _err(exc) from exc


@router.delete("/bills/{bid}/paid/{period}")
def bill_unpaid(bid: str, period: str, tz: str = Query(default="UTC", max_length=64), p: Principal = Depends(operator)) -> dict:
    try:
        return taskextra.unmark_paid(p, bid, period, tz)
    except Errors as exc:
        raise _err(exc) from exc


# weekly goals (V6.106)

class GoalIn(BaseModel):
    text: str | None = Field(default=None, max_length=120)
    done: bool | None = None
    tz: str | None = Field(default="UTC", max_length=64)


@router.get("/goals")
def list_goals(tz: str = Query(default="UTC", max_length=64), p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        return taskextra.goals(conn, p.organization_id, tz)


@router.post("/goals", status_code=201)
def add_goal(body: GoalIn, p: Principal = Depends(operator)) -> dict:
    try:
        return taskextra.add_goal(p, body.text or "", body.tz)
    except Errors as exc:
        raise _err(exc) from exc


@router.patch("/goals/{gid}")
def edit_goal(gid: str, body: GoalIn, p: Principal = Depends(operator)) -> dict:
    try:
        return taskextra.edit_goal(p, gid, body.model_dump(exclude={"tz"}, exclude_unset=True), body.tz)
    except Errors as exc:
        raise _err(exc) from exc


@router.delete("/goals/{gid}")
def remove_goal(gid: str, tz: str = Query(default="UTC", max_length=64), p: Principal = Depends(operator)) -> dict:
    try:
        return taskextra.remove_goal(p, gid, tz)
    except Errors as exc:
        raise _err(exc) from exc


# list colors and icons (V6.110)

class StyleIn(BaseModel):
    color: str | None = Field(default=None, max_length=7)
    icon: str | None = Field(default=None, max_length=40)


@router.get("/lists/styles")
def styles(p: Principal = Depends(member)) -> dict:
    with db.get_engine().connect() as conn:
        return {"styles": taskextra.list_styles(conn, p.organization_id), "icons": list(taskextra.ICONS)}


@router.put("/lists/{name}/style")
def set_style(name: str, body: StyleIn, p: Principal = Depends(operator)) -> dict:
    try:
        return {"styles": taskextra.set_list_style(p, name, body.color, body.icon)}
    except Errors as exc:
        raise _err(exc) from exc
