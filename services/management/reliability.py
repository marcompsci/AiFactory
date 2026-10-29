"""Reliability: catching loops, naming failures, learning from runs, and checking the mission's objective.

Where the ideas come from:
- Step repetition is the most common multi-agent failure (17% of 1,642 traces in MAST, Cemri et al., "Why Do
  Multi-Agent LLM Systems Fail?", 2025); Magentic-One stops an inner loop after a small stall count and replans.
  Here: a task whose last two runs failed the same way stops, and the General Manager is told; the supervisor also
  flags a run that keeps making the same tool call.
- MAST says to label failures by type so the fix matches the failure. `failure_labels` sorts this town's failures
  into MAST's categories with plain rules (method "rules"; nothing is model-judged).
- Generative Agents (Park et al., 2023) reflect on what happened; their known flaw is reflections that invent
  things. Lessons here are written by rules from real task runs and each one cites the run it came from. They are
  stored as `hypothesis` memory (never `verified`) and given to the agent as hints, not facts.
- Verifiers often check that something ran, not that the goal was met (MAST FC3). `check_objective` checks, when a
  mission completes, that every step finished, produced what its plan said it would, and passed its validation.
"""
from __future__ import annotations

from services.core.text import plural

import json
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import insert, select
from sqlalchemy.engine import Connection

from services.core import db
from services.core.events import emit

STALL_LIMIT = 2          # identical failures in a row before the task stops (Magentic-One uses a stall count of about 2)
REPEAT_TOOL_LIMIT = 3    # the same tool with the same arguments this many times in one run is a loop
LOOP_PREFIX = "stopped: the same failure repeated"
VERIFY_PREFIX = "verification failed: "
LESSON_PREFIX = "Lesson: "
LESSON_TTL_DAYS = 90
MAX_ROWS = 2000
NOT_THE_AGENT = ("INFRA", "RES")  # outages and budget pauses are not the agent's reasoning: no loop stop, no lesson


def _norm(err: str | None) -> str:
    """An error without the parts that change between attempts (numbers, ids, paths)."""
    e = (err or "").lower()
    e = re.sub(r"^retrying: ", "", e)
    e = re.sub(r"(/[\w.\-]+)+", "/path", e)
    e = re.sub(r"[0-9a-f]{8,}", "#", e)
    e = re.sub(r"\d+(\.\d+)?", "#", e)
    return re.sub(r"\s+", " ", e).strip()[:300]


def _short(err: str | None) -> str:
    e = re.sub(r"^retrying: ", "", (err or "").strip())
    return (e[:140] + "…") if len(e) > 140 else e


def repeating_failure(conn: Connection, task_id: str) -> str | None:
    """The repeated error, if the task's last STALL_LIMIT runs failed the same way for a reason that is the agent's."""
    runs = conn.execute(select(db.task_runs.c.status, db.task_runs.c.error).where(db.task_runs.c.task_id == task_id)
                        .order_by(db.task_runs.c.attempt.desc()).limit(STALL_LIMIT)).fetchall()
    if len(runs) < STALL_LIMIT or any(r.status != "FAILED" for r in runs):
        return None
    errs = {_norm(r.error) for r in runs}
    if len(errs) != 1 or not next(iter(errs)) or _mode_for(runs[0].error) in NOT_THE_AGENT:
        return None
    return runs[0].error


def repeated_tool_call(conn: Connection, task_id: str) -> tuple[str, int] | None:
    """(tool, count) when the task's current run made the same call with the same arguments REPEAT_TOOL_LIMIT+ times."""
    started = conn.execute(select(db.task_runs.c.started_at).where(db.task_runs.c.task_id == task_id)
                           .order_by(db.task_runs.c.attempt.desc()).limit(1)).scalar()
    q = select(db.tool_executions.c.tool_name, db.tool_executions.c.arguments).where(db.tool_executions.c.task_id == task_id)
    if started:
        q = q.where(db.tool_executions.c.started_at >= started)
    counts: dict[tuple[str, str], int] = {}
    for r in conn.execute(q.limit(MAX_ROWS)).fetchall():
        k = (r.tool_name, json.dumps(r.arguments or {}, sort_keys=True, default=str))
        counts[k] = counts.get(k, 0) + 1
    worst = max(counts.items(), key=lambda kv: kv[1], default=None)
    return (worst[0][0], worst[1]) if worst and worst[1] >= REPEAT_TOOL_LIMIT else None


# ---------------------------------------------------------------- failure labels (MAST)

CATEGORIES = {
    "specification": {"name": "Task & role setup", "fix": "Make the task's instructions, role and stopping point clearer."},
    "misalignment": {"name": "Agents out of step", "fix": "Ask before assuming; keep the plan and the action in sync."},
    "verification": {"name": "Checking the work", "fix": "Check the goal itself, not only that something ran."},
    "resources": {"name": "Budget & limits", "fix": "The owner decides whether to raise a limit."},
    "infrastructure": {"name": "Outside the agent", "fix": "A model, tool or computer problem, not the agent's reasoning."},
    "unclassified": {"name": "Not yet classified", "fix": "Read the run's error to decide."},
}

MODES = {
    "FM-1.1": ("specification", "Didn't meet the task's requirements"),
    "FM-1.2": ("specification", "Went outside its role's permissions"),
    "FM-1.3": ("specification", "Repeated the same step"),
    "FM-1.5": ("specification", "Didn't know when to stop"),
    "FM-2.3": ("misalignment", "Drifted from the approved plan"),
    "FM-2.6": ("misalignment", "Said one thing, produced another"),
    "FM-3.1": ("verification", "Finished before the objective was met"),
    "RES": ("resources", "Hit its budget"),
    "INFRA": ("infrastructure", "Model or tool unavailable"),
    "UNK": ("unclassified", "Failure not matched by any rule"),
}


def _mode_for(error: str | None) -> str:
    e = (error or "").lower().strip()
    e = re.sub(r"^retrying: ", "", e)
    if e.startswith(LOOP_PREFIX):
        under = _mode_for(re.sub(r"^" + re.escape(LOOP_PREFIX) + r"[^:]*:\s*", "", e))
        return under if under in NOT_THE_AGENT else "FM-1.3"
    # QA's verdict first: its text is test output, which can contain any word
    if e.startswith(VERIFY_PREFIX.strip()) or "tests still failing" in e or "re-opened by qa" in e:
        return "FM-1.1"
    if "permission denied" in e or "not permitted" in e or "not allowed" in e or "refusing to edit tests" in e:
        return "FM-1.2"
    if "timed out" in e or "stayed busy" in e or "past 1.5" in e:
        return "FM-1.5"
    if "did not return json" in e or "invalid json" in e:
        return "FM-2.6"
    if "budget" in e or ("cap" in e and "reached" in e):
        return "RES"
    if "model call failed" in e or "provider" in e or "connection" in e or "unavailable" in e:
        return "INFRA"
    return "UNK"


def _task_errors(conn: Connection, *, org_id: str, since: str | None = None, mission_id: str | None = None) -> dict[str, str]:
    """task_id -> the error it last failed with (tasks keep it in their task.failed event, not in a column). One query."""
    q = select(db.events.c.payload).where(db.events.c.organization_id == org_id, db.events.c.event_type == "task.failed")
    if since:
        q = q.where(db.events.c.occurred_at >= since)
    if mission_id:
        q = q.where(db.events.c.mission_id == mission_id)
    out: dict[str, str] = {}
    for e in conn.execute(q.order_by(db.events.c.sequence).limit(MAX_ROWS * 2)).fetchall():
        p = e.payload or {}
        if p.get("task_id"):
            out[p["task_id"]] = p.get("error") or ""
    return out


def _label(mode: str, **kw) -> dict:
    cat, name = MODES[mode]
    return {"mode": mode, "name": name, "category": cat, "category_name": CATEGORIES[cat]["name"], "fix": CATEGORIES[cat]["fix"], **kw}


def failure_labels(conn: Connection, org_id: str, days: int = 30) -> dict:
    """Every failed attempt, stalled task, drifted build and missed objective in the last `days`, each with a MAST label.
    `total` counts failed attempts; `incidents` counts distinct tasks and missed objectives."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    agents = {a.id: a.name for a in conn.execute(select(db.agents.c.id, db.agents.c.name)
                                                 .where(db.agents.c.organization_id == org_id)).fetchall()}
    missions = {m.id: m.title for m in conn.execute(select(db.missions.c.id, db.missions.c.title)
                                                    .where(db.missions.c.organization_id == org_id)).fetchall()}
    labels: list[dict] = []
    seen_tasks: set[str] = set()
    rows = conn.execute(select(db.task_runs.c.id, db.task_runs.c.error, db.task_runs.c.attempt, db.task_runs.c.started_at,
                               db.tasks.c.id.label("task_id"), db.tasks.c.title, db.tasks.c.agent_id, db.tasks.c.mission_id)
                        .join(db.tasks, db.tasks.c.id == db.task_runs.c.task_id)
                        .where(db.task_runs.c.organization_id == org_id, db.task_runs.c.status == "FAILED",
                               db.task_runs.c.started_at >= since)
                        .order_by(db.task_runs.c.started_at.desc()).limit(MAX_ROWS)).fetchall()
    for r in rows:
        seen_tasks.add(r.task_id)
        labels.append(_label(_mode_for(r.error), source=f"task_run:{r.id}", task_id=r.task_id, task=r.title, attempt=r.attempt,
                             agent_id=r.agent_id, agent=agents.get(r.agent_id, ""), mission_id=r.mission_id,
                             mission=missions.get(r.mission_id, ""), evidence=(r.error or "")[:300], at=r.started_at))
    # tasks that failed without a failed run of their own (timeouts, an agent that stayed busy)
    errors = _task_errors(conn, org_id=org_id, since=since)
    for t in conn.execute(select(db.tasks).where(db.tasks.c.organization_id == org_id, db.tasks.c.status == "FAILED",
                                                 db.tasks.c.updated_at >= since).limit(MAX_ROWS)).fetchall():
        if t.id in seen_tasks:
            continue
        err = errors.get(t.id, "")
        labels.append(_label(_mode_for(err), source=f"task:{t.id}", task_id=t.id, task=t.title, attempt=t.attempt, agent_id=t.agent_id,
                             agent=agents.get(t.agent_id, ""), mission_id=t.mission_id, mission=missions.get(t.mission_id, ""),
                             evidence=err[:300], at=t.updated_at))
    for g in conn.execute(select(db.goal_checkpoints).where(db.goal_checkpoints.c.organization_id == org_id,
                                                           db.goal_checkpoints.c.status.in_(["drift", "objective_not_met"]),
                                                           db.goal_checkpoints.c.created_at >= since).limit(MAX_ROWS)).fetchall():
        labels.append(_label("FM-2.3" if g.status == "drift" else "FM-3.1", source=f"goal_checkpoint:{g.id}", task_id=None, task=None,
                             attempt=None, agent_id=None, agent="", mission_id=g.mission_id, mission=missions.get(g.mission_id, ""),
                             evidence="; ".join(g.findings or [])[:300], at=g.created_at))
    labels.sort(key=lambda l: l["at"] or "", reverse=True)
    by_cat: dict[str, int] = {}
    by_mode: dict[str, int] = {}
    by_agent: dict[str, dict] = {}
    for l in labels:
        by_cat[l["category"]] = by_cat.get(l["category"], 0) + 1
        by_mode[l["mode"]] = by_mode.get(l["mode"], 0) + 1
        if l["agent_id"]:
            a = by_agent.setdefault(l["agent_id"], {"agent_id": l["agent_id"], "agent": l["agent"], "count": 0, "modes": {}})
            a["count"] += 1
            a["modes"][l["mode"]] = a["modes"].get(l["mode"], 0) + 1
    incidents = len({l["task_id"] or l["source"] for l in labels})
    top = max(by_cat.items(), key=lambda kv: kv[1])[0] if by_cat else None
    return {
        "days": days, "method": "rules", "total": len(labels), "incidents": incidents, "labels": labels[:200],
        "by_category": [{"category": c, "name": CATEGORIES[c]["name"], "count": n, "fix": CATEGORIES[c]["fix"]}
                        for c, n in sorted(by_cat.items(), key=lambda kv: -kv[1])],
        "by_mode": [{"mode": m, "name": MODES[m][1], "category": MODES[m][0], "count": n} for m, n in sorted(by_mode.items(), key=lambda kv: -kv[1])],
        "by_agent": sorted(by_agent.values(), key=lambda a: -a["count"]),
        "top_category": top,
        "advice": CATEGORIES[top]["fix"] if top else "No failures in this period.",
        "reference": "MAST taxonomy, Cemri et al. 2025 (arXiv:2503.13657)",
    }


# ---------------------------------------------------------------- objective check

_BY_DECISION = ("rejected by reviewer", "no change to publish")


def check_objective(conn: Connection, mission_id: str) -> dict:
    """At completion: every step finished, produced the outputs its plan promised and passed its validation.
    Steps skipped by a decision (you rejected publishing; there was nothing to publish) make it "partly met"."""
    m = conn.execute(select(db.missions).where(db.missions.c.id == mission_id)).first()
    problems: list[str] = []
    decided: list[str] = []
    checked = 0
    for t in conn.execute(select(db.tasks).where(db.tasks.c.mission_id == mission_id).order_by(db.tasks.c.ordinal)).fetchall():
        out = t.outputs or {}
        if t.status == "SKIPPED":
            reason = out.get("reason") or "skipped"
            (decided if reason in _BY_DECISION else problems).append(f"'{t.title}' was skipped ({reason})")
            continue
        if t.status != "COMPLETED":
            problems.append(f"'{t.title}' ended {t.status.lower()}")
            continue
        checked += 1
        missing = [k for k in (t.expected_outputs or {}) if k not in out]
        if missing:
            problems.append(f"'{t.title}' finished without {', '.join(missing)}")
        v = t.validation or {}
        if v.get("all_tests_pass") and (out.get("failed") or 0) > 0:
            problems.append(f"'{t.title}' finished with {plural(int(out.get('failed') or 0), 'failing test')}")
    if not checked:
        problems.append("No steps finished, so nothing could be checked.")
    status = "objective_not_met" if problems else "objective_partly_met" if decided else "objective_met"
    findings = problems + decided or ["Every step finished and produced what the plan asked for."]
    gid = db.new_id()
    conn.execute(insert(db.goal_checkpoints).values(id=gid, organization_id=m.organization_id, mission_id=mission_id, status=status,
                                                    findings=findings))
    emit(conn, "mission.objective_checked", mission_id=mission_id, execution_mode=m.execution_mode, org_id=m.organization_id,
         payload={"checkpoint_id": gid, "met": status == "objective_met", "status": status, "findings": findings})
    return {"met": status == "objective_met", "status": status, "findings": findings}


def objective_for(conn: Connection, mission_id: str) -> dict | None:
    g = conn.execute(select(db.goal_checkpoints).where(db.goal_checkpoints.c.mission_id == mission_id,
                                                      db.goal_checkpoints.c.status.in_(["objective_met", "objective_partly_met",
                                                                                        "objective_not_met"]))
                     .order_by(db.goal_checkpoints.c.created_at.desc())).first()
    return {"met": g.status == "objective_met", "status": g.status, "findings": g.findings or [], "checked_at": g.created_at} if g else None


# ---------------------------------------------------------------- lessons

def learn_from_mission(conn: Connection, mission_id: str) -> int:
    """Write one cited lesson per task that struggled for reasons of its own in this mission. Returns how many were new."""
    m = conn.execute(select(db.missions).where(db.missions.c.id == mission_id)).first()
    if m is None:
        return 0
    errors = _task_errors(conn, org_id=m.organization_id, mission_id=mission_id)
    written = 0
    for t in conn.execute(select(db.tasks).where(db.tasks.c.mission_id == mission_id)).fetchall():
        runs = conn.execute(select(db.task_runs).where(db.task_runs.c.task_id == t.id).order_by(db.task_runs.c.attempt)).fetchall()
        failed = [r for r in runs if r.status == "FAILED" and _mode_for(r.error) not in NOT_THE_AGENT]
        if not failed:
            continue
        first = failed[0]
        if t.status == "COMPLETED":
            text = (f"{LESSON_PREFIX}on \"{t.title}\" ({t.key}), attempt {first.attempt} failed with \"{_short(first.error)}\"; "
                    f"it passed on attempt {runs[-1].attempt}. Check for that problem before the first try.")
        elif t.status == "FAILED" and errors.get(t.id, "").startswith(LOOP_PREFIX):
            text = (f"{LESSON_PREFIX}on \"{t.title}\" ({t.key}), retrying the same way failed {len(failed)} times with "
                    f"\"{_short(first.error)}\". Change the approach or ask for help instead of retrying.")
        else:
            text = (f"{LESSON_PREFIX}on \"{t.title}\" ({t.key}), {plural(len(failed), 'attempt')} failed with \"{_short(failed[-1].error)}\". "
                    "Flag this early next time.")
        if conn.execute(select(db.memory_entries.c.id).where(db.memory_entries.c.agent_id == t.agent_id,
                                                             db.memory_entries.c.content == text)).first():
            continue
        lid = db.new_id()
        expires = (datetime.now(timezone.utc) + timedelta(days=LESSON_TTL_DAYS)).isoformat()
        conn.execute(insert(db.memory_entries).values(id=lid, organization_id=m.organization_id, scope="agent", trust="hypothesis",
                                                      content=text, source=f"task_run:{first.id}", mission_id=mission_id,
                                                      agent_id=t.agent_id, expires_at=expires))
        emit(conn, "agent.lesson_learned", mission_id=mission_id, agent_id=t.agent_id, execution_mode=m.execution_mode,
             org_id=m.organization_id, payload={"memory_id": lid, "task_id": t.id, "lesson": text, "source": f"task_run:{first.id}"})
        written += 1
    return written


def lessons_for(conn: Connection, agent_id: str, task_key: str | None = None, limit: int = 3) -> list[dict]:
    """The agent's most relevant unexpired lessons: same task kind first, then the newest."""
    now = db.utcnow()
    rows = conn.execute(select(db.memory_entries).where(db.memory_entries.c.agent_id == agent_id, db.memory_entries.c.scope == "agent",
                                                        db.memory_entries.c.content.like(LESSON_PREFIX + "%"))
                        .order_by(db.memory_entries.c.created_at.desc()).limit(50)).fetchall()
    rows = [r for r in rows if not r.expires_at or r.expires_at > now]
    if task_key:
        rows.sort(key=lambda r: f"({task_key})" not in r.content)
    return [{"id": r.id, "lesson": r.content[len(LESSON_PREFIX):], "source": r.source, "trust": r.trust, "mission_id": r.mission_id,
             "created_at": r.created_at} for r in rows[:limit]]


def lessons_prompt(lessons: list[dict]) -> str:
    if not lessons:
        return ""
    lines = "\n".join(f"- {l['lesson']} [{l['source']}]" for l in lessons)
    return ("Lessons from your own earlier runs (written by rules from real task runs, each cites its run; treat them as hints, "
            f"not facts):\n{lines}")
