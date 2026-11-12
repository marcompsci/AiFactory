"""More on each task (V6.68–V6.87): checklists, lists, estimates, snooze, "waiting on", templates, plan my day, focus
sessions, the weekly review, cost-and-time estimates from past runs, feedback on results, the results library and
productivity insights.

Everything here is the owner's own bookkeeping: nothing starts a run, spends money or contacts anyone. Estimates are
worked out from this server's own history and always come back labelled as estimates.
"""
from __future__ import annotations

import re
import statistics
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, insert, or_, select, update
from sqlalchemy.engine import Connection

from services.core import db
from services.core.auth import Principal
from services.core.events import emit, transaction

LIST_RX = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
DEFAULT_MINUTES = {"code": 60, "research": 45, "write": 45, "personal": 30}
MAX_ITEMS = 50


class PlusError(ValueError):
    def __init__(self, msg: str, status: int = 422) -> None:
        super().__init__(msg)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _zone(tz: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def _task(conn: Connection, org: str, tid: str):
    from .mytasks import TaskError, _row
    try:
        return _row(conn, org, tid)
    except TaskError as exc:
        raise PlusError(str(exc), exc.status) from exc


# ---------------------------------------------------------------- meta (lists, estimates, snooze, waiting on)

def clean_list(name: str | None) -> str | None:
    if name in (None, ""):
        return None
    n = str(name).strip().lstrip("#").lower()
    if not LIST_RX.match(n):
        raise PlusError("a list name is letters, numbers, - or _, up to 40 characters")
    return n


def clean_estimate(v) -> int | None:
    if v in (None, ""):
        return None
    m = int(v)
    if not 5 <= m <= 600:
        raise PlusError("an estimate is between 5 minutes and 10 hours")
    return m


def meta_for(conn: Connection, org: str, ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    M = db.task_meta
    out = {}
    for chunk in range(0, len(ids), 500):
        for r in conn.execute(select(M).where(M.c.organization_id == org, M.c.task_id.in_(ids[chunk:chunk + 500]))):
            out[r.task_id] = dict(r._mapping)
    return out


def set_meta(conn: Connection, org: str, tid: str, **fields) -> None:
    M = db.task_meta
    now = _now().isoformat()
    exists = conn.execute(select(M.c.task_id).where(M.c.task_id == tid)).first()
    if exists:
        conn.execute(update(M).where(M.c.task_id == tid).values(updated_at=now, **fields))
    else:
        conn.execute(insert(M).values(task_id=tid, organization_id=org, updated_at=now, **fields))


def check_blocker(conn: Connection, org: str, tid: str, other: str | None) -> str | None:
    """"Waits on" another of your open tasks; never itself, and never in a loop (A waits on B waits on A)."""
    if not other:
        return None
    _task(conn, org, other)
    if other == tid:
        raise PlusError("a task can't wait on itself")
    seen, cur = {tid}, other
    while cur:
        if cur in seen:
            raise PlusError("that would make the tasks wait on each other")
        seen.add(cur)
        cur = conn.execute(select(db.task_meta.c.blocked_by).where(db.task_meta.c.task_id == cur)).scalar()
    return other


def snooze_until(preset: str | None, until: str | None, tz: str | None, now: datetime | None = None) -> str | None:
    """later (3 hours), tonight (8pm), tomorrow (9am), next_week (Monday 9am), or a given time; None to wake it."""
    zone = _zone(tz)
    now = (now or _now()).astimezone(zone)
    if preset == "wake":
        return None
    if until:
        try:
            d = datetime.fromisoformat(until.replace("Z", "+00:00"))
        except ValueError as exc:
            raise PlusError("that isn't a time") from exc
        if d.tzinfo is None:
            d = d.replace(tzinfo=zone)
    elif preset == "later":
        d = now + timedelta(hours=3)
    elif preset == "tonight":
        d = datetime.combine(now.date(), time(20, 0), tzinfo=zone)
        if d <= now:
            d += timedelta(days=1)
    elif preset == "tomorrow":
        d = datetime.combine(now.date() + timedelta(days=1), time(9, 0), tzinfo=zone)
    elif preset == "next_week":
        d = datetime.combine(now.date() + timedelta(days=(7 - now.weekday()) % 7 or 7), time(9, 0), tzinfo=zone)
    else:
        raise PlusError("snooze until later, tonight, tomorrow, next_week, or a time")
    if d <= now:
        raise PlusError("snooze until a time that's still ahead")
    return d.astimezone(timezone.utc).isoformat()


def snooze(p: Principal, tid: str, preset: str | None, until: str | None, tz: str | None) -> None:
    when = snooze_until(preset, until, tz)
    with transaction() as conn:
        r = _task(conn, p.organization_id, tid)
        if r.status != "OPEN":
            raise PlusError("only open tasks can be snoozed", 409)
        set_meta(conn, p.organization_id, tid, snoozed_until=when)
        emit(conn, "my_task.updated", org_id=p.organization_id, payload={"task_id": tid, "fields": ["snoozed_until"]})


# ---------------------------------------------------------------- V6.68 checklists

def items_for(conn: Connection, org: str, ids: list[str]) -> dict[str, list[dict]]:
    if not ids:
        return {}
    I = db.task_items
    out: dict[str, list[dict]] = {}
    for chunk in range(0, len(ids), 500):
        for r in conn.execute(select(I).where(I.c.organization_id == org, I.c.task_id.in_(ids[chunk:chunk + 500]))
                              .order_by(I.c.position, I.c.created_at)):
            out.setdefault(r.task_id, []).append({"id": r.id, "text": r.text, "done": bool(r.done), "from_agents": bool(r.from_agents)})
    return out


def _clean_text(t: str) -> str:
    t = " ".join(str(t or "").split())
    if not 1 <= len(t) <= 200:
        raise PlusError("a checklist step is 1 to 200 characters")
    return t


def _insert_items(conn: Connection, org: str, tid: str, texts: list[str], from_agents: bool = False, start: int = 0) -> None:
    I = db.task_items
    for i, text in enumerate(texts):
        conn.execute(insert(I).values(id=db.new_id(), task_id=tid, organization_id=org, text=_clean_text(text), done=0,
                                      position=start + i, from_agents=int(from_agents), created_at=_now().isoformat()))


def add_items(p: Principal, tid: str, texts: list[str]) -> list[dict]:
    texts = [t for t in texts if str(t or "").strip()]
    if not texts:
        raise PlusError("add at least one step")
    with transaction() as conn:
        _task(conn, p.organization_id, tid)
        have = len(conn.execute(select(db.task_items.c.id).where(db.task_items.c.task_id == tid)).fetchall())
        if have + len(texts) > MAX_ITEMS:
            raise PlusError(f"a checklist holds up to {MAX_ITEMS} steps")
        _insert_items(conn, p.organization_id, tid, texts, start=have)
        emit(conn, "my_task.updated", org_id=p.organization_id, payload={"task_id": tid, "fields": ["checklist"]})
    with db.get_engine().connect() as conn:
        return items_for(conn, p.organization_id, [tid]).get(tid, [])


def _item(conn: Connection, org: str, tid: str, iid: str):
    from .mytasks import _canonical
    if not _canonical(iid):
        raise PlusError("step not found", 404)
    r = conn.execute(select(db.task_items).where(db.task_items.c.id == iid, db.task_items.c.task_id == tid,
                                                 db.task_items.c.organization_id == org)).first()
    if r is None:
        raise PlusError("step not found", 404)
    return r


def edit_item(p: Principal, tid: str, iid: str, text: str | None = None, done: bool | None = None) -> list[dict]:
    with transaction() as conn:
        _task(conn, p.organization_id, tid)
        _item(conn, p.organization_id, tid, iid)
        vals: dict = {}
        if text is not None:
            vals["text"] = _clean_text(text)
        if done is not None:
            vals["done"] = int(done)
            vals["done_at"] = _now().isoformat() if done else None
        if not vals:
            raise PlusError("nothing to change")
        conn.execute(update(db.task_items).where(db.task_items.c.id == iid).values(**vals))
        emit(conn, "my_task.updated", org_id=p.organization_id, payload={"task_id": tid, "fields": ["checklist"]})
    with db.get_engine().connect() as conn:
        return items_for(conn, p.organization_id, [tid]).get(tid, [])


def remove_item(p: Principal, tid: str, iid: str) -> list[dict]:
    with transaction() as conn:
        _task(conn, p.organization_id, tid)
        _item(conn, p.organization_id, tid, iid)
        conn.execute(delete(db.task_items).where(db.task_items.c.id == iid))
    with db.get_engine().connect() as conn:
        return items_for(conn, p.organization_id, [tid]).get(tid, [])


def seed_from_plan(org: str, task_id: str, steps: list[str]) -> None:
    """The agents' plan becomes the task's checklist, if it doesn't have one yet (V6.68). Called by the planner."""
    if not task_id or not steps:
        return
    with transaction() as conn:
        T = db.my_tasks
        if conn.execute(select(T.c.id).where(T.c.id == task_id, T.c.organization_id == org)).first() is None:
            return
        if conn.execute(select(db.task_items.c.id).where(db.task_items.c.task_id == task_id)).first():
            return
        _insert_items(conn, org, task_id, [s[:200] for s in steps[:MAX_ITEMS] if s.strip()], from_agents=True)


def copy_details(conn: Connection, org: str, src: str, dst: str) -> None:
    """A repeat keeps its list, estimate and checklist (unticked)."""
    m = meta_for(conn, org, [src]).get(src)
    if m and (m.get("list_name") or m.get("estimate_minutes")):
        set_meta(conn, org, dst, list_name=m.get("list_name"), estimate_minutes=m.get("estimate_minutes"))
    steps = [i["text"] for i in items_for(conn, org, [src]).get(src, [])]
    if steps:
        _insert_items(conn, org, dst, steps)


def forget(conn: Connection, tid: str) -> None:
    """Remove what hangs off a deleted task (Postgres cascades; SQLite needs telling)."""
    conn.execute(delete(db.task_items).where(db.task_items.c.task_id == tid))
    conn.execute(delete(db.task_meta).where(db.task_meta.c.task_id == tid))
    conn.execute(delete(db.task_feedback).where(db.task_feedback.c.task_id == tid))
    conn.execute(delete(db.focus_sessions).where(db.focus_sessions.c.task_id == tid))
    conn.execute(update(db.task_meta).where(db.task_meta.c.blocked_by == tid).values(blocked_by=None))


# ---------------------------------------------------------------- V6.72 templates

def _template_view(r) -> dict:
    d = dict(r._mapping)
    d["items"] = list(d.get("items") or [])
    return d


def templates(conn: Connection, org: str) -> list[dict]:
    T = db.task_templates
    return [_template_view(r) for r in conn.execute(select(T).where(T.c.organization_id == org).order_by(T.c.name))]


def save_template(p: Principal, tid: str, name: str | None) -> dict:
    with db.get_engine().connect() as conn:
        r = _task(conn, p.organization_id, tid)
        m = meta_for(conn, p.organization_id, [tid]).get(tid) or {}
        steps = [i["text"] for i in items_for(conn, p.organization_id, [tid]).get(tid, [])]
        count = len(conn.execute(select(db.task_templates.c.id).where(db.task_templates.c.organization_id == p.organization_id)).fetchall())
    if count >= 100:
        raise PlusError("you have 100 templates; delete one first", 409)
    nm = " ".join((name or r.title).split())[:60]
    if not nm:
        raise PlusError("give the template a name")
    new = db.new_id()
    with transaction() as conn:
        conn.execute(insert(db.task_templates).values(
            id=new, organization_id=p.organization_id, name=nm, title=r.title, notes=r.notes or "", kind=r.kind, priority=r.priority,
            list_name=m.get("list_name"), estimate_minutes=m.get("estimate_minutes"), budget_usd=r.budget_usd, items=steps,
            created_by=p.user_id, created_at=_now().isoformat()))
    with db.get_engine().connect() as conn:
        return _template_view(conn.execute(select(db.task_templates).where(db.task_templates.c.id == new)).first())


def _template(conn: Connection, org: str, tmpl: str):
    from .mytasks import _canonical
    if not _canonical(tmpl):
        raise PlusError("template not found", 404)
    r = conn.execute(select(db.task_templates).where(db.task_templates.c.id == tmpl, db.task_templates.c.organization_id == org)).first()
    if r is None:
        raise PlusError("template not found", 404)
    return r


def use_template(p: Principal, tmpl: str, due_at: str | None = None) -> dict:
    from . import mytasks
    with db.get_engine().connect() as conn:
        t = _template(conn, p.organization_id, tmpl)
    fields = {"title": t.title, "notes": t.notes, "kind": t.kind, "priority": t.priority, "budget_usd": t.budget_usd,
              "list_name": t.list_name, "estimate_minutes": t.estimate_minutes, "items": list(t.items or [])}
    if due_at:
        fields["due_at"] = due_at
    return mytasks.create(p, fields)


def delete_template(p: Principal, tmpl: str) -> None:
    with transaction() as conn:
        _template(conn, p.organization_id, tmpl)
        conn.execute(delete(db.task_templates).where(db.task_templates.c.id == tmpl))


# ---------------------------------------------------------------- V6.77 plan my day

def minutes_of(t: dict) -> int:
    return int(t.get("estimate_minutes") or DEFAULT_MINUTES.get(t.get("kind") or "personal", 30))


def plan_day(conn: Connection, org: str, tz: str | None = "UTC", start: str = "09:00", end: str = "18:00",
             now: datetime | None = None) -> dict:
    """Today's tasks laid out as a timeline: what needs you first (5 minutes each), results to review (10 minutes),
    then overdue, due today and the rest by priority, each for its estimate (or a default by kind), from the later of
    `start` and now until `end`. What doesn't fit is listed after. Snoozed, waiting and in-progress tasks stay off."""
    from .mytasks import PRIORITY_RANK, listing
    zone = _zone(tz)
    now = (now or _now()).astimezone(zone)

    def at(hhmm: str) -> datetime:
        try:
            h, m = (int(x) for x in hhmm.split(":"))
            return datetime.combine(now.date(), time(h, m), tzinfo=zone)
        except Exception as exc:
            raise PlusError("times are HH:MM") from exc
    day_start, day_end = at(start), at(end)
    if day_end <= day_start:
        raise PlusError("the day has to end after it starts")
    cursor = max(day_start, now.replace(second=0, microsecond=0))
    if cursor.minute % 5:
        cursor += timedelta(minutes=5 - cursor.minute % 5)
    end_of_day = datetime.combine(now.date(), time(23, 59), tzinfo=zone).astimezone(timezone.utc).isoformat()
    tasks = listing(conn, org, include_done=False)
    needs = [t for t in tasks if t["stage"] == "needs_you"]
    review = [t for t in tasks if t["stage"] == "review"]
    rest = [t for t in tasks if t["stage"] in ("open", "problem")]

    def rank(t: dict):
        due_today = bool(t["due_at"] and t["due_at"] <= end_of_day)
        return (not t["overdue"], not due_today, PRIORITY_RANK.get(t["priority"], 1), t["due_at"] or "9999", t["created_at"])
    rest.sort(key=rank)
    blocks, later = [], []
    queue = [(t, 5, "Decide") for t in needs] + [(t, 10, "Review") for t in review] + [(t, minutes_of(t), "Do") for t in rest]
    for t, mins, verb in queue:
        if cursor + timedelta(minutes=mins) > day_end:
            later.append({"task_id": t["id"], "title": t["title"], "minutes": mins})
            continue
        blocks.append({"task_id": t["id"], "title": t["title"], "verb": verb, "minutes": mins, "kind": t["kind"],
                       "priority": t["priority"], "overdue": t["overdue"], "list_name": t.get("list_name"),
                       "estimated": not t.get("estimate_minutes") and verb == "Do",
                       "start": cursor.astimezone(timezone.utc).isoformat(),
                       "end": (cursor + timedelta(minutes=mins)).astimezone(timezone.utc).isoformat()})
        cursor += timedelta(minutes=mins)
    planned = sum(b["minutes"] for b in blocks)
    return {"blocks": blocks, "later": later, "planned_minutes": planned,
            "free_minutes": max(0, int((day_end - cursor).total_seconds() // 60)) if cursor < day_end else 0,
            "day": {"start": day_start.astimezone(timezone.utc).isoformat(), "end": day_end.astimezone(timezone.utc).isoformat()}}


# ---------------------------------------------------------------- V6.76 focus

def log_focus(p: Principal, tid: str, minutes: int, started_at: str | None) -> dict:
    if not 1 <= int(minutes) <= 240:
        raise PlusError("a focus session is 1 to 240 minutes")
    try:
        start = datetime.fromisoformat((started_at or "").replace("Z", "+00:00")) if started_at else _now() - timedelta(minutes=int(minutes))
    except ValueError as exc:
        raise PlusError("that isn't a time") from exc
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if start > _now() + timedelta(minutes=1):
        raise PlusError("a session can't start in the future")
    with transaction() as conn:
        _task(conn, p.organization_id, tid)
        sid = db.new_id()
        conn.execute(insert(db.focus_sessions).values(id=sid, organization_id=p.organization_id, task_id=tid, minutes=int(minutes),
                                                      started_at=start.astimezone(timezone.utc).isoformat(), created_by=p.user_id,
                                                      created_at=_now().isoformat()))
        total = sum(r.minutes for r in conn.execute(select(db.focus_sessions.c.minutes).where(db.focus_sessions.c.task_id == tid)))
    return {"id": sid, "minutes": int(minutes), "task_total_minutes": total}


def focus_total(conn: Connection, tid: str) -> int:
    return sum(r.minutes for r in conn.execute(select(db.focus_sessions.c.minutes).where(db.focus_sessions.c.task_id == tid)))


# ---------------------------------------------------------------- V6.78 cost and time before you start

def estimate(conn: Connection, org: str, tid: str) -> dict:
    """From this server's finished runs of the same kind: the typical estimated cost and how long they took.
    Labelled as an estimate; None when there's no history yet."""
    r = _task(conn, org, tid)
    M = db.missions
    if r.kind == "code" and r.repository_id:
        q = select(M.c.spent_usd_estimated, M.c.created_at, M.c.updated_at, M.c.execution_mode).where(
            M.c.organization_id == org, M.c.kind == "fix_failing_test", M.c.status == "COMPLETED")
        what = "fix-a-failing-test runs"
    else:
        q = select(M.c.spent_usd_estimated, M.c.created_at, M.c.updated_at, M.c.execution_mode, M.c.params).where(
            M.c.organization_id == org, M.c.kind == "personal_task", M.c.status == "COMPLETED")
        what = f"{r.kind if r.kind in ('research', 'write') else 'other'} tasks"
    rows = conn.execute(q.order_by(M.c.created_at.desc()).limit(200)).fetchall()
    if r.kind != "code" or not r.repository_id:
        want = r.kind if r.kind in ("research", "write") else "personal"
        rows = [x for x in rows if ((x.params or {}).get("task_kind") or "personal") == want][:40]
    else:
        rows = rows[:40]
    from services.core.config import get_settings
    budget = float(r.budget_usd) if r.budget_usd else get_settings().default_mission_budget_usd
    if not rows:
        return {"label": "estimate", "runs": 0, "about": what, "cost_usd": None, "minutes": None, "budget_usd": budget,
                "note": "No finished runs like this yet, so there's nothing to estimate from. The budget cap still applies."}
    # simulations cost nothing, so they say nothing about what a real run costs
    costs = [float(x.spent_usd_estimated or 0) for x in rows if x.execution_mode != "simulation"]
    mins = []
    for x in rows:
        try:
            mins.append(max(0.0, (datetime.fromisoformat(x.updated_at) - datetime.fromisoformat(x.created_at)).total_seconds() / 60))
        except (TypeError, ValueError):
            continue
    sim = sum(1 for x in rows if x.execution_mode == "simulation")
    return {"label": "estimate", "runs": len(rows), "about": what, "budget_usd": budget,
            "cost_usd": {"typical": round(statistics.median(costs), 2), "high": round(max(costs), 2)} if costs else None,
            "minutes": {"typical": round(statistics.median(mins), 1), "high": round(max(mins), 1)} if mins else None,
            "simulated_runs": sim,
            "note": (f"From your last {len(rows)} finished {what}" + (f", {sim} of them simulations" if sim else "")
                     + (". They were all simulations, so there's no real cost to go by yet" if not costs else "")
                     + ". An estimate, not a quote; the run stops at its budget cap.")}


# ---------------------------------------------------------------- V6.79 feedback on results

def _doer(conn: Connection, mission_id: str) -> str | None:
    """Who wrote the result: the agent on the run's last task."""
    T, A = db.tasks, db.agents
    r = conn.execute(select(A.c.key).join(T, T.c.agent_id == A.c.id).where(T.c.mission_id == mission_id)
                     .order_by(T.c.created_at.desc())).first()
    return r.key if r else None


def give_feedback(p: Principal, tid: str, rating: int, reason: str | None) -> dict:
    if rating not in (1, -1):
        raise PlusError("rate a result up (1) or down (-1)")
    reason = " ".join((reason or "").split())[:300] or None
    with transaction() as conn:
        r = _task(conn, p.organization_id, tid)
        if not r.mission_id:
            raise PlusError("there's no result to rate yet", 409)
        st = conn.execute(select(db.missions.c.status).where(db.missions.c.id == r.mission_id)).scalar()
        if st != "COMPLETED":
            raise PlusError("rate a result once its run has finished", 409)
        F = db.task_feedback
        agent = _doer(conn, r.mission_id)
        if conn.execute(select(F.c.id).where(F.c.mission_id == r.mission_id)).first():
            conn.execute(update(F).where(F.c.mission_id == r.mission_id).values(rating=rating, reason=reason or "", created_at=_now().isoformat()))
        else:
            conn.execute(insert(F).values(id=db.new_id(), organization_id=p.organization_id, task_id=tid, mission_id=r.mission_id,
                                          rating=rating, reason=reason or "", agent_key=agent, created_by=p.user_id, created_at=_now().isoformat()))
        emit(conn, "my_task.rated", org_id=p.organization_id, mission_id=r.mission_id,
             payload={"task_id": tid, "rating": rating, "agent": agent})
    return {"rating": rating, "reason": reason, "agent": agent}


def feedback_for(conn: Connection, mission_id: str | None) -> dict | None:
    if not mission_id:
        return None
    r = conn.execute(select(db.task_feedback).where(db.task_feedback.c.mission_id == mission_id)).first()
    return {"rating": r.rating, "reason": r.reason or None, "agent": r.agent_key} if r else None


def agent_quality(conn: Connection, org: str) -> list[dict]:
    F, A = db.task_feedback, db.agents
    stats: dict[str, dict] = {}
    for r in conn.execute(select(F.c.agent_key, F.c.rating, F.c.reason).where(F.c.organization_id == org).order_by(F.c.created_at.desc())):
        s = stats.setdefault(r.agent_key or "unknown", {"agent": r.agent_key or "unknown", "up": 0, "down": 0, "recent_reasons": []})
        s["up" if r.rating > 0 else "down"] += 1
        if r.rating < 0 and r.reason and len(s["recent_reasons"]) < 3:
            s["recent_reasons"].append(r.reason)
    names = {r.key: r.name for r in conn.execute(select(A.c.key, A.c.name))}
    out = []
    for s in stats.values():
        n = s["up"] + s["down"]
        s["name"] = names.get(s["agent"], s["agent"])
        s["score"] = round(s["up"] / n, 2) if n else None
        out.append(s)
    return sorted(out, key=lambda s: (-(s["up"] + s["down"]), s["name"]))


# ---------------------------------------------------------------- V6.80 results library

def results(conn: Connection, org: str, q: str | None = None, kind: str | None = None, limit: int = 50) -> list[dict]:
    """Every result the agents wrote for your tasks, newest first; searchable by words in the title or text."""
    M, A, T = db.missions, db.artifacts, db.my_tasks
    words = [w for w in re.findall(r"[a-z0-9]{2,}", (q or "").lower())][:8]
    query = (select(A.c.id, A.c.title, A.c.content, A.c.created_at, M.c.id.label("mission_id"), M.c.execution_mode, M.c.params)
             .join(M, M.c.id == A.c.mission_id)
             .where(M.c.organization_id == org, M.c.kind == "personal_task", A.c.kind == "note"))
    for w in words:  # searched in the database, so older results are found too (words are letters and digits only)
        query = query.where(or_(A.c.title.ilike(f"%{w}%"), A.c.content.ilike(f"%{w}%")))
    rows = conn.execute(query.order_by(A.c.created_at.desc()).limit(500)).fetchall()
    titles = {r.id: r.title for r in conn.execute(select(T.c.id, T.c.title).where(T.c.organization_id == org))}
    fb = {r.mission_id: r.rating for r in conn.execute(select(db.task_feedback.c.mission_id, db.task_feedback.c.rating)
                                                       .where(db.task_feedback.c.organization_id == org))}
    out = []
    for r in rows:
        params = r.params or {}
        k = params.get("task_kind") or "personal"
        if kind and k != kind:
            continue
        hay = f"{r.title} {r.content}".lower()
        if words and not all(w in hay for w in words):
            continue
        tid = params.get("task_id")
        text = r.content or ""
        out.append({"artifact_id": r.id, "title": r.title, "task_id": tid, "task_title": titles.get(tid), "kind": k,
                    "created_at": r.created_at, "simulated": r.execution_mode == "simulation", "rating": fb.get(r.mission_id),
                    "excerpt": re.sub(r"\s+", " ", text)[:220], "content": text, "mission_id": r.mission_id})
        if len(out) >= max(1, min(limit, 200)):
            break
    return out


# ---------------------------------------------------------------- V6.83 insights

def insights(conn: Connection, org: str, tz: str | None = "UTC", days: int = 14) -> dict:
    zone = _zone(tz)
    days = max(7, min(int(days), 60))
    today = _now().astimezone(zone).date()
    first = today - timedelta(days=days - 1)
    since = datetime.combine(first, time(0, 0), tzinfo=zone).astimezone(timezone.utc).isoformat()
    T, F, M = db.my_tasks, db.focus_sessions, db.missions
    per = {(first + timedelta(days=i)).isoformat(): {"day": (first + timedelta(days=i)).isoformat(), "done": 0, "added": 0, "focus_minutes": 0}
           for i in range(days)}

    def local_day(iso: str) -> str:
        return datetime.fromisoformat(iso).astimezone(zone).date().isoformat()
    on_time = late = 0
    for r in conn.execute(select(T.c.done_at, T.c.due_at).where(T.c.organization_id == org, T.c.status == "DONE", T.c.done_at >= since)):
        d = local_day(r.done_at)
        if d in per:
            per[d]["done"] += 1
        if r.due_at:
            if r.done_at <= r.due_at:
                on_time += 1
            else:
                late += 1
    for r in conn.execute(select(T.c.created_at).where(T.c.organization_id == org, T.c.created_at >= since)):
        d = local_day(r.created_at)
        if d in per:
            per[d]["added"] += 1
    for r in conn.execute(select(F.c.started_at, F.c.minutes).where(F.c.organization_id == org, F.c.started_at >= since)):
        d = local_day(r.started_at)
        if d in per:
            per[d]["focus_minutes"] += r.minutes
    runs = {"completed": 0, "failed": 0, "cancelled": 0, "simulated": 0}
    for r in conn.execute(select(M.c.status, M.c.execution_mode).where(M.c.organization_id == org, M.c.kind == "personal_task",
                                                                      M.c.created_at >= since)):
        key = {"COMPLETED": "completed", "FAILED": "failed", "CANCELLED": "cancelled"}.get(r.status)
        if key:
            runs[key] += 1
        if r.execution_mode == "simulation":
            runs["simulated"] += 1
    ratings = [r.rating for r in conn.execute(select(db.task_feedback.c.rating).where(db.task_feedback.c.organization_id == org,
                                                                                      db.task_feedback.c.created_at >= since))]
    series = list(per.values())
    done = sum(x["done"] for x in series)
    focus = sum(x["focus_minutes"] for x in series)
    open_now = len(conn.execute(select(T.c.id).where(T.c.organization_id == org, T.c.status == "OPEN")).fetchall())
    best = max(series, key=lambda x: x["done"]) if done else None
    out = {"days": days, "series": series, "done": done, "added": sum(x["added"] for x in series), "open": open_now,
           "on_time_rate": round(on_time / (on_time + late), 2) if on_time + late else None, "on_time": on_time, "late": late,
           "focus_minutes": focus, "runs": runs,
           "ratings": {"up": sum(1 for r in ratings if r > 0), "down": sum(1 for r in ratings if r < 0)},
           "best_day": best["day"] if best else None}
    parts = [f"{done} done in {days} days"]
    if out["on_time_rate"] is not None:
        parts.append(f"{int(out['on_time_rate'] * 100)}% on time")
    if focus:
        parts.append(f"{focus // 60}h {focus % 60}m focused" if focus >= 60 else f"{focus}m focused")
    out["headline"] = ", ".join(parts) + "."
    return out


# ---------------------------------------------------------------- V6.84 weekly review

def review(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    from .mytasks import listing
    zone = _zone(tz)
    now = _now()
    local = now.astimezone(zone)
    monday = datetime.combine(local.date() - timedelta(days=local.weekday()), time(0, 0), tzinfo=zone)
    week_start = monday.astimezone(timezone.utc).isoformat()
    stale_cut = (now - timedelta(days=14)).isoformat()
    tasks = listing(conn, org, include_done=True)
    done = [t for t in tasks if t["stage"] == "done" and (t.get("done_at") or "") >= week_start]
    slipped = [t for t in tasks if t["overdue"] and t["status"] == "OPEN"]
    stale = [t for t in tasks if t["status"] == "OPEN" and not t["due_at"] and t["created_at"] < stale_cut and t["stage"] == "open"]
    upcoming_end = (now + timedelta(days=7)).isoformat()
    upcoming = [t for t in tasks if t["status"] == "OPEN" and t["due_at"] and now.isoformat() <= t["due_at"] <= upcoming_end]
    return {"week_of": (local.date() - timedelta(days=local.weekday())).isoformat(), "done": done, "slipped": slipped,
            "stale": stale, "upcoming": upcoming,
            "summary": f"{len(done)} done this week, {len(slipped)} slipped, {len(stale)} sitting for two weeks or more, "
                       f"{len(upcoming)} due in the next seven days."}


def bulk(p: Principal, ids: list[str], action: str, tz: str | None = "UTC", due_at: str | None = None) -> dict:
    """The weekly review's decisions in one go: done, drop, snooze to next week, or move the due date."""
    from . import mytasks
    if action not in ("done", "drop", "next_week", "due"):
        raise PlusError("choose done, drop, next_week or due")
    ids = list(dict.fromkeys(ids))[:100]
    if not ids:
        raise PlusError("pick some tasks")
    changed, errors = [], []
    for tid in ids:
        try:
            if action == "done":
                mytasks.complete(p, tid, tz)
            elif action == "drop":
                mytasks.set_status(p, tid, "DROPPED")
            elif action == "next_week":
                snooze(p, tid, "next_week", None, tz)
            else:
                if not due_at:
                    raise PlusError("give the new due date")
                mytasks.edit(p, tid, {"due_at": due_at})
            changed.append(tid)
        except (PlusError, mytasks.TaskError) as exc:
            errors.append({"task_id": tid, "error": str(exc)})
    return {"changed": changed, "errors": errors}
