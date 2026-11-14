"""More for the task list (V6.88–V6.97): search, undo, each task's history, links, habit streaks and the morning digest.

Like the rest of the task list this is the owner's own bookkeeping: nothing here starts a run, spends money or opens a
link. Links are stored and shown for you to open; the agents never fetch them.
"""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy import delete, insert, or_, select, update
from sqlalchemy.engine import Connection

from services.core import db
from services.core.auth import Principal
from services.core.events import emit, transaction

from .taskplus import PlusError, _now, _task, _zone

MAX_LINKS = 20
URL_RX = re.compile(r"https?://[^\s<>\"']{3,2040}", re.I)


# ---------------------------------------------------------------- V6.90 search

def search_ids(conn: Connection, org: str, q: str) -> set[str]:
    """Tasks whose title, notes, list, checklist or links mention every word of `q` (any script, up to 8 words).
    A search with no words in it finds nothing."""
    words = [w.replace("_", "") for w in re.findall(r"\w+", (q or "").lower())]
    words = [w for w in words if w][:8]
    T, M, I, L = db.my_tasks, db.task_meta, db.task_items, db.task_links
    if not words:
        return set()
    hits: set[str] | None = None
    for w in words:
        like = f"%{w}%"
        found = {r.id for r in conn.execute(select(T.c.id).where(T.c.organization_id == org,
                                                                 or_(T.c.title.ilike(like), T.c.notes.ilike(like))))}
        found |= {r.task_id for r in conn.execute(select(M.c.task_id).where(M.c.organization_id == org, M.c.list_name.ilike(like)))}
        found |= {r.task_id for r in conn.execute(select(I.c.task_id).where(I.c.organization_id == org, I.c.text.ilike(like)))}
        found |= {r.task_id for r in conn.execute(select(L.c.task_id).where(L.c.organization_id == org,
                                                                            or_(L.c.title.ilike(like), L.c.url.ilike(like))))}
        hits = found if hits is None else hits & found
        if not hits:
            return set()
    return hits or set()


# ---------------------------------------------------------------- V6.91 undo

def undo_done(p: Principal, tid: str) -> dict:
    """Take back "done": the task opens again, and the next occurrence a repeating task queued is removed if nothing has
    happened to it yet (no run, not edited). A run that was cancelled when you marked it done stays cancelled."""
    from . import mytasks, taskplus
    T = db.my_tasks
    removed = None
    with transaction() as conn:
        r = _task(conn, p.organization_id, tid)
        if r.status != "DONE":
            raise PlusError("only a finished task can be taken back", 409)
        nxt = conn.execute(select(T).where(T.c.repeat_of == tid, T.c.organization_id == p.organization_id)).first()
        if nxt is not None and nxt.status == "OPEN" and not nxt.mission_id and nxt.updated_at == nxt.created_at \
                and _untouched(conn, p.organization_id, nxt.id):
            taskplus.forget(conn, nxt.id)
            conn.execute(delete(T).where(T.c.id == nxt.id))
            removed = nxt.id
        conn.execute(update(T).where(T.c.id == tid).values(status="OPEN", done_at=None, updated_at=_now().isoformat()))
        emit(conn, "my_task.updated", org_id=p.organization_id,
             payload={"task_id": tid, "title": r.title, "status": "OPEN", "undo": "done", "removed_next": removed})
    with db.get_engine().connect() as conn:
        return {"task": mytasks.get(conn, p.organization_id, tid), "removed_next": removed}


def _untouched(conn: Connection, org: str, tid: str) -> bool:
    """Nothing has been done to a queued repeat: no change of any kind (each one leaves an event), no focus time."""
    E = db.events
    changed = conn.execute(select(E.c.id).where(E.c.organization_id == org, E.c.event_type.like("my_task.%"),
                                                E.c.payload["task_id"].as_string() == tid).limit(1)).first()
    focused = conn.execute(select(db.focus_sessions.c.id).where(db.focus_sessions.c.task_id == tid).limit(1)).first()
    return changed is None and focused is None


# ---------------------------------------------------------------- V6.92 history

_FIELD_WORDS = {"title": "title", "notes": "notes", "due_at": "due date", "priority": "priority", "kind": "kind of work",
                "repeat": "repeat", "budget_usd": "budget", "repository_id": "repository", "list_name": "list",
                "estimate_minutes": "time estimate", "blocked_by": "waiting on", "snoozed_until": "snooze",
                "checklist": "checklist", "links": "links"}


def _describe(e) -> str | None:
    p = e.payload or {}
    t = e.event_type
    if t == "my_task.created":
        return "Added" + (" (the next one of a repeating task)" if p.get("repeat_of") else "")
    if t == "my_task.completed":
        return "Marked done" + (", and the next one was queued" if p.get("next_task_id") else "")
    if t == "my_task.started":
        return "You asked the agents to do it"
    if t == "my_task.rated":
        return "You rated the result " + ("useful" if (p.get("rating") or 0) > 0 else "not useful")
    if t == "my_task.updated":
        if p.get("undo") == "done":
            return "You took back \"done\""
        if p.get("status") == "OPEN":
            return "Reopened"
        if p.get("status") == "DROPPED":
            return "Dropped"
        fields = [_FIELD_WORDS.get(f, f.replace("_", " ")) for f in p.get("fields") or []]
        if "snooze" in fields:
            return "Snoozed" if p.get("snoozed_until") else "Snooze changed"
        return "Changed the " + ", ".join(fields) if fields else "Changed"
    return None


def history(conn: Connection, org: str, tid: str, limit: int = 100) -> list[dict]:
    """What happened to one task, newest first: its own events plus how its agent runs ended."""
    r = _task(conn, org, tid)
    E = db.events
    rows = conn.execute(select(E.c.event_type, E.c.payload, E.c.occurred_at, E.c.mission_id)
                        .where(E.c.organization_id == org, E.c.event_type.like("my_task.%"),
                               E.c.payload["task_id"].as_string() == tid)
                        .order_by(E.c.sequence.desc()).limit(limit)).fetchall()
    out = [{"at": e.occurred_at, "kind": e.event_type.split(".", 1)[1], "text": text, "mission_id": e.mission_id}
           for e in rows if (text := _describe(e))]
    if not any(x["kind"] == "created" for x in out):
        out.append({"at": r.created_at, "kind": "created", "text": "Added", "mission_id": None})
    started = [x["mission_id"] for x in out if x["kind"] == "started" and x["mission_id"]]
    if started:
        M = db.missions
        for m in conn.execute(select(M.c.id, M.c.status, M.c.updated_at, M.c.execution_mode).where(M.c.id.in_(started))):
            if m.status in ("COMPLETED", "FAILED", "CANCELLED", "REJECTED"):
                word = {"COMPLETED": "The agents finished", "FAILED": "The agents' run failed",
                        "CANCELLED": "The run was cancelled", "REJECTED": "The run was turned down"}[m.status]
                out.append({"at": m.updated_at, "kind": "run_" + m.status.lower(), "mission_id": m.id,
                            "text": word + (" (a simulation)" if m.execution_mode == "simulation" else "")})
    out.sort(key=lambda x: x["at"] or "", reverse=True)
    return out[:limit]


# ---------------------------------------------------------------- V6.93 links

def clean_url(url: str) -> str:
    u = (url or "").strip()
    bad = PlusError("a link starts with http:// or https:// and has a web address")
    if not 10 <= len(u) <= 2048 or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in u):
        raise bad
    try:
        parts = urlsplit(u)
        host = parts.hostname
    except ValueError as exc:
        raise bad from exc
    if parts.scheme.lower() not in ("http", "https") or not host:
        raise bad
    if "@" in parts.netloc:
        raise PlusError("a link can't carry a user name or password")
    return parts.scheme.lower() + u[len(parts.scheme):]  # "HTTPS://…" is stored as "https://…"


def links_for(conn: Connection, org: str, ids: list[str]) -> dict[str, list[dict]]:
    if not ids:
        return {}
    L = db.task_links
    out: dict[str, list[dict]] = {}
    for r in conn.execute(select(L.c.id, L.c.task_id, L.c.url, L.c.title, L.c.created_at)
                          .where(L.c.organization_id == org, L.c.task_id.in_(ids)).order_by(L.c.created_at)):
        out.setdefault(r.task_id, []).append({"id": r.id, "url": r.url, "title": r.title, "host": urlsplit(r.url).hostname or ""})
    return out


def add_link(p: Principal, tid: str, url: str, title: str | None = None, conn: Connection | None = None) -> list[dict]:
    u = clean_url(url)
    label = " ".join((title or "").split())[:120]

    def write(c: Connection) -> None:
        _task(c, p.organization_id, tid)
        L = db.task_links
        have = c.execute(select(L.c.url).where(L.c.task_id == tid)).scalars().all()
        if u in have:
            return
        if len(have) >= MAX_LINKS:
            raise PlusError(f"a task holds up to {MAX_LINKS} links")
        c.execute(insert(L).values(id=db.new_id(), task_id=tid, organization_id=p.organization_id, url=u, title=label,
                                   created_by=p.user_id, created_at=_now().isoformat()))
        emit(c, "my_task.updated", org_id=p.organization_id, payload={"task_id": tid, "fields": ["links"]})

    if conn is not None:
        write(conn)
        return links_for(conn, p.organization_id, [tid]).get(tid, [])
    with transaction() as c:
        write(c)
    with db.get_engine().connect() as c:
        return links_for(c, p.organization_id, [tid]).get(tid, [])


def remove_link(p: Principal, tid: str, lid: str) -> list[dict]:
    from .mytasks import _canonical
    L = db.task_links
    with transaction() as conn:
        _task(conn, p.organization_id, tid)
        gone = _canonical(lid) and conn.execute(delete(L).where(L.c.id == lid, L.c.task_id == tid,
                                                                L.c.organization_id == p.organization_id)).rowcount
        if not gone:
            raise PlusError("link not found", 404)
        emit(conn, "my_task.updated", org_id=p.organization_id, payload={"task_id": tid, "fields": ["links"]})
    with db.get_engine().connect() as conn:
        return links_for(conn, p.organization_id, [tid]).get(tid, [])


def take_urls(text: str) -> tuple[str, list[str]]:
    """Quick capture: web addresses typed into a task become its links and leave the title."""
    urls = []
    for m in URL_RX.finditer(text or ""):
        try:
            urls.append(clean_url(m.group(0).rstrip(".,;:)!?")))
        except PlusError:
            continue  # not a usable address: it's dropped from the title and not kept as a link
    rest = URL_RX.sub(" ", text or "")
    return " ".join(rest.split()), urls[:MAX_LINKS]


# ---------------------------------------------------------------- V6.95 habits (streaks on repeating tasks)

def _series_rows(conn: Connection, org: str) -> dict[str, dict]:
    """Every task in a repeating series, read once: id → its few fields."""
    T = db.my_tasks
    rows = conn.execute(select(T.c.id, T.c.repeat_of, T.c.status, T.c.due_at, T.c.done_at)
                        .where(T.c.organization_id == org, or_(T.c.repeat != "none", T.c.repeat_of.is_not(None))))
    return {r.id: dict(r._mapping) for r in rows}


def _walk(rows: dict[str, dict], tid: str) -> list[dict]:
    out, seen, cur = [], set(), rows.get(tid)
    while cur and cur["id"] not in seen and len(out) < 400:
        out.append(cur)
        seen.add(cur["id"])
        cur = rows.get(cur["repeat_of"]) if cur["repeat_of"] else None
    return out


def chain_rows(conn: Connection, org: str, tid: str) -> list[dict]:
    """The occurrences of a repeating task, newest first, following repeat_of back (one query, at most 400)."""
    return _walk(_series_rows(conn, org), tid)


def _outcome(r: dict, zone) -> str:
    """done (on or before its due day), late (done after its due day), missed (dropped), open."""
    if r["status"] == "DONE":
        if r["due_at"] and r["done_at"] and datetime.fromisoformat(r["done_at"]).astimezone(zone).date() > \
                datetime.fromisoformat(r["due_at"]).astimezone(zone).date():
            return "late"
        return "done"
    if r["status"] == "DROPPED":
        return "missed"
    return "open"


def streak_of(outcomes: list[str]) -> tuple[int, int]:
    """(current, best) runs of on-time "done", oldest → newest; the open occurrence at the end doesn't break a streak."""
    best = cur = 0
    for o in outcomes:
        if o == "open":
            continue
        cur = cur + 1 if o == "done" else 0
        best = max(best, cur)
    return cur, best


def habits(conn: Connection, org: str, tz: str | None = "UTC") -> list[dict]:
    """Every open repeating task with its streak and its last 14 occurrences."""
    from .capture import repeat_label
    T = db.my_tasks
    zone = _zone(tz)
    heads = conn.execute(select(T).where(T.c.organization_id == org, T.c.status == "OPEN", T.c.repeat != "none")
                         .order_by(T.c.due_at)).fetchall()
    rows = _series_rows(conn, org)
    out = []
    for h in heads[:100]:
        chain = list(reversed(_walk(rows, h.id)))  # oldest first
        outcomes = [_outcome(r, zone) for r in chain]
        cur, best = streak_of(outcomes)
        closed = [o for o in outcomes if o != "open"]
        out.append({"task_id": h.id, "title": h.title, "repeat": h.repeat, "repeat_label": repeat_label(h.repeat),
                    "due_at": h.due_at, "current": cur, "best": best, "times": len(closed),
                    "on_time_rate": round(closed.count("done") / len(closed), 2) if closed else None,
                    "recent": [{"due_at": r["due_at"], "outcome": o} for r, o in list(zip(chain, outcomes))[-14:]]})
    out.sort(key=lambda x: (-x["current"], x["title"].lower()))
    return out


def streak_for(conn: Connection, org: str, r, tz: str | None = "UTC") -> dict | None:
    if r.repeat == "none" and not r.repeat_of:
        return None
    zone = _zone(tz)
    outcomes = [_outcome(x, zone) for x in reversed(chain_rows(conn, org, r.id))]
    cur, best = streak_of(outcomes)
    return {"current": cur, "best": best, "times": sum(1 for o in outcomes if o != "open")}


# ---------------------------------------------------------------- V6.96 the morning digest

def digest(conn: Connection, org: str, tz: str | None = "UTC", day: str = "today", now: datetime | None = None) -> dict:
    """A short summary of a day ("today", "tomorrow", or "2"–"6" days ahead) for a morning notification: what's due by
    the end of that day and still ahead of now, what's already overdue, what needs you, and how much work is planned.
    Counts only; it changes nothing."""
    from . import mytasks, taskplus
    zone = _zone(tz)
    now = now or _now()
    local = now.astimezone(zone)
    ahead = {"today": 0, "tomorrow": 1}.get(day, int(day) if str(day).isdigit() else 0)
    date = local.date() + timedelta(days=ahead)
    start = datetime.combine(date, time(0, 0), tzinfo=zone).astimezone(timezone.utc).isoformat()
    end = datetime.combine(date + timedelta(days=1), time(0, 0), tzinfo=zone).astimezone(timezone.utc).isoformat()
    tasks = [t for t in mytasks.listing(conn, org, include_done=False)]
    from_ = max(start, now.isoformat())
    due = [t for t in tasks if t["due_at"] and from_ <= t["due_at"] < end and t["stage"] not in ("snoozed", "waiting")]
    overdue = [t for t in tasks if t["due_at"] and t["due_at"] < now.isoformat() and t["stage"] not in ("snoozed", "blocked", "waiting")]
    needs = [t for t in tasks if t["stage"] in ("needs_you", "review")]
    planned = sum(taskplus.minutes_of(t) for t in due)
    bits = []
    if due:
        bits.append(f"{len(due)} due")
    if overdue:
        bits.append(f"{len(overdue)} overdue")
    if needs:
        bits.append(f"{len(needs)} waiting for you")
    when = "Today" if ahead == 0 else "Tomorrow" if ahead == 1 else date.strftime("%A")
    title = f"{when}: " + (", ".join(bits) if bits else "nothing due")
    top = list(dict.fromkeys(t["title"] for t in (needs + overdue + due)))[:3]
    body = ("First up: " + "; ".join(top) + "." if top else "A clear day on your list.") + \
        (f" About {planned // 60}h {planned % 60:02d}m of planned work." if planned >= 60 else
         f" About {planned} minutes of planned work." if planned else "")
    return {"day": date.isoformat(), "title": title, "body": body, "due": len(due), "overdue": len(overdue),
            "needs_you": len(needs), "planned_minutes": planned, "top": top, "as_of": now.isoformat()}
