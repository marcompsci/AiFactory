"""What an agent NPC says when the owner talks to it.

Replies are built from database records only (agent state, tasks, missions, approvals, opportunities, artifacts,
estimated costs), so an NPC never claims work the backend doesn't know about. Requests that would change something
(start research, create a mission, cancel a mission) become a *proposal*: a structured action that runs only when the
owner taps Confirm, through the same API functions and permission checks as the rest of the app.

Understanding is keyword-based on purpose: it is predictable, testable and needs no model. Anything it can't map to a
supported action gets an honest "here's what I can do" instead of a guess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, insert, select
from sqlalchemy.engine import Connection

from services.core import db

PROPOSAL_TTL = timedelta(minutes=15)
ACTIVE_TASK = ("RUNNING", "WAITING_FOR_APPROVAL")
DONE_MISSION = ("COMPLETED", "FAILED", "CANCELLED")

# What each NPC in the playable slice can do. Anyone else can still report their own status.
MANAGERS = {"general_manager", "commander"}
RESEARCHERS = {"researcher", "research_apps", "research_marketplaces"}
BUILDERS = {"developer", "architect"}

STATE_PHRASE = {
    "IDLE": "free right now",
    "ASSIGNED": "just picked up a task",
    "PLANNING": "planning my next step",
    "EXECUTING": "working on a task",
    "WAITING_FOR_TOOL": "waiting on a tool to finish",
    "WAITING_FOR_AGENT": "waiting on a teammate",
    "WAITING_FOR_APPROVAL": "waiting for your approval",
    "REVIEWING": "reviewing work",
    "COMPLETED": "just finished a task",
    "FAILED": "stuck: my last task failed",
    "CANCELLED": "stopped: my task was cancelled",
}

DISTRICT_NAME = {
    "nexus-spire": "Nexus Spire", "code-forge": "Code Forge", "sentinel-citadel": "Sentinel Citadel",
    "vision-quarter": "Creative Studio", "data-observatory": "Research Observatory", "memory-vault": "Memory Vault",
    "owners-tower": "Owner's Tower", "central-bank": "AI Central Bank", "claude-code-factory": "Claude Code Factory",
    "github-factory": "GitHub Factory", "codex-factory": "Codex Factory",
}


@dataclass
class Reply:
    text: str
    proposal: dict | None = None
    suggestions: list[str] = field(default_factory=list)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _has(text: str, *words: str) -> bool:
    return any(re.search(rf"\b{w}", text) for w in words)


def _mode_note(mode: str | None) -> str:
    return " (simulation: no AI model is connected, so that run is a rehearsal, not real AI work)" if mode == "simulation" else ""


def _intro(agent) -> Reply:
    can = ["tell you what I'm working on"]
    sugg = ["What are you working on?"]
    if agent.key in MANAGERS:
        can += ["show what needs your approval", "recommend opportunities", "start research or a software change"]
        sugg += ["What happened today?", "What needs my approval?", "Any recommendations?"]
        can.insert(1, "give you the daily brief")
    if agent.key in RESEARCHERS:
        can += ["research a product idea on the App Store charts, Etsy or Depop", "share my findings"]
        sugg += ["Research budgeting apps", "Show me your findings"]
    if agent.key in TESTERS:
        can += ["run the test suite and report the results"]
        sugg += ["Run the tests"]
    if agent.key in BANKERS:
        can += ["tell you how spending is going and where it's heading"]
        sugg += ["How's spending?"]
    if agent.key in BUILDERS:
        can += ["take on a software change to the connected repository", "show what I've produced"]
        sugg += ["Fix the failing test", "Show me your artifacts"]
    can.append("cancel a mission that's running")
    return Reply(f"Hi, I'm {agent.name}, {agent.role}. I can {', '.join(can[:-1])} and {can[-1]}.", suggestions=sugg[:4])


def _status(conn: Connection, agent) -> Reply:
    state = agent.execution_state or "IDLE"
    lines = [f"I'm {STATE_PHRASE.get(state, state.lower())}."]
    pos = conn.execute(select(db.agent_positions.c.district).where(db.agent_positions.c.agent_id == agent.id)).scalar()
    if pos and pos != agent.home_district:
        lines.append(f"I'm over at the {DISTRICT_NAME.get(pos, pos)} right now.")
    active = conn.execute(
        select(db.tasks.c.title, db.tasks.c.status, db.missions.c.title.label("mission"), db.missions.c.execution_mode)
        .join(db.missions, db.missions.c.id == db.tasks.c.mission_id)
        .where(db.tasks.c.agent_id == agent.id, db.tasks.c.status.in_(ACTIVE_TASK))
        .order_by(db.tasks.c.updated_at.desc()).limit(2)).all()
    for t in active:
        lines.append(f"Task: \"{t.title}\" for \"{t.mission}\" ({t.status.lower().replace('_', ' ')}){_mode_note(t.execution_mode)}.")
    if not active:
        last = conn.execute(
            select(db.tasks.c.title, db.tasks.c.status, db.tasks.c.updated_at, db.missions.c.title.label("mission"))
            .join(db.missions, db.missions.c.id == db.tasks.c.mission_id)
            .where(db.tasks.c.agent_id == agent.id, db.tasks.c.status.in_(("COMPLETED", "FAILED")))
            .order_by(db.tasks.c.updated_at.desc()).limit(1)).first()
        lines.append("No task is assigned to me." if not last else
                     f"My last task, \"{last.title}\" for \"{last.mission}\", {'finished' if last.status == 'COMPLETED' else 'failed'}.")
    return Reply(" ".join(lines), suggestions=["Show everything in progress", "Show me your artifacts"])


def _missions(conn: Connection, org: str) -> Reply:
    rows = conn.execute(select(db.missions.c.title, db.missions.c.status, db.missions.c.execution_mode, db.missions.c.paused)
                        .where(db.missions.c.organization_id == org).order_by(db.missions.c.created_at.desc()).limit(5)).all()
    if not rows:
        return Reply("There are no missions yet. Ask a researcher to look into an idea, or a developer for a software change.",
                     suggestions=["Research budgeting apps", "Fix the failing test"])
    active = sum(1 for r in rows if r.status not in DONE_MISSION)
    items = "; ".join(f"\"{r.title}\": {r.status.lower().replace('_', ' ')}{' (paused)' if r.paused else ''}"
                      f"{' [simulation]' if r.execution_mode == 'simulation' else ''}" for r in rows)
    return Reply(f"{active} of the latest {len(rows)} missions are still going. {items}. The journal has the full list.",
                 suggestions=["What needs my approval?"])


def _approvals(conn: Connection, org: str) -> Reply:
    rows = conn.execute(select(db.approvals.c.summary, db.approvals.c.action).where(
        db.approvals.c.organization_id == org, db.approvals.c.status == "PENDING").order_by(db.approvals.c.created_at).limit(3)).all()
    total = conn.execute(select(func.count()).select_from(db.approvals).where(
        db.approvals.c.organization_id == org, db.approvals.c.status == "PENDING")).scalar() or 0
    fin = conn.execute(select(func.count()).select_from(db.financial_approvals).where(
        db.financial_approvals.c.organization_id == org, db.financial_approvals.c.status == "REQUESTED")).scalar() or 0
    if not total and not fin:
        return Reply("Nothing is waiting for your approval.")
    parts = []
    if total:
        parts.append(f"{total} mission step{'s' if total != 1 else ''} need{'s' if total == 1 else ''} your approval: "
                     + "; ".join(r.summary[:120].rstrip(". ") for r in rows) + ("…" if total > len(rows) else "") + ".")
    if fin:
        parts.append(f"{fin} financial request{'s are' if fin != 1 else ' is'} waiting at the AI Central Bank.")
    parts.append("Open the approval screen (the bell) to decide. Nothing is approved until you tap Approve there.")
    return Reply(" ".join(parts))


def _recommendations(conn: Connection, org: str) -> Reply:
    opps = conn.execute(select(db.opportunities.c.title, db.opportunities.c.opportunity_score, db.opportunities.c.status,
                               db.opportunities.c.confidence, db.opportunities.c.data_mode)
                        .where(db.opportunities.c.organization_id == org)
                        .order_by(db.opportunities.c.opportunity_score.desc()).limit(3)).all()
    if not opps:
        return Reply("I have no researched opportunities to recommend yet. Ask Lumen at the Research Observatory to look into an idea.",
                     suggestions=["Research budgeting apps"])
    items = "; ".join(f"\"{o.title}\" scored {o.opportunity_score:.2f} ({o.confidence} confidence, {o.status.lower().replace('_', ' ')}"
                      f"{', fixture data' if o.data_mode != 'live' else ''})" for o in opps)
    return Reply(f"Top opportunities from research so far: {items}. Scores come from the research packets; they're not a promise of revenue.")


def _findings(conn: Connection, agent) -> Reply:
    arts = conn.execute(select(db.artifacts.c.title, db.artifacts.c.kind, db.artifacts.c.created_at)
                        .where(db.artifacts.c.agent_id == agent.id).order_by(db.artifacts.c.created_at.desc()).limit(3)).all()
    lines = []
    if agent.key in RESEARCHERS:
        opps = conn.execute(select(db.opportunities.c.title, db.opportunities.c.opportunity_score)
                            .where(db.opportunities.c.research_agent_id == agent.id)
                            .order_by(db.opportunities.c.created_at.desc()).limit(2)).all()
        if opps:
            lines.append("My latest findings: " + "; ".join(f"\"{o.title}\" ({o.opportunity_score:.2f})" for o in opps) + ".")
    if arts:
        lines.append("What I've produced: " + "; ".join(f"{a.title} ({a.kind})" for a in arts) + ". Open them from the journal.")
    return Reply(" ".join(lines) or "I haven't produced anything yet.")


def _finance(conn: Connection, org: str) -> Reply:
    from services.orchestrator import ops
    spent = ops.spent_today(conn, org)
    budget = conn.execute(select(db.organizations.c.daily_budget_usd).where(db.organizations.c.id == org)).scalar()
    return Reply(f"Estimated AI spend today is ${spent:.2f} of a ${budget:.2f} daily budget (an estimate, not a bill). "
                 "Sterling's team at the AI Central Bank can tell you where it's heading.")


# ---------------------------------------------------------------- requests that become proposals
_LEAD = r"^(?:(?:hey|hi|ok|okay)[, ]+)?(?:please\s+|can you\s+|could you\s+|would you\s+|i want you to\s+|go\s+|let'?s\s+)*"
_RESEARCH = re.compile(_LEAD + r"(?:research|investigate|look\s+into|find\s+out\s+about|study|scout|analy[sz]e)\b\s*(?:the\s+market\s+for\s+|on\s+|about\s+|for\s+)?(?P<q>.*)$")
_BUILD = re.compile(_LEAD + r"(?:build|fix|add|change|implement|create|make|update|refactor|write|improve|repair)\b")


# Asking beats guessing: proceeding on a wrong assumption is about 12% of multi-agent failures (MAST FM-2.2). A request
# too vague to act on gets a question back, never a proposal built on a guess.
_VAGUE = {"it", "this", "that", "these", "those", "thing", "things", "stuff", "something", "anything", "everything", "some",
          "the", "a", "an", "my", "our", "bug", "bugs", "issue", "issues", "problem", "problems", "app", "apps", "code", "better",
          "faster", "nicer", "good", "work", "working", "ideas", "idea", "market", "markets", "products", "product", "trends",
          "money", "more", "up", "again", "now", "please", "me", "for", "of", "to", "and", "all", "whole", "there", "here"}
_BUILD_VERB = re.compile(_LEAD + r"(?:build|fix|add|change|implement|create|make|update|refactor|write|improve|repair)\b\s*")


def _content_words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9][a-z0-9'+-]*", text.lower()) if w not in _VAGUE]


def _names_source(text: str) -> bool:
    return bool(re.search(r"app\s*store|apple|etsy|depop", text))


def _source(text: str, agent_key: str) -> str:
    if "depop" in text:
        return "depop"
    if "etsy" in text or (agent_key == "research_marketplaces" and "app store" not in text):
        return "etsy"
    return "apple_charts"


def _clean_query(q: str) -> str:
    q = re.sub(r"\b(on|in|from|at)\s+(the\s+)?(app\s*store(\s+charts)?|apple(\s+charts)?|etsy|depop)\b", " ", q)
    q = re.sub(r"[^a-z0-9 '&+-]", " ", q)
    q = re.sub(r"\b(please|for me|thanks|thank you)\b", " ", q)
    return re.sub(r"\s+", " ", q).strip()[:80].strip()


def _propose(conn: Connection, *, org: str, user: str, agent, kind: str, params: dict, summary: str) -> dict:
    pid = db.new_id()
    expires = (_now() + PROPOSAL_TTL).isoformat()
    conn.execute(insert(db.play_proposals).values(id=pid, organization_id=org, user_id=user, agent_id=agent.id, kind=kind,
                                                  params=params, summary=summary, status="PENDING", expires_at=expires))
    return {"id": pid, "kind": kind, "params": params, "summary": summary, "status": "PENDING", "expires_at": expires}


def _research(conn: Connection, org: str, user: str, agent, text: str, q: str) -> Reply:
    if agent.key not in RESEARCHERS | MANAGERS:
        return Reply("Research is the Observatory's job. Lumen, Pip or Wren at the Research Observatory can take it.")
    query = _clean_query(q)
    if len(query) < 2 or not _content_words(query):
        return Reply("What should I research, exactly? Name a kind of app or product, for example \"budgeting apps\" or "
                     "\"handmade candles on Etsy\". I'd rather ask than guess.",
                     suggestions=["Research budgeting apps", "Research handmade candles on Etsy"])
    if agent.key in MANAGERS and not _names_source(text):
        return Reply(f"Where should the team look for \"{query}\": the App Store charts (apps) or Etsy (handmade products)?",
                     suggestions=[f"Research {query} on the App Store", f"Research {query} on Etsy"])
    source = _source(text, agent.key)
    where = {"apple_charts": "the App Store charts", "etsy": "Etsy", "depop": "Depop"}[source]
    summary = f"Start market research on \"{query}\" using {where} (US)."
    prop = _propose(conn, org=org, user=user, agent=agent, kind="start_research",
                    params={"source": source, "query": query, "region": "US"}, summary=summary)
    return Reply(f"I can do that: research \"{query}\" on {where}. The General Manager reviews what I find, and the brief rides "
                 "the conveyor to the Nexus Spire. Confirm to start it.", proposal=prop)


def _build(conn: Connection, org: str, user: str, agent, raw: str) -> Reply:
    if agent.key not in BUILDERS | MANAGERS:
        return Reply("Software changes happen at the Code Forge. Kade or Orin there can take that on.")
    prompt = raw.strip()
    if len(prompt) < 8 or not _content_words(_BUILD_VERB.sub("", prompt.lower(), count=1)):
        return Reply("Before I start: which part should change, and what should it do afterwards? For example: \"fix the median "
                     "function so even-length lists average the middle pair\". I'd rather ask than build the wrong thing.",
                     suggestions=["Fix the median function so even-length lists average the middle pair"])
    summary = f"Create a software-change mission: \"{prompt[:160]}{'…' if len(prompt) > 160 else ''}\""
    prop = _propose(conn, org=org, user=user, agent=agent, kind="create_mission", params={"prompt": prompt[:4000]}, summary=summary)
    return Reply("I can take that on as a mission: the architect inspects the repository, QA reproduces the problem, I make the change "
                 "in an isolated worktree, QA re-tests and Orin reviews. Publishing waits for your approval. Confirm to start it.",
                 proposal=prop)


_TESTS = re.compile(_LEAD + r"(?:run|rerun|re-run)\s+(?:the\s+|all\s+the\s+|all\s+)?(?:tests?|test\s+suite|suite)"
                    r"\s*(?:again|now|please|for\s+me)?[.!?]*$")
TESTERS = {"qa"}
BANKERS = {"cfo", "forecaster", "revenue_analyst", "expense_auditor", "savings_strategist", "bill_manager", "tax_agent"}


def _run_tests(conn: Connection, org: str, user: str, agent) -> Reply:
    if agent.key not in TESTERS | MANAGERS:
        return Reply("Test runs are Sentry's job, at the Sentinel Citadel.")
    prompt = "Run the test suite of the connected repository and report which tests fail."
    prop = _propose(conn, org=org, user=user, agent=agent, kind="create_mission", params={"prompt": prompt, "kind": "run_tests"},
                    summary="Run the test suite and report the results (nothing is changed).")
    return Reply("I can run the whole suite in the sandbox and report what passes and what fails. Nothing gets changed. "
                 "Confirm to start it.", proposal=prop)


def _spend(conn: Connection, org: str) -> Reply:
    from services.management.forecast import forecast
    fc = forecast(conn, org)
    t = fc["total"]
    parts = [f"Estimated AI spend today is ${t['spent']:.2f}" + (f" of a ${t['daily_budget_usd']:.2f} daily budget" if t.get("daily_budget_usd") else "") + "."]
    if t.get("already_at_cap"):
        parts.append("That's already the whole daily budget, so new AI work waits until tomorrow or until the budget is raised.")
    elif t.get("projected") is not None:
        parts.append(f"At today's pace it ends the day around ${t['projected']:.2f}.")
    else:
        parts.append("There aren't enough AI calls yet today to project the rest of the day.")
    soon = [w["agent"] for w in fc["warnings"] if not w.get("already")]
    if soon:
        parts.append("Heading for a cap: " + ", ".join(soon[:3]) + ".")
    top = [a for a in fc["agents"] if a["spent"] > 0][:2]
    if top:
        parts.append("Most so far: " + ", ".join(f"{a['agent']} (${a['spent']:.2f})" for a in top) + ".")
    parts.append("These are estimates, not bills.")
    return Reply(" ".join(parts), suggestions=["What happened today?"])


def _cancel(conn: Connection, org: str, user: str, agent, text: str) -> Reply:
    rows = conn.execute(select(db.missions.c.id, db.missions.c.title, db.missions.c.status)
                        .where(db.missions.c.organization_id == org, db.missions.c.status.notin_(DONE_MISSION))
                        .order_by(db.missions.c.created_at.desc()).limit(20)).all()
    if not rows:
        return Reply("Nothing is running, so there's nothing to cancel.")
    words = {w for w in re.findall(r"[a-z0-9]{4,}", text) if w not in {"cancel", "stop", "mission", "please", "that", "this", "latest", "last"}}
    pick = next((r for r in rows if words and words & set(re.findall(r"[a-z0-9]{4,}", r.title.lower()))), None) or rows[0]
    prop = _propose(conn, org=org, user=user, agent=agent, kind="cancel_mission", params={"mission_id": pick.id},
                    summary=f"Cancel the mission \"{pick.title}\".")
    return Reply(f"You want me to cancel \"{pick.title}\" ({pick.status.lower().replace('_', ' ')})? Tasks already running stop at "
                 "their next step. Confirm to cancel it.", proposal=prop)


_AGAIN = re.compile(_LEAD + r"(?:do|run|start|try)\s+(?:that|it|this|the\s+last\s+(?:one|mission))\s+again\b|^again[!. ]*$")


def _rerun(conn: Connection, org: str, user: str, agent, text: str) -> Reply:
    from services.management.links import RERUNNABLE, TERMINAL
    rows = conn.execute(select(db.missions.c.id, db.missions.c.title, db.missions.c.status, db.missions.c.kind)
                        .where(db.missions.c.organization_id == org, db.missions.c.status.in_(list(TERMINAL)),
                               db.missions.c.kind.in_(list(RERUNNABLE)))
                        .order_by(db.missions.c.updated_at.desc()).limit(20)).all()
    if not rows:
        return Reply("Nothing has finished yet that I can start again.")
    words = {w for w in re.findall(r"[a-z0-9]{4,}", text) if w not in {"again", "that", "this", "please", "last", "mission", "start", "the"}}
    pick = next((r for r in rows if words and words & set(re.findall(r"[a-z0-9]{4,}", r.title.lower()))), None) or rows[0]
    prop = _propose(conn, org=org, user=user, agent=agent, kind="rerun_mission", params={"mission_id": pick.id},
                    summary=f"Start \"{pick.title}\" again.")
    return Reply(f"The last one I can repeat is \"{pick.title}\" ({pick.status.lower()}). Same request, starting fresh, under "
                 "your charter. Confirm to start it again.", proposal=prop)


_START_SAVED = re.compile(_LEAD + r"(?:start|run|launch|kick\s+off|do)\s+(?:my\s+|the\s+|our\s+)?(?P<n>.{2,60}?)(?:\s+(?:again|now|please))?[.!?]*$")


def _start_saved(conn: Connection, org: str, user: str, agent, t: str) -> Reply | None:
    m = _START_SAVED.match(t)
    if not m:
        return None
    from services.management import saved
    name = re.sub(r"\s+saved\s+request$", "", m.group("n").strip())
    hit = next((r for r in saved.listing(conn, org) if r["name_key"] == saved._key(name)), None)
    if hit is None:
        return None
    prop = _propose(conn, org=org, user=user, agent=agent, kind="start_saved", params={"saved_request_id": hit["id"]},
                    summary=f"Start your saved request \"{hit['name']}\".")
    return Reply(f"Your saved request \"{hit['name']}\" is ready. It starts as you, under your charter. Confirm to start it.", proposal=prop)


def _search(conn: Connection, org: str, q: str) -> Reply:
    from services.management.search import search
    res = search(conn, org, q)
    if not res["results"]:
        return Reply(f"I found nothing in the records about \"{q}\".")
    top = res["results"][:3]
    lines = "; ".join(f"{r['title']}: {r['snippet'][:90]}" for r in top)
    more = f" ({res['total']} results in all; the search screen in the Owner tab has the rest.)" if res["total"] > 3 else ""
    return Reply(f"From the records: {lines}.{more}")


def _schedule(conn: Connection, org: str, user: str, agent, t: str, tz: str) -> Reply | None:
    from services.management import schedules
    sc = schedules.parse(t)
    if sc is None:
        return None
    rest = sc.pop("rest")
    if _TESTS.match(rest):
        if agent.key not in TESTERS | MANAGERS:
            return Reply("Sentry at the Sentinel Citadel can schedule test runs.")
        kind, params, what = "run_tests", {"prompt": "Run the test suite of the connected repository and report which tests fail."}, "run the test suite"
    else:
        m = _RESEARCH.match(rest)
        query = _clean_query(m.group("q")) if m else ""
        if not m or not _content_words(query):
            return Reply("I can schedule test runs (\"every Monday at 9 run the tests\") or market research "
                         "(\"every day research budgeting apps\"). What should repeat?")
        if agent.key not in RESEARCHERS | MANAGERS:
            return Reply("The Research Observatory schedules research. Lumen, Pip or Wren can set it up.")
        source = _source(rest, agent.key)
        kind, params, what = "market_research", {"source": source, "query": query, "region": "US"}, f"research \"{query}\""
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(tz)
    except Exception:
        tz = "UTC"
    try:
        schedules.validate(kind, params, sc["cadence"], sc["weekday"], sc["hour"], sc["minute"], tz)
    except schedules.ScheduleError as exc:
        return Reply(f"I can't schedule that: {exc}. Try a time like 9am or 18:30.")
    preview = schedules.describe({**sc, "tz": tz})
    title = f"{what[0].upper()}{what[1:]}, {preview}"
    prop = _propose(conn, org=org, user=user, agent=agent, kind="create_schedule",
                    params={"kind": kind, "params": params, "tz": tz, "title": title, **sc}, summary=f"Schedule: {title}.")
    return Reply(f"I can {what} {preview}. Each run follows your charter and quiet hours, and you can pause or delete it "
                 "under Owner → Schedules. Confirm to set it up.", proposal=prop)


def respond(conn: Connection, *, org: str, user: str, agent, text: str, tz: str = "UTC") -> Reply:
    raw = (text or "").strip()
    t = raw.lower()
    if not t or re.fullmatch(r"(hi|hello|hey|yo|sup|help|what can you do\??|who are you\??)[!. ]*", t):
        return _intro(agent)
    if _has(t, "approv", "pending", "sign off", "waiting for me"):
        return _approvals(conn, org)
    if _has(t, "status", "progress", "working on", "doing", "how's it going", "how is it going", "busy", "update me", "what's up"):
        if _has(t, "everything", "all", "missions", "team"):
            return _missions(conn, org)
        return _status(conn, agent)
    scheduled = _schedule(conn, org, user, agent, t, tz)
    if scheduled:
        return scheduled
    started = _start_saved(conn, org, user, agent, t)
    if started:
        return started
    if _has(t, "cancel", "stop the", "abort"):
        return _cancel(conn, org, user, agent, t)
    if _AGAIN.search(t):
        return _rerun(conn, org, user, agent, t)
    m = _RESEARCH.match(t)
    if m:
        return _research(conn, org, user, agent, t, m.group("q"))
    if _TESTS.match(t):
        return _run_tests(conn, org, user, agent)
    if _BUILD.match(t):
        return _build(conn, org, user, agent, raw)
    found = re.match(_LEAD + r"(?:find(?!\s+out\b)|search(?: for)?|look up|where is|when did)\s+(?P<q>.{2,80})$", t)
    if found:  # after research and build, so "find out about…" still starts research
        return _search(conn, org, found.group("q").strip(" ?.!"))
    if agent.key in MANAGERS and (_has(t, "the week", "this week", "weekly", "last week", "past week", "last 7 days", "last seven days")):
        from services.management.weekly import report, spoken as weekly_spoken
        return Reply(weekly_spoken(report(conn, org, tz=tz)), suggestions=["What happened today?", "What needs my approval?"])
    if agent.key in MANAGERS and (_has(t, "what happened", "catch me up", "daily brief", "what did i miss", "recap")
                                  or re.fullmatch(r"(brief|today|summary|yesterday)\??[!. ]*", t)):
        from services.management.brief import brief, spoken
        return Reply(spoken(brief(conn, org)), suggestions=["What needs my approval?", "Show everything in progress"])
    if _has(t, "money", "budget", "spend", "cost", "bill", "tax", "financ", "revenue", "saving", "forecast"):
        return _spend(conn, org) if agent.key in BANKERS | MANAGERS else _finance(conn, org)
    if _has(t, "recommend", "opportunit", "review", "should we", "idea"):
        return _recommendations(conn, org) if agent.key in MANAGERS else _findings(conn, agent)
    if _has(t, "artifact", "result", "finding", "report", "show me", "deliverable", "produced"):
        return _findings(conn, agent)
    if _has(t, "mission", "journal", "in progress", "tasks"):
        return _missions(conn, org)
    intro = _intro(agent)
    return Reply("I didn't catch a request I can act on. " + intro.text.split(". ", 1)[-1], suggestions=intro.suggestions)
