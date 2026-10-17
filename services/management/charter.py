"""The owner's charter: a short rulebook only the owner amends, recorded amendment by amendment.

Project Sid's agents lived under a constitution they could amend, and behavior followed it (tax payments fell when
the rate was lowered). Here the constitution belongs to the owner, and it can only make the town stricter than the
safety built into the code. The locked rules below are not in the charter at all, so no amendment can touch them.

Rules (all optional; absent means the built-in defaults apply):
- agent_daily_usd: an agent's estimated AI spend per UTC day. Reaching it pauses that agent's mission (circuit breaker).
- mission_budget_cap_usd: the most any one mission may be budgeted; larger budgets are refused or held to the cap.
- quiet_hours: {"start": "HH:MM", "end": "HH:MM", "tz": "Area/City"}: scheduled work (research, finance, App Lab and
  factory check-ins) waits. Missions you start yourself still run; the supervisor and conveyor keep running.
Loosening a rule (raising or removing a cap, changing or removing quiet hours) needs a fresh step-up.
"""
from __future__ import annotations

import re
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection

from services.core import db
from services.core.events import emit

LOCKED = [
    "Publishing code (a pull request) waits for your approval; agents never push to the default branch.",
    "Spending money or buying anything needs your approval with a fresh step-up; no agent spends on its own.",
    "Releases wait for your decision in the Owner's Tower.",
    "Walking away, closing the app or a timeout never counts as approval.",
    "Integrations are read-only; secrets live only in the environment or encrypted storage.",
    "The emergency stop halts all work, whatever the charter says.",
]
QUIET_JOBS = {"pipeline", "finance", "applab", "factories", "schedules"}
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
MAX_USD = 50.0


class CharterError(ValueError):
    pass


def rules(conn: Connection, org_id: str) -> dict:
    row = conn.execute(select(db.charters.c.rules).where(db.charters.c.organization_id == org_id)).first()
    return dict(row.rules or {}) if row else {}


def view(conn: Connection, org_id: str) -> dict:
    row = conn.execute(select(db.charters).where(db.charters.c.organization_id == org_id)).first()
    history = [dict(r._mapping) for r in conn.execute(select(db.charter_amendments).where(db.charter_amendments.c.organization_id == org_id)
                                                     .order_by(db.charter_amendments.c.version.desc()).limit(50)).fetchall()]
    r = dict(row.rules or {}) if row else {}
    return {"rules": r, "version": row.version if row else 0, "updated_at": row.updated_at if row else None, "locked": LOCKED,
            "amendments": history, "quiet_now": quiet_now(r)}


def validate(new: dict) -> dict:
    out: dict = {}
    for k in ("agent_daily_usd", "mission_budget_cap_usd"):
        v = new.get(k)
        if v is None:
            continue
        try:
            v = round(float(v), 2)
        except (TypeError, ValueError) as exc:
            raise CharterError(f"{k} must be a number") from exc
        if not 0.01 <= v <= MAX_USD:
            raise CharterError(f"{k} must be between $0.01 and ${MAX_USD:.0f}")
        out[k] = v
    q = new.get("quiet_hours")
    if q is not None:
        if not isinstance(q, dict) or not HHMM.match(str(q.get("start", ""))) or not HHMM.match(str(q.get("end", ""))):
            raise CharterError("quiet_hours needs start and end as HH:MM")
        if q["start"] == q["end"]:
            raise CharterError("quiet hours must not start and end at the same time")
        tz = str(q.get("tz") or "UTC")
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise CharterError(f"unknown time zone {tz}") from exc
        out["quiet_hours"] = {"start": q["start"], "end": q["end"], "tz": tz}
    unknown = set(new) - {"agent_daily_usd", "mission_budget_cap_usd", "quiet_hours"}
    if unknown:
        raise CharterError(f"not a charter rule: {', '.join(sorted(unknown))}")
    return out


def loosens(old: dict, new: dict) -> list[str]:
    """The rules this change makes less strict."""
    out = []
    for k in ("agent_daily_usd", "mission_budget_cap_usd"):
        if k in old and (k not in new or new[k] > old[k]):
            out.append(k)
    if "quiet_hours" in old and new.get("quiet_hours") != old["quiet_hours"]:
        out.append("quiet_hours")  # a shorter or moved window could let work run when it used to wait
    return out


def amend(conn: Connection, *, org_id: str, user_id: str, new_rules: dict, note: str, step_up_method: str | None) -> dict:
    new = validate(new_rules)
    old = rules(conn, org_id)
    changes = {k: {"from": old.get(k), "to": new.get(k)} for k in set(old) | set(new) if old.get(k) != new.get(k)}
    if not changes:
        return view(conn, org_id)
    loose = loosens(old, new)
    if loose and not step_up_method:
        raise PermissionError(f"loosening {', '.join(loose)} needs a fresh step-up")
    row = conn.execute(select(db.charters.c.version).where(db.charters.c.organization_id == org_id)).first()
    version = (row.version if row else 0) + 1
    if row:
        conn.execute(update(db.charters).where(db.charters.c.organization_id == org_id)
                     .values(rules=new, version=version, updated_by=user_id, updated_at=db.utcnow()))
    else:
        conn.execute(insert(db.charters).values(organization_id=org_id, rules=new, version=version, updated_by=user_id))
    conn.execute(insert(db.charter_amendments).values(id=db.new_id(), organization_id=org_id, version=version, changed_by=user_id,
                                                      changes=changes, note=note[:1000], loosened=int(bool(loose)),
                                                      step_up_method=step_up_method if loose else None))
    emit(conn, "charter.amended", org_id=org_id, payload={"version": version, "changes": changes, "loosened": loose, "note": note[:300]})
    return view(conn, org_id)


# ---------------------------------------------------------------- enforcement

def quiet_now(r: dict, now: datetime | None = None) -> bool:
    q = r.get("quiet_hours")
    if not q:
        return False
    try:
        local = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(q.get("tz") or "UTC")).time()
    except (ZoneInfoNotFoundError, ValueError):
        return False
    start, end = time.fromisoformat(q["start"]), time.fromisoformat(q["end"])
    return start <= local < end if start < end else (local >= start or local < end)  # windows may cross midnight


def job_waits(conn: Connection, job: str, org_id: str) -> bool:
    return job in QUIET_JOBS and quiet_now(rules(conn, org_id))


def agent_spent_today(conn: Connection, agent_id: str) -> float:
    day = datetime.now(timezone.utc).date().isoformat()
    return float(conn.execute(select(func.coalesce(func.sum(db.usage_records.c.estimated_cost_usd), 0.0))
                              .where(db.usage_records.c.agent_id == agent_id, db.usage_records.c.created_at >= day)).scalar() or 0.0)


def budget_violation(conn: Connection, *, org_id: str, agent_id: str, agent_name: str, mission_budget: float,
                     mission_spent: float) -> str | None:
    """The charter rule this spend would break, if any (called from ops.check_budget before every model call)."""
    r = rules(conn, org_id)
    cap = r.get("mission_budget_cap_usd")
    if cap is not None and mission_spent >= min(mission_budget, cap):
        return f"the charter's mission cap ${cap:.2f} reached (estimated)"
    daily = r.get("agent_daily_usd")
    if daily is not None and agent_spent_today(conn, agent_id) >= daily:
        return f"{agent_name}'s daily cap ${daily:.2f} under your charter reached (estimated)"
    return None


def check_mission_budget(conn: Connection, org_id: str, budget_usd: float) -> None:
    cap = rules(conn, org_id).get("mission_budget_cap_usd")
    if cap is not None and budget_usd > cap:
        raise CharterError(f"your charter caps a mission's budget at ${cap:.2f}")
