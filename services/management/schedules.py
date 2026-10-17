"""Scheduled missions: "every Monday at 9, run the tests", "every day, research budgeting apps".

A schedule exists only after the owner confirms it (a City proposal or the owner-only API). When one is due, the
scheduler starts the mission through the same functions as a person would (so the emergency stop, charter caps and
approvals all apply), and quiet hours hold it like any other scheduled work. Each run is claimed first (its next
time is moved on in the same step), so a schedule can't fire twice for one slot. Only read-only kinds can be
scheduled: test runs and market research.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Connection

from services.core import db
from services.core.events import emit

KINDS = {"run_tests", "market_research"}
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MAX_SCHEDULES = 20


class ScheduleError(ValueError):
    pass


def next_run(cadence: str, weekday: int | None, hour: int, minute: int, tz: str, after: datetime) -> datetime:
    """The first slot strictly after `after`, in UTC."""
    z = ZoneInfo(tz)
    local = after.astimezone(z)
    cand = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    for _ in range(9):
        if cand > local and (cadence == "daily" or cand.weekday() == weekday):
            return cand.astimezone(timezone.utc)
        cand = (cand + timedelta(days=1)).replace(hour=hour, minute=minute)
    raise ScheduleError("couldn't work out the next run")


def describe(s: dict) -> str:
    when = "every day" if s["cadence"] == "daily" else f"every {DAYS[s['weekday']].capitalize()}"
    return f"{when} at {s['hour']:02d}:{s['minute']:02d} ({s['tz']})"


def validate(kind: str, params: dict, cadence: str, weekday: int | None, hour: int, minute: int, tz: str) -> None:
    if kind not in KINDS:
        raise ScheduleError("only test runs and market research can be scheduled")
    if cadence not in ("daily", "weekly") or (cadence == "weekly" and weekday not in range(7)):
        raise ScheduleError("a schedule is daily, or weekly on a named day")
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ScheduleError("that time doesn't exist")
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ScheduleError(f"unknown time zone {tz}") from exc
    if kind == "market_research" and not (params.get("query") and params.get("source")):
        raise ScheduleError("research needs a topic and a source")


def create(conn: Connection, *, org_id: str, user_id: str, kind: str, params: dict, cadence: str, weekday: int | None,
           hour: int, minute: int, tz: str, title: str) -> dict:
    validate(kind, params, cadence, weekday, hour, minute, tz)
    n = len(conn.execute(select(db.mission_schedules.c.id).where(db.mission_schedules.c.organization_id == org_id)).fetchall())
    if n >= MAX_SCHEDULES:
        raise ScheduleError(f"you already have {MAX_SCHEDULES} schedules")
    sid = db.new_id()
    nxt = next_run(cadence, weekday, hour, minute, tz, datetime.now(timezone.utc)).isoformat()
    conn.execute(insert(db.mission_schedules).values(id=sid, organization_id=org_id, kind=kind, params=params, title=title[:160],
                                                     cadence=cadence, weekday=weekday, hour=hour, minute=minute, tz=tz,
                                                     next_run_at=nxt, enabled=1, created_by=user_id, runs=0))
    row = get(conn, org_id, sid)
    emit(conn, "schedule.created", org_id=org_id, payload={"schedule_id": sid, "title": row["title"], "when": row["when"]})
    return row


def get(conn: Connection, org_id: str, sid: str) -> dict | None:
    r = conn.execute(select(db.mission_schedules).where(db.mission_schedules.c.id == sid,
                                                        db.mission_schedules.c.organization_id == org_id)).first()
    if r is None:
        return None
    d = dict(r._mapping)
    d["when"] = describe(d)
    return d


def listing(conn: Connection, org_id: str) -> list[dict]:
    rows = conn.execute(select(db.mission_schedules.c.id).where(db.mission_schedules.c.organization_id == org_id)
                        .order_by(db.mission_schedules.c.created_at)).fetchall()
    return [get(conn, org_id, r.id) for r in rows]


def set_enabled(conn: Connection, org_id: str, sid: str, enabled: bool) -> dict:
    s = get(conn, org_id, sid)
    if s is None:
        raise ScheduleError("schedule not found")
    values: dict = {"enabled": int(enabled)}
    if enabled:  # resuming never back-fills missed runs: the next one is the next slot from now
        values["next_run_at"] = next_run(s["cadence"], s["weekday"], s["hour"], s["minute"], s["tz"], datetime.now(timezone.utc)).isoformat()
    conn.execute(update(db.mission_schedules).where(db.mission_schedules.c.id == sid).values(**values))
    emit(conn, "schedule.changed", org_id=org_id, payload={"schedule_id": sid, "enabled": enabled})
    return get(conn, org_id, sid)


def remove(conn: Connection, org_id: str, sid: str) -> None:
    if get(conn, org_id, sid) is None:
        raise ScheduleError("schedule not found")
    conn.execute(delete(db.mission_schedules).where(db.mission_schedules.c.id == sid))
    emit(conn, "schedule.changed", org_id=org_id, payload={"schedule_id": sid, "deleted": True})


def claim_due(conn: Connection, now: datetime | None = None) -> list[dict]:
    """Due, enabled schedules, each claimed by moving its next run on (so one slot runs once)."""
    now = now or datetime.now(timezone.utc)
    out = []
    for r in conn.execute(select(db.mission_schedules).where(db.mission_schedules.c.enabled == 1,
                                                             db.mission_schedules.c.next_run_at <= now.isoformat())).fetchall():
        nxt = next_run(r.cadence, r.weekday, r.hour, r.minute, r.tz, now).isoformat()
        res = conn.execute(update(db.mission_schedules).where(db.mission_schedules.c.id == r.id,
                                                              db.mission_schedules.c.next_run_at == r.next_run_at)
                           .values(next_run_at=nxt))
        if (res.rowcount or 0) == 1:
            out.append({**dict(r._mapping), "slot": r.next_run_at})
    return out


def record_run(conn: Connection, sid: str, *, mission_id: str | None, error: str | None) -> None:
    s = conn.execute(select(db.mission_schedules.c.runs, db.mission_schedules.c.organization_id, db.mission_schedules.c.title)
                     .where(db.mission_schedules.c.id == sid)).first()
    if s is None:
        return
    conn.execute(update(db.mission_schedules).where(db.mission_schedules.c.id == sid).values(
        runs=(s.runs or 0) + (1 if mission_id else 0), last_run_at=db.utcnow(), last_mission_id=mission_id, last_error=error))
    emit(conn, "schedule.ran", mission_id=mission_id, org_id=s.organization_id,
         payload={"schedule_id": sid, "title": s.title, "mission_id": mission_id, "error": error})


# ---------------------------------------------------------------- reading "every Monday at 9am …" in the City

_EVERY = re.compile(r"^(?:please\s+|can you\s+)?every\s+(?P<day>day|morning|weekday|"
                    + "|".join(DAYS) + r"|week)(?:\s+at\s+(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)?)?[,\s]+(?P<rest>.+)$")


def parse(text: str) -> dict | None:
    """{cadence, weekday, hour, minute, rest} from "every <day> [at <time>] <request>", or None."""
    m = _EVERY.match(text.strip().lower())
    if not m:
        return None
    day = m.group("day")
    if day == "weekday":
        return None  # not supported yet; the caller asks the owner to pick a day or every day
    cadence, weekday = ("daily", None) if day in ("day", "morning") else ("weekly", 0 if day == "week" else DAYS.index(day))
    hour = int(m.group("h") or 9)
    minute = int(m.group("m") or 0)
    if m.group("ap") == "pm" and hour < 12:
        hour += 12
    if m.group("ap") == "am" and hour == 12:
        hour = 0
    return {"cadence": cadence, "weekday": weekday, "hour": hour, "minute": minute, "rest": m.group("rest").strip()}
