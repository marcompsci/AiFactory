"""Task handlers for App Lab missions. The repository's contents are untrusted input to any model call."""
from __future__ import annotations

import json
import re

from sqlalchemy import select

from services.core import db
from services.orchestrator.handlers import TaskEnv, TaskError


def _param(env: TaskEnv, key: str) -> str:
    v = (env.mission.params or {}).get(key)
    if not v:
        raise TaskError(f"mission has no {key}")
    return v


def lab_research(env: TaskEnv) -> dict:
    r = env.tool("research_design_insights", cycle_id=_param(env, "cycle_id"))
    env.say(f"Collected {r['count']} design pattern(s) people engage with, pay for and play ({r['data_mode']} evidence). Sending them to "
            "the App Lab at Code Forge.", to_key="developer", kind="handoff")
    return {"count": r["count"]}


def _json_block(text: str):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def lab_analyze(env: TaskEnv) -> dict:
    cid = _param(env, "cycle_id")
    scan = env.tool("scan_repository", cycle_id=cid)
    r = env.tool("propose_improvements", cycle_id=cid)
    # What Claude Code already learned about this codebase (CLAUDE.md, auto memory), when the owner linked it.
    mem = env.tool("read_claude_code_memory", query=" ".join(["conventions", "tests", "style", *scan["stack"], *scan["readme"].split()[:12]]))
    refined = patched = 0
    if env.live and r.get("proposal_ids"):
        with db.get_engine().connect() as conn:
            rows = conn.execute(select(db.lab_proposals).where(db.lab_proposals.c.id.in_(r["proposal_ids"]),
                                                               db.lab_proposals.c.route == "claude_code")).fetchall()
        context = {"stack": scan["stack"], "files": scan["files"][:200], "readme": scan["readme"][:2500],
                   "claude_code_memory": [h["text"][:500] for h in mem.get("hits", [])[:4]]}
        for p in rows:
            reply = env.ask_model(
                "You are a senior app developer. Tailor this improvement to the repository below. Reply with JSON only: "
                '{"summary": "<two sentences>", "plan": ["<step>", ...]} with at most six concrete steps naming real files from the list. '
                "Do not suggest changes to CI, secrets, billing or deployment.\n<untrusted>"
                + json.dumps({"improvement": {"title": p.title, "why": p.summary, "plan": p.plan}, "repository": context}) + "</untrusted>", 500)
            data = _json_block(reply)
            if isinstance(data, dict) and isinstance(data.get("plan"), list):
                env.tool("refine_proposal", cycle_id=cid, proposal_id=p.id, summary=str(data.get("summary", "")), plan=data["plan"],
                         model=env.agent.model_name)
                refined += 1
    if mem.get("count"):
        env.say(f"Pulled {mem['count']} note(s) from Claude Code's memory about how this project is built.", kind="status")
    env.say(f"Read {scan['file_count']} files at {scan['base_sha'][:8]} (read-only) and drafted {r['count']} proposal(s)"
            + (f", {refined} tailored by {env.agent.model_name}" if refined else " from templates") + ". Sending them to the General Manager.",
            to_key="general_manager", kind="handoff")
    return {"proposals": r["count"], "refined": refined, "patched": patched}


def lab_publish(env: TaskEnv) -> dict:
    pid = _param(env, "proposal_id")
    with db.get_engine().connect() as conn:
        p = conn.execute(select(db.lab_proposals).where(db.lab_proposals.c.id == pid)).first()
    if p is None:
        raise TaskError("unknown proposal")
    r = env.tool("publish_lab_change", proposal_id=pid, payload_hash=p.payload_hash)
    what = "a draft pull request" if r["kind"] == "pr" else "an issue for Claude Code"
    env.say(f"Owner-approved change published as {what}: {r['url']}. Nothing was pushed to the default branch.", to_key="general_manager",
            kind="status")
    return {"url": r["url"]}


LAB_HANDLERS = {"lab_research": lab_research, "lab_analyze": lab_analyze, "lab_publish": lab_publish}
