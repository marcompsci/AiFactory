"""Scheduled missions: "every Monday at 9, run the tests", "every day, research budgeting apps".

A schedule exists only after the owner confirms it (a City proposal or the owner-only API). When one is due, the
scheduler starts the mission through the same functions as a person would (so the emergency stop, charter caps and
approvals all apply), and quiet hours hold it like any other scheduled work. Each run is claimed first (its next
time is moved on in the same step), so a schedule can't fire twice for one slot. Only read-only kinds can be
scheduled: test runs and market research.

V6.19 adds "every weekday" (Monday to Friday), running a schedule now, and skipping its next run. V6.20: a schedule
that fails three times in a row pauses itself and waits in the owner's inbox (an emergency-stop hold isn't a failure).
V6.24: before each run the creator's role at their latest sign-in is checked; a creator who is no longer an owner
pauses the schedule at once. V6.28: so does a creator who hasn't signed in as an owner for 30 days.
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
MAX_FAILURES = 3  # failed runs in a row before a schedule pauses itself
CADENCES = ("daily", "weekly", "weekdays")


class ScheduleError(ValueError):
    pass


def next_run(cadence: str, weekday: int | None, hour: int, minute: int, tz: str, after: datetime) -> datetime:
    """The first slot strictly after `after`, in UTC."""
    z = ZoneInfo(tz)
    local = after.astimezone(z)
    cand = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    for _ in range(9):
        if cand > local and (cadence == "daily" or (cadence == "weekdays" and cand.weekday() < 5)
                             or (cadence == "weekly" and cand.weekday() == weekday)):
            return cand.astimezone(timezone.utc)
        cand = (cand + timedelta(days=1)).replace(hour=hour, minute=minute)
    raise ScheduleError("couldn't work out the next run")


def describe(s: dict) -> str:
    when = ("every day" if s["cadence"] == "daily" else "every weekday" if s["cadence"] == "weekdays"
            else f"every {DAYS[s['weekday']].capitalize()}")
    return f"{when} at {s['hour']:02d}:{s['minute']:02d} ({s['tz']})"


def validate(kind: str, params: dict, cadence: str, weekday: int | None, hour: int, minute: int, tz: str) -> None:
    if kind not in KINDS:
        raise ScheduleError("only test runs and market research can be scheduled")
    if cadence not in CADENCES or (cadence == "weekly" and weekday not in range(7)):
        raise ScheduleError("a schedule is daily, every weekday, or weekly on a named day")
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ScheduleError("that time doesn't exist")
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ScheduleError(f"unknown time zone {tz}") from exc
    if kind == "market_research":
        from pydantic import ValidationError

        from services.api.v4 import ResearchIn
        try:
            ResearchIn(**params)  # the same check every run will face, so a bad schedule is refused now, not on each run
        except (ValidationError, TypeError) as exc:
            raise ScheduleError("research needs a valid topic and source") from exc


def create(conn: Connection, *, org_id: str, user_id: str, kind: str, params: dict, cadence: str, weekday: int | None,
           hour: int, minute: int, tz: str, title: str) -> dict:
    validate(kind, params, cadence, weekday, hour, minute, tz)
    n = len(conn.execute(select(db.mission_schedules.c.id).where(db.mission_schedules.c.organization_id == org_id)).fetchall())
    if n >= MAX_SCHEDULES:
        raise ScheduleError(f"you already have {MAX_SCHEDULES} schedules")
    sid = db.new_id()
    nxt = next_run(cadence, weekday, hour, minute, tz, datetime.now(timezone.utc)).isoformat()
    conn.execute(insert(db.mission_schedules).values(id=sid, organization_id=org_id, kind=kind, params=params, title=title[:160],
                                                     cadence=cadence, weekday=weekday if cadence == "weekly" else None, hour=hour, minute=minute, tz=tz,
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
    h = conn.execute(select(db.schedule_health.c.failures, db.schedule_health.c.paused_reason, db.schedule_health.c.paused_at)
                     .where(db.schedule_health.c.schedule_id == sid)).first()
    d["failures"] = h.failures if h else 0
    d["paused_reason"] = h.paused_reason if h else None
    d["paused_at"] = h.paused_at if h else None
    d["budget_usd"] = conn.execute(select(db.schedule_budgets.c.budget_usd).where(db.schedule_budgets.c.schedule_id == sid)).scalar()
    d["cost"] = cost(conn, sid, d["cadence"])
    return d


RUNS_PER_MONTH = {"daily": 30.4, "weekdays": 21.7, "weekly": 4.35}
COST_SAMPLE = 10


def cost(conn: Connection, sid: str, cadence: str) -> dict:
    """Estimated AI spend per run (average of the last COST_SAMPLE finished runs) and a monthly
    projection at this cadence. Estimates from the gateway's usage records, not bills."""
    from sqlalchemy import func
    R, U = db.schedule_runs, db.usage_records
    M = db.missions
    mids = [r.mission_id for r in conn.execute(select(R.c.mission_id).join(M, M.c.id == R.c.mission_id)
                                               .where(R.c.schedule_id == sid, M.c.status.in_(["COMPLETED", "FAILED", "CANCELLED"]))
                                               .order_by(R.c.started_at.desc()).limit(COST_SAMPLE)).fetchall()]  # finished runs only
    if not mids:
        return {"runs_counted": 0, "per_run_usd": None, "monthly_usd": None, "is_estimate": True}
    total = float(conn.execute(select(func.coalesce(func.sum(U.c.estimated_cost_usd), 0.0)).where(U.c.mission_id.in_(mids))).scalar() or 0)
    per = total / len(mids)
    return {"runs_counted": len(mids), "per_run_usd": round(per, 4), "monthly_usd": round(per * RUNS_PER_MONTH.get(cadence, 30.4), 2),
            "is_estimate": True}


def set_budget(conn: Connection, org_id: str, sid: str, budget: float | None, user_id: str) -> dict:
    """Each run's mission budget (None: the default). The charter's mission cap still applies, so a budget above it is refused."""
    from . import charter
    if get(conn, org_id, sid) is None:
        raise ScheduleError("schedule not found")
    B = db.schedule_budgets
    conn.execute(delete(B).where(B.c.schedule_id == sid))
    if budget is not None:
        try:
            charter.check_mission_budget(conn, org_id, budget)
        except charter.CharterError as exc:
            raise ScheduleError(str(exc)) from exc
        conn.execute(insert(B).values(schedule_id=sid, organization_id=org_id, budget_usd=round(float(budget), 2), set_by=user_id))
    emit(conn, "schedule.changed", org_id=org_id, payload={"schedule_id": sid, "budget_usd": budget})
    return get(conn, org_id, sid)


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
    if enabled:  # the owner looked at it and turned it back on: start counting failures afresh
        conn.execute(delete(db.schedule_health).where(db.schedule_health.c.schedule_id == sid))
    emit(conn, "schedule.changed", org_id=org_id, payload={"schedule_id": sid, "enabled": enabled})
    return get(conn, org_id, sid)


def remove(conn: Connection, org_id: str, sid: str) -> None:
    if get(conn, org_id, sid) is None:
        raise ScheduleError("schedule not found")
    conn.execute(delete(db.schedule_health).where(db.schedule_health.c.schedule_id == sid))
    conn.execute(delete(db.schedule_budgets).where(db.schedule_budgets.c.schedule_id == sid))
    conn.execute(delete(db.schedule_runs).where(db.schedule_runs.c.schedule_id == sid))
    conn.execute(delete(db.mission_schedules).where(db.mission_schedules.c.id == sid))
    emit(conn, "schedule.changed", org_id=org_id, payload={"schedule_id": sid, "deleted": True})


def claim_due(conn: Connection, now: datetime | None = None) -> list[dict]:
    """Due, enabled schedules, each claimed by moving its next run on (so one slot runs once). A schedule whose
    organization is in quiet hours waits (it isn't claimed) until they end."""
    from . import charter
    now = now or datetime.now(timezone.utc)
    out = []
    quiet: dict[str, bool] = {}
    for r in conn.execute(select(db.mission_schedules).where(db.mission_schedules.c.enabled == 1,
                                                             db.mission_schedules.c.next_run_at <= now.isoformat())).fetchall():
        if r.organization_id not in quiet:
            quiet[r.organization_id] = charter.quiet_now(charter.rules(conn, r.organization_id), now)
        if quiet[r.organization_id]:
            continue
        nxt = next_run(r.cadence, r.weekday, r.hour, r.minute, r.tz, now).isoformat()
        res = conn.execute(update(db.mission_schedules).where(db.mission_schedules.c.id == r.id,
                                                              db.mission_schedules.c.next_run_at == r.next_run_at)
                           .values(next_run_at=nxt))
        if (res.rowcount or 0) == 1:
            out.append({**dict(r._mapping), "slot": r.next_run_at})
    return out


HOLD_ERRORS = ("emergency stop is engaged",)  # a deliberate hold, not the schedule failing


def record_run(conn: Connection, sid: str, *, mission_id: str | None, error: str | None, pause_now: str | None = None) -> None:
    """Record one run. Failures in a row are counted; at MAX_FAILURES (or at once with `pause_now`, for a reason retrying
    can't fix) the schedule pauses itself and waits in the owner's inbox."""
    s = conn.execute(select(db.mission_schedules.c.runs, db.mission_schedules.c.organization_id, db.mission_schedules.c.title)
                     .where(db.mission_schedules.c.id == sid)).first()
    if s is None:
        return
    conn.execute(update(db.mission_schedules).where(db.mission_schedules.c.id == sid).values(
        runs=(s.runs or 0) + (1 if mission_id else 0), last_run_at=db.utcnow(), last_mission_id=mission_id, last_error=error))
    if mission_id and not conn.execute(select(db.schedule_runs.c.id).where(db.schedule_runs.c.schedule_id == sid,
                                                                           db.schedule_runs.c.mission_id == mission_id)).first():
        conn.execute(insert(db.schedule_runs).values(id=db.new_id(), organization_id=s.organization_id, schedule_id=sid, mission_id=mission_id))
    emit(conn, "schedule.ran", mission_id=mission_id, org_id=s.organization_id,
         payload={"schedule_id": sid, "title": s.title, "mission_id": mission_id, "error": error})
    H = db.schedule_health
    h = conn.execute(select(H.c.failures).where(H.c.schedule_id == sid)).first()
    if error is None or any(x in error for x in HOLD_ERRORS):
        if error is None and h and h.failures:
            conn.execute(update(H).where(H.c.schedule_id == sid).values(failures=0, updated_at=db.utcnow()))
        if not pause_now:
            return
    failures = (h.failures if h else 0) + (0 if error is None else 1)
    reason = pause_now or (f"paused itself after {failures} failed runs in a row (last: {error})" if failures >= MAX_FAILURES else None)
    values = {"failures": failures, "updated_at": db.utcnow()}
    if reason:
        values.update(paused_reason=reason[:400], paused_at=db.utcnow())
    if h:
        conn.execute(update(H).where(H.c.schedule_id == sid).values(**values))
    else:
        conn.execute(insert(H).values(schedule_id=sid, organization_id=s.organization_id, **values))
    if reason:
        conn.execute(update(db.mission_schedules).where(db.mission_schedules.c.id == sid).values(enabled=0))
        emit(conn, "schedule.auto_paused", org_id=s.organization_id, payload={"schedule_id": sid, "title": s.title, "reason": reason[:400]})


def skip_next(conn: Connection, org_id: str, sid: str) -> dict:
    """Skip one run: the next run moves to the slot after it."""
    s = get(conn, org_id, sid)
    if s is None:
        raise ScheduleError("schedule not found")
    if not s["enabled"]:
        raise ScheduleError("the schedule is paused, so there's no next run to skip")
    after = datetime.fromisoformat(s["next_run_at"])
    nxt = next_run(s["cadence"], s["weekday"], s["hour"], s["minute"], s["tz"], after).isoformat()
    n = conn.execute(update(db.mission_schedules).where(db.mission_schedules.c.id == sid,
                                                        db.mission_schedules.c.next_run_at == s["next_run_at"]).values(next_run_at=nxt)).rowcount
    if not n:
        raise ScheduleError("that run is starting right now, so it can't be skipped")
    emit(conn, "schedule.changed", org_id=org_id, payload={"schedule_id": sid, "skipped": s["next_run_at"], "next_run_at": nxt})
    return get(conn, org_id, sid)


OWNER_FRESH_DAYS = 30  # a creator not seen signing in as an owner for this long can't keep a schedule running


def owner_problem(conn: Connection, s: dict, now: datetime | None = None) -> str | None:
    """Why this schedule shouldn't run in its creator's name, from the V6.24 roster (None when it may):
    - their latest sign-in wasn't as an owner;
    - they haven't signed in for OWNER_FRESH_DAYS (V6.28: a demotion we never saw can't keep it running forever);
    - they've never signed in since the roster began and the schedule is older than OWNER_FRESH_DAYS."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=OWNER_FRESH_DAYS)
    row = conn.execute(select(db.org_members.c.role, db.org_members.c.last_seen)
                       .where(db.org_members.c.organization_id == s["organization_id"],
                              db.org_members.c.user_id == s["created_by"])).first()
    if row is not None:
        if row.role != "owner":
            return "the person who set it up is no longer an owner"
        if _ts(row.last_seen) < cutoff:
            return f"the person who set it up hasn't signed in for {OWNER_FRESH_DAYS} days"
        return None
    if s.get("created_at") and _ts(s["created_at"]) < cutoff:
        return f"no sign-in from the person who set it up in {OWNER_FRESH_DAYS} days, so it can't be confirmed they're still an owner"
    return None


def _ts(v) -> datetime:
    d = v if isinstance(v, datetime) else datetime.fromisoformat(str(v))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def creator_still_owner(conn: Connection, s: dict) -> bool | None:
    """Kept for callers of V6.24: True/False from the roster, None when the creator isn't in it."""
    role = conn.execute(select(db.org_members.c.role).where(db.org_members.c.organization_id == s["organization_id"],
                                                            db.org_members.c.user_id == s["created_by"])).scalar()
    return None if role is None else role == "owner"


def start(s: dict, *, slot_key: str, user_id: str | None = None) -> tuple[str | None, str | None]:
    """Start one run of schedule `s` through the regular functions (emergency stop and charter apply). Returns
    (mission_id, error)."""
    from fastapi import HTTPException

    from services.api import main, v4
    from services.core.auth import Principal
    p = Principal(user_id=user_id or s["created_by"], organization_id=s["organization_id"], role="operator", mode="schedule")
    with db.get_engine().connect() as conn:
        budget = conn.execute(select(db.schedule_budgets.c.budget_usd).where(db.schedule_budgets.c.schedule_id == s["id"])).scalar()
    try:
        if s["kind"] == "run_tests":
            m = main.create_mission(main.MissionIn(prompt=s["params"]["prompt"], kind="run_tests", title=s["title"][:120], budget_usd=budget,
                                                   idempotency_key=f"schedule:{s['id']}:{slot_key}"[:100]), p)
            return m["id"], None
        return v4.start_research(v4.ResearchIn(**{**s["params"], "budget_usd": budget}), p)["mission_id"], None
    except HTTPException as exc:
        return None, str(exc.detail)[:300]
    except Exception as exc:  # recorded on the schedule; the next slot tries again
        import logging
        logging.getLogger("aiciv.schedules").exception("schedule %s failed", s["id"])
        return None, str(exc)[:300]


# ---------------------------------------------------------------- reading "every Monday at 9am …" in the City

_EVERY = re.compile(r"^(?:please\s+|can you\s+)?every\s+(?P<day>day|morning|weekdays?|work\s*days?|"
                    + "|".join(DAYS) + r"|week)(?:\s+at\s+(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)?)?[,\s]+(?P<rest>.+)$")


def parse(text: str) -> dict | None:
    """{cadence, weekday, hour, minute, rest} from "every <day> [at <time>] <request>", or None."""
    m = _EVERY.match(text.strip().lower())
    if not m:
        return None
    day = m.group("day")
    if day == "weekday" or day.startswith("work"):
        cadence, weekday = "weekdays", None
    elif day in ("day", "morning"):
        cadence, weekday = "daily", None
    else:
        cadence, weekday = "weekly", 0 if day == "week" else DAYS.index(day)
    hour = int(m.group("h") or 9)
    minute = int(m.group("m") or 0)
    if m.group("ap") == "pm" and hour < 12:
        hour += 12
    if m.group("ap") == "am" and hour == 12:
        hour = 0
    return {"cadence": cadence, "weekday": weekday, "hour": hour, "minute": minute, "rest": m.group("rest").strip()}

