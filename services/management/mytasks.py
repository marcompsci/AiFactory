"""The owner's task list (V6.43–V6.49).

A task is something the owner needs done: "draft the Echo blurb by Friday", "fix the failing StackSprint test",
"research budgeting apps". It lives here whether or not the factory works on it. Pressing Do it hands it to the agents
(V6.45): code with a repository goes to the regular fix-a-failing-test mission; everything else to a personal_task
mission where the General Manager plans the steps and the right agent writes up the result. The task follows that
mission (V6.46) and comes back for review (V6.47); only the owner marks it done. Repeating tasks queue their next
occurrence when one is done (V6.49).

Nothing here spends money on its own: a run starts only when someone with the operator role presses Do it (or confirms
it in the City chat), under the charter's caps, with the mission's budget.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Connection

from services.core import db
from services.core.auth import Principal
from services.core.events import emit, transaction
from services.core.text import plural

from . import capture

KINDS = ("code", "research", "write", "personal")
PRIORITIES = ("urgent", "normal", "low")
REPEATS = ("none", "daily", "weekdays", "weekly", "biweekly", "monthly", "monthly_last", "yearly")  # plus "days:N" (capture.valid_repeat)
MAX_OPEN = 500
STARTING_TIMEOUT = __import__("datetime").timedelta(minutes=2)
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}
PRIORITY_RANK = {"urgent": 0, "normal": 1, "low": 2}


class TaskError(ValueError):
    def __init__(self, msg: str, status: int = 422) -> None:
        super().__init__(msg)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical(tid: str) -> bool:
    """Only the plain lower-case form of an id: other spellings uuid.UUID accepts ("urn:uuid:…", "{…}") are spelled
    differently in the table, and Postgres would refuse some of them with an error."""
    try:
        return str(uuid.UUID(str(tid))) == str(tid)
    except ValueError:
        return False


def _row(conn: Connection, org: str, tid: str):
    if not _canonical(tid):
        raise TaskError("task not found", 404)
    r = conn.execute(select(db.my_tasks).where(db.my_tasks.c.id == tid, db.my_tasks.c.organization_id == org)).first()
    if r is None:
        raise TaskError("task not found", 404)
    return r


def _due(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise TaskError("due date isn't a date") from exc
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat()


def _clean(fields: dict) -> dict:
    out: dict = {}
    if "title" in fields:
        t = " ".join(str(fields["title"] or "").split())
        if not 2 <= len(t) <= 160:
            raise TaskError("give the task a title of 2 to 160 characters")
        out["title"] = t
    if "notes" in fields:
        out["notes"] = str(fields["notes"] or "")[:4000]
    if fields.get("repeat") is not None and not capture.valid_repeat(fields["repeat"]):
        raise TaskError("repeat must be none, daily, weekdays, weekly, biweekly, monthly, monthly_last, yearly or days:N (2 to 365)")
    if fields.get("repeat") is not None:
        out["repeat"] = fields["repeat"]
    for key, allowed in (("kind", KINDS), ("priority", PRIORITIES)):
        if key in fields and fields[key] is not None:
            if fields[key] not in allowed:
                raise TaskError(f"{key} must be one of {', '.join(allowed)}")
            out[key] = fields[key]
    if "due_at" in fields:
        out["due_at"] = _due(fields["due_at"])
    if "budget_usd" in fields:
        b = fields["budget_usd"]
        if b is not None and not (0 < float(b) <= 50):
            raise TaskError("a task budget is between $0.01 and $50")
        out["budget_usd"] = float(b) if b is not None else None
    if "repository_id" in fields:
        out["repository_id"] = fields["repository_id"] or None
    return out


def _check_repo(conn: Connection, org: str, repo: str | None) -> None:
    if not repo:
        return
    if not _canonical(repo):
        raise TaskError("that repository isn't one of yours", 404)
    ok = conn.execute(select(db.repositories.c.id).where(db.repositories.c.id == repo, db.repositories.c.organization_id == org)).first()
    if ok is None:
        raise TaskError("that repository isn't one of yours", 404)


# ---------------------------------------------------------------- reading

def _missions(conn: Connection, ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    M, A = db.missions, db.artifacts
    out = {r.id: {"status": r.status, "execution_mode": r.execution_mode, "spent_usd_estimated": float(r.spent_usd_estimated or 0),
                  "budget_usd": float(r.budget_usd or 0), "kind": r.kind}
           for r in conn.execute(select(M.c.id, M.c.status, M.c.execution_mode, M.c.spent_usd_estimated, M.c.budget_usd, M.c.kind)
                                 .where(M.c.id.in_(ids)))}
    for a in conn.execute(select(A.c.id, A.c.mission_id, A.c.kind, A.c.title, A.c.created_at).where(A.c.mission_id.in_(ids))
                          .order_by(A.c.created_at)):
        m = out.get(a.mission_id)
        if m is not None:
            if a.kind == "plan":
                m["plan_artifact_id"] = a.id
            else:
                m["result_artifact_id"] = a.id  # the last one written is the result to review
    return out


def stage(task, mission: dict | None) -> str:
    """Where a task stands: open, working, needs_you, review, problem, done, dropped."""
    if task.status == "DONE":
        return "done"
    if task.status == "DROPPED":
        return "dropped"
    if not mission:
        return "open"
    s = mission["status"]
    if s == "WAITING_FOR_APPROVAL":
        return "needs_you"
    if s not in TERMINAL:
        return "working"
    if s == "COMPLETED":
        return "review"
    return "problem"


def _view(task, mission: dict | None, now: datetime, meta: dict | None = None, items: list | None = None,
          open_ids: set | None = None, waiting: dict | None = None, goal_id: str | None = None) -> dict:
    d = dict(task._mapping)
    d["stage"] = stage(task, mission)
    d["mission"] = mission
    d["repeat_label"] = capture.repeat_label(task.repeat)
    d["overdue"] = bool(task.due_at and task.status == "OPEN" and datetime.fromisoformat(task.due_at) < now)
    meta = meta or {}
    d["list_name"] = meta.get("list_name")
    d["estimate_minutes"] = meta.get("estimate_minutes")
    snoozed = meta.get("snoozed_until")
    d["snoozed_until"] = snoozed if snoozed and snoozed > now.isoformat() else None
    blocker = meta.get("blocked_by")
    d["blocked_by"] = blocker if blocker and (open_ids is None or blocker in open_ids) else None
    d["waiting_for"] = waiting  # V6.107 {person, follow_up_at}
    d["follow_up_due"] = bool(waiting and waiting["follow_up_at"] <= now.isoformat())
    d["goal_id"] = goal_id
    if d["stage"] == "open":  # V6.70/V6.71/V6.107: set aside until later, waiting on a task, or waiting for a person
        if d["blocked_by"]:
            d["stage"] = "blocked"
        elif d["snoozed_until"]:
            d["stage"] = "snoozed"
        elif waiting and not d["follow_up_due"]:
            d["stage"] = "waiting"
    items = items or []
    d["items_total"] = len(items)
    d["items_done"] = sum(1 for i in items if i["done"])
    return d


def _open_ids(conn: Connection, org: str) -> set:
    T = db.my_tasks
    return {r.id for r in conn.execute(select(T.c.id).where(T.c.organization_id == org, T.c.status == "OPEN"))}


def listing(conn: Connection, org: str, include_done: bool = True, archived: bool = False) -> list[dict]:
    """Open tasks, plus those closed in the last 30 days (older ones are in the archive, V6.108, unless `archived`)."""
    from . import taskextra, taskplus
    T = db.my_tasks
    q = select(T).where(T.c.organization_id == org)
    if not include_done:
        q = q.where(T.c.status == "OPEN")
    rows = conn.execute(q.order_by(T.c.created_at.desc()).limit(2000)).fetchall()
    if include_done and not archived:
        cut = taskextra.archive_cutoff()
        rows = [r for r in rows if r.status == "OPEN" or ((r.done_at or r.updated_at) or "") >= cut]
    rows = rows[:1000]
    ms = _missions(conn, [r.mission_id for r in rows if r.mission_id])
    ids = [r.id for r in rows]
    metas, items, open_ids = taskplus.meta_for(conn, org, ids), taskplus.items_for(conn, org, ids), _open_ids(conn, org)
    waits, goals = taskextra.waiting_for(conn, org, ids), taskextra.goal_for(conn, org, ids)
    now = _now()
    out = [_view(r, ms.get(r.mission_id) if r.mission_id else None, now, metas.get(r.id), items.get(r.id), open_ids,
                 waits.get(r.id), goals.get(r.id)) for r in rows]
    out.sort(key=sort_key)
    return out


def sort_key(t: dict):
    order = {"needs_you": 0, "review": 1, "problem": 2, "working": 3, "open": 4, "blocked": 5, "waiting": 6, "snoozed": 7,
             "done": 8, "dropped": 9}
    return (order.get(t["stage"], 9), t["due_at"] is None, t["due_at"] or "", PRIORITY_RANK.get(t["priority"], 1), t["created_at"])


def get(conn: Connection, org: str, tid: str, tz: str | None = "UTC") -> dict:
    from . import taskplus
    r = _row(conn, org, tid)
    ms = _missions(conn, [r.mission_id] if r.mission_id else [])
    items = taskplus.items_for(conn, org, [tid]).get(tid, [])
    from . import taskextra
    d = _view(r, ms.get(r.mission_id) if r.mission_id else None, _now(), taskplus.meta_for(conn, org, [tid]).get(tid), items,
              _open_ids(conn, org), taskextra.waiting_for(conn, org, [tid]).get(tid), taskextra.goal_for(conn, org, [tid]).get(tid))
    d["items"] = items
    d["feedback"] = taskplus.feedback_for(conn, r.mission_id)
    d["focus_minutes"] = taskplus.focus_total(conn, tid)
    from . import taskmore
    d["links"] = taskmore.links_for(conn, org, [tid]).get(tid, [])
    d["streak"] = taskmore.streak_for(conn, org, r, tz)
    if d["blocked_by"]:
        d["blocked_by_title"] = conn.execute(select(db.my_tasks.c.title).where(db.my_tasks.c.id == d["blocked_by"])).scalar()
    m = d["mission"] or {}
    A = db.artifacts
    for key in ("plan_artifact_id", "result_artifact_id"):
        if m.get(key):
            a = conn.execute(select(A.c.id, A.c.title, A.c.content, A.c.created_at).where(A.c.id == m[key])).first()
            d[key.replace("_artifact_id", "")] = dict(a._mapping) if a else None
    return d


# ---------------------------------------------------------------- writing

def create(p: Principal, fields: dict) -> dict:
    from . import taskplus
    fields = dict(fields)
    extra = {"list_name": taskplus.clean_list(fields.pop("list_name", None)),
             "estimate_minutes": taskplus.clean_estimate(fields.pop("estimate_minutes", None))}
    steps = [s for s in (fields.pop("items", None) or []) if str(s).strip()][:taskplus.MAX_ITEMS]
    ref = fields.pop("client_ref", None)
    from . import taskmore
    urls = []
    for u in (fields.pop("links", None) or [])[:taskmore.MAX_LINKS]:
        try:
            urls.append(taskmore.clean_url(u))
        except taskmore.PlusError as exc:
            raise TaskError(str(exc)) from exc
    clean = _clean({"kind": None, "priority": "normal", "repeat": "none", **fields})
    if "title" not in clean:
        raise TaskError("give the task a title of 2 to 160 characters")
    clean.setdefault("kind", capture.kind_of(clean["title"]))
    tid = db.new_id()
    T = db.my_tasks
    seen = None
    with transaction() as conn:
        if ref:  # the phone sent this add before (a timed-out reply, then the outbox): hand back the task it made
            seen = conn.execute(select(db.task_meta.c.task_id).where(db.task_meta.c.organization_id == p.organization_id,
                                                                     db.task_meta.c.client_ref == ref)).scalar()
    if seen:
        with db.get_engine().connect() as conn:
            return get(conn, p.organization_id, seen)
    with transaction() as conn:
        _check_repo(conn, p.organization_id, clean.get("repository_id"))
        n = len(conn.execute(select(T.c.id).where(T.c.organization_id == p.organization_id, T.c.status == "OPEN")).fetchall())
        if n >= MAX_OPEN:
            raise TaskError(f"you already have {MAX_OPEN} open tasks; finish or drop some first", 409)
        now = _now().isoformat()
        conn.execute(insert(T).values(id=tid, organization_id=p.organization_id, status="OPEN", runs=0, created_by=p.user_id,
                                      created_at=now, updated_at=now, notes=clean.pop("notes", ""), **clean))
        if ref:
            extra["client_ref"] = ref
        if any(extra.values()):
            taskplus.set_meta(conn, p.organization_id, tid, **extra)
        if steps:
            taskplus._insert_items(conn, p.organization_id, tid, steps)
        emit(conn, "my_task.created", org_id=p.organization_id,
             payload={"task_id": tid, "title": clean["title"], "kind": clean["kind"], "due_at": clean.get("due_at")})
        for u in urls:
            taskmore.add_link(p, tid, u, conn=conn)
    with db.get_engine().connect() as conn:
        return get(conn, p.organization_id, tid)


def create_from_text(p: Principal, text: str, tz: str | None = "UTC", extra: dict | None = None) -> dict:
    from . import taskmore
    text, urls = taskmore.take_urls(text)  # V6.93: web addresses become the task's links
    parsed = capture.parse(text, tz)
    if len(parsed["title"]) < 2:
        raise TaskError("say what the task is")
    fields = {k: parsed[k] for k in ("title", "kind", "priority", "due_at", "repeat", "budget_usd", "list_name", "estimate_minutes")}
    if urls:
        fields["links"] = urls
    fields.update({k: v for k, v in (extra or {}).items() if v is not None})
    return create(p, fields)


def edit(p: Principal, tid: str, fields: dict) -> dict:
    from . import taskplus
    fields = dict(fields)
    meta: dict = {}
    try:
        if "list_name" in fields:
            meta["list_name"] = taskplus.clean_list(fields.pop("list_name"))
        if "estimate_minutes" in fields:
            meta["estimate_minutes"] = taskplus.clean_estimate(fields.pop("estimate_minutes"))
    except taskplus.PlusError as exc:
        raise TaskError(str(exc), exc.status) from exc
    blocked = fields.pop("blocked_by", ...) if "blocked_by" in fields else ...
    clean = _clean(fields)
    if not clean and not meta and blocked is ...:
        raise TaskError("nothing to change")
    with transaction() as conn:
        _row(conn, p.organization_id, tid)
        if "repository_id" in clean:
            _check_repo(conn, p.organization_id, clean["repository_id"])
        if blocked is not ...:
            try:
                meta["blocked_by"] = taskplus.check_blocker(conn, p.organization_id, tid, blocked or None)
            except taskplus.PlusError as exc:
                raise TaskError(str(exc), exc.status) from exc
        if clean:
            conn.execute(update(db.my_tasks).where(db.my_tasks.c.id == tid).values(updated_at=_now().isoformat(), **clean))
        if meta:
            taskplus.set_meta(conn, p.organization_id, tid, **meta)
        emit(conn, "my_task.updated", org_id=p.organization_id, payload={"task_id": tid, "fields": sorted([*clean, *meta])})
    with db.get_engine().connect() as conn:
        return get(conn, p.organization_id, tid)


def complete(p: Principal, tid: str, tz: str | None = "UTC") -> dict:
    """Mark a task done (the owner's call, never the agents'). A repeating task queues its next occurrence."""
    T = db.my_tasks
    nxt_id = None
    with db.get_engine().connect() as conn:
        _stop_run(p, _row(conn, p.organization_id, tid))
    with transaction() as conn:
        r = _row(conn, p.organization_id, tid)
        now = _now().isoformat()
        changed = conn.execute(update(T).where(T.c.id == tid, T.c.status != "DONE").values(status="DONE", done_at=now, updated_at=now)).rowcount
        if not changed:
            return {"task": get(conn, p.organization_id, tid), "next": None}
        already = conn.execute(select(T.c.id).where(T.c.repeat_of == tid)).first()  # done, reopened, done again: one repeat
        if r.repeat != "none" and already is None:
            nxt_id = db.new_id()
            conn.execute(insert(T).values(id=nxt_id, organization_id=r.organization_id, title=r.title, notes=r.notes, kind=r.kind,
                                          priority=r.priority, status="OPEN",
                                          due_at=capture.next_due(r.due_at, r.repeat, tz, anchor=_first_due(conn, r)),
                                          repeat=r.repeat, budget_usd=r.budget_usd, repository_id=r.repository_id, runs=0,
                                          repeat_of=tid, created_by=p.user_id, created_at=now, updated_at=now))
            from . import taskplus
            taskplus.copy_details(conn, r.organization_id, tid, nxt_id)
        emit(conn, "my_task.completed", org_id=p.organization_id,
             payload={"task_id": tid, "title": r.title, "next_task_id": nxt_id, "had_run": bool(r.mission_id)})
    with db.get_engine().connect() as conn:
        return {"task": get(conn, p.organization_id, tid), "next": get(conn, p.organization_id, nxt_id) if nxt_id else None}


def _first_due(conn: Connection, r) -> str | None:
    """The first due date of a repeating series (follows repeat_of back; at most 400 steps)."""
    from . import taskmore
    chain = taskmore.chain_rows(conn, r.organization_id, r.id)
    dated = [x for x in chain if x["due_at"]]
    return dated[-1]["due_at"] if dated else r.due_at


def _stop_run(p: Principal, r) -> None:
    """A task you finish, drop or delete takes its run with it: a run still going is cancelled, so nothing keeps
    working (or spending) on something you've set aside."""
    if not r.mission_id:
        return
    with db.get_engine().connect() as conn:
        st = conn.execute(select(db.missions.c.status).where(db.missions.c.id == r.mission_id)).scalar()
    if st and st not in TERMINAL:
        from fastapi import HTTPException

        from services.api import main
        try:
            main.cancel(r.mission_id, p)
        except HTTPException as exc:
            if exc.status_code != 409:  # 409: it finished on its own in the meantime
                raise


def set_status(p: Principal, tid: str, status: str) -> dict:
    """Reopen (OPEN) or drop (DROPPED) a task."""
    if status not in ("OPEN", "DROPPED"):
        raise TaskError("a task can be reopened or dropped")
    if status == "DROPPED":
        with db.get_engine().connect() as conn:
            _stop_run(p, _row(conn, p.organization_id, tid))
    with transaction() as conn:
        r = _row(conn, p.organization_id, tid)
        conn.execute(update(db.my_tasks).where(db.my_tasks.c.id == tid).values(status=status, done_at=None, updated_at=_now().isoformat()))
        emit(conn, "my_task.updated", org_id=p.organization_id, payload={"task_id": tid, "title": r.title, "status": status})
    with db.get_engine().connect() as conn:
        return get(conn, p.organization_id, tid)


def remove(p: Principal, tid: str) -> None:
    from . import taskplus
    with db.get_engine().connect() as conn:
        _stop_run(p, _row(conn, p.organization_id, tid))
    with transaction() as conn:
        r = _row(conn, p.organization_id, tid)
        taskplus.forget(conn, tid)
        conn.execute(delete(db.my_tasks).where(db.my_tasks.c.id == tid))
        emit(conn, "my_task.deleted", org_id=p.organization_id, payload={"task_id": tid, "title": r.title})


# ---------------------------------------------------------------- V6.45 do it for me

def do_it(p: Principal, tid: str, redo_note: str | None = None) -> dict:
    """Hand the task to the agents as `p`. Claimed first (a conditional update on the run count), so two presses can't
    both start one; a press while a run is still going gets 409."""
    from fastapi import HTTPException
    from sqlalchemy import or_
    T = db.my_tasks
    note = " ".join((redo_note or "").split())[:1000] or None
    now = _now()
    stale = (now - STARTING_TIMEOUT).isoformat()  # a claim left by a crash mid-start lapses after this
    with transaction() as conn:
        r = _row(conn, p.organization_id, tid)
        if r.status != "OPEN":
            raise TaskError("reopen the task first", 409)
        if r.mission_id:
            st = conn.execute(select(db.missions.c.status).where(db.missions.c.id == r.mission_id)).scalar()
            if st and st not in TERMINAL:
                raise TaskError("the agents are already working on it", 409)
        claimed = conn.execute(update(T).where(T.c.id == tid, T.c.status == "OPEN", T.c.runs == r.runs,
                                               or_(T.c.starting_at.is_(None), T.c.starting_at < stale))
                               .values(runs=r.runs + 1, starting_at=now.isoformat(), updated_at=now.isoformat())).rowcount
        if not claimed:
            raise TaskError("it's starting right now", 409)
    try:
        mid = _start(p, r, note)
    except BaseException as exc:
        with transaction() as conn:  # give the claim back, so it can be tried again straight away
            conn.execute(update(T).where(T.c.id == tid).values(runs=r.runs, starting_at=None))
        if isinstance(exc, (HTTPException, TaskError, KeyboardInterrupt, SystemExit)):
            raise
        raise TaskError(f"couldn't start it: {exc}"[:300]) from exc
    with transaction() as conn:
        conn.execute(update(T).where(T.c.id == tid).values(mission_id=mid, starting_at=None, updated_at=_now().isoformat()))
        emit(conn, "my_task.started", mission_id=mid, org_id=p.organization_id,
             payload={"task_id": tid, "title": r.title, "mission_id": mid, "redo": bool(note)})
    with db.get_engine().connect() as conn:
        return get(conn, p.organization_id, tid)


def _start(p: Principal, r, note: str | None) -> str:
    from fastapi import HTTPException

    from services.management import charter
    from services.management.hierarchy import general_manager
    from services.management.manager import record_decision
    from services.management.pipeline import create_mission

    from . import links
    if r.kind == "code" and r.repository_id:
        prompt = f"{r.title}. {r.notes}".strip() + (f"\nChanges asked for after the last run: {note}" if note else "")
        spec = {"kind": "fix_failing_test", "prompt": prompt[:4000], "title": r.title[:120], "repository_id": r.repository_id,
                "budget_usd": float(r.budget_usd) if r.budget_usd else None}
        return links.start(spec, p, priority=r.priority, key=f"task:{r.id}:{r.runs + 1}")
    from services.core.config import get_settings
    task_kind = r.kind if r.kind in ("research", "write") else "personal"
    with transaction() as conn:
        if conn.execute(select(db.organizations.c.emergency_stopped).where(db.organizations.c.id == p.organization_id)).scalar():
            raise HTTPException(409, "emergency stop is engaged")
        budget = float(r.budget_usd) if r.budget_usd is not None else get_settings().default_mission_budget_usd
        if r.budget_usd is not None:
            try:
                charter.check_mission_budget(conn, p.organization_id, budget)
            except charter.CharterError as exc:
                raise TaskError(str(exc)) from exc
        else:  # the default budget is held to the charter's cap, as for any mission
            cap = charter.rules(conn, p.organization_id).get("mission_budget_cap_usd")
            if cap is not None and budget > cap:
                budget = float(cap)
        mid = create_mission(conn, org_id=p.organization_id, kind="personal_task", title=r.title,
                             prompt=f"Do the owner's task and write up the result for review: {r.title}",
                             params={"task_id": r.id, "task_kind": task_kind, "title": r.title, "notes": r.notes or "",
                                     "redo_note": note or ""},
                             opportunity_id=None, created_by=p.user_id, budget_usd=budget)
        if r.priority != "normal":
            conn.execute(insert(db.mission_priorities).values(mission_id=mid, organization_id=p.organization_id, priority=r.priority,
                                                              set_by=p.user_id))
        gm = general_manager(conn)
        doer = {"research": "researcher", "write": "designer"}.get(task_kind, "general_manager")
        record_decision(conn, decision_type="goal_assignment", subject_type="mission", subject_id=mid, outcome=f"assigned:{doer}",
                        rationale=f"Owner's task → a reviewed result: plan the steps, then {doer.replace('_', ' ')} does it and writes it up.",
                        manager_agent_id=gm.id, event="manager.goal_assigned")
    from services.api.main import state
    state.worker.enqueue(mid)
    return mid


# ---------------------------------------------------------------- V6.48 today

def today(conn: Connection, org: str, tz: str | None = "UTC") -> dict:
    try:
        zone = ZoneInfo(tz or "UTC")
    except Exception:
        zone = ZoneInfo("UTC")
    now = _now()
    local = now.astimezone(zone)
    end = local.replace(hour=23, minute=59, second=59).astimezone(timezone.utc).isoformat()
    tasks = listing(conn, org, include_done=False)
    done_today = conn.execute(select(db.my_tasks.c.id).where(db.my_tasks.c.organization_id == org, db.my_tasks.c.status == "DONE",
                                                             db.my_tasks.c.done_at >= local.replace(hour=0, minute=0, second=0)
                                                             .astimezone(timezone.utc).isoformat())).fetchall()
    sections = {
        "needs_you": [t for t in tasks if t["stage"] == "needs_you"],
        "review": [t for t in tasks if t["stage"] in ("review", "problem")],
        "overdue": [t for t in tasks if t["overdue"] and t["stage"] in ("open", "working")],
        "today": [t for t in tasks if t["due_at"] and now.isoformat() <= t["due_at"] <= end and t["stage"] in ("open", "working")],
        "working": [t for t in tasks if t["stage"] == "working"],
    }
    nxt = next((t for t in sorted((t for t in tasks if t["stage"] == "open"),
                                  key=lambda t: (not t["overdue"], t["due_at"] is None, t["due_at"] or "", PRIORITY_RANK[t["priority"]])) ), None)
    out = {**sections, "next": nxt, "open": len(tasks), "done_today": len(done_today)}
    out["spoken"] = spoken(out)
    return out


def spoken(t: dict) -> str:
    parts = []
    if t["needs_you"]:
        parts.append(f"{plural(len(t['needs_you']), 'task')} need{'s' if len(t['needs_you']) == 1 else ''} your approval")
    if t["review"]:
        parts.append(f"{plural(len(t['review']), 'result')} to review")
    if t["overdue"]:
        parts.append(f"{len(t['overdue'])} overdue")
    if t["today"]:
        parts.append(f"{len(t['today'])} due today")
    if t["working"]:
        parts.append(f"the agents are working on {len(t['working'])}")
    if not t["open"]:
        line = "Your list is clear."
    elif parts:
        line = "You have " + ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1] + "."
    else:
        line = f"You have {plural(t['open'], 'open task')}, nothing due today."
    if t["next"]:
        line += f" Next up: {t['next']['title']}."
    if t["done_today"]:
        line += f" {plural(t['done_today'], 'task')} done today."
    return line


def find(conn: Connection, org: str, text: str) -> dict | None:
    """The open task a phrase names ("do the blurb task", "the Echo blurb"), or None."""
    import re
    words = {w for w in re.findall(r"[a-z0-9]{3,}", text.lower())} - {"the", "task", "do", "for", "and", "please", "start", "work", "on", "my"}
    if not words:
        return None
    best, score = None, 0
    for t in listing(conn, org, include_done=False):
        s = len(words & set(re.findall(r"[a-z0-9]{3,}", t["title"].lower())))
        if s > score:
            best, score = t, s
    return best


def week_done(conn: Connection, org: str, since: str) -> int:
    return len(conn.execute(select(db.my_tasks.c.id).where(db.my_tasks.c.organization_id == org, db.my_tasks.c.status == "DONE",
                                                           db.my_tasks.c.done_at >= since)).fetchall())
