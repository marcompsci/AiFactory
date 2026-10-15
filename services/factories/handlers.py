"""Task handlers for factory_sync missions."""
from __future__ import annotations

from services.orchestrator.handlers import TaskEnv


def claude_sync(env: TaskEnv) -> dict:
    r = env.tool("sync_claude_code")
    env.say(f"Checked in with Claude Code: {r['count']} recent session(s), {r['completed_tasks']} finished task(s), "
            f"{r['memory_files']} memory file(s) shared with the team.", to_key="architect", kind="handoff")
    return {"count": r["count"]}


def github_sync(env: TaskEnv) -> dict:
    r = env.tool("sync_github_activity")
    env.say(f"Updated the GitHub Factory board for {r['count']} repositor{'y' if r['count'] == 1 else 'ies'}.", to_key="architect", kind="status")
    return {"count": r["count"]}


def codex_sync(env: TaskEnv) -> dict:
    r = env.tool("sync_codex")
    env.say(f"Checked in with Codex: {r['count']} recent session(s), {r['completed_tasks']} finished step(s), "
            f"{r['memory_files']} AGENTS.md file(s) shared with the team.", to_key="architect", kind="handoff")
    return {"count": r["count"]}


def _pct(v) -> str:
    return "unknown" if v is None else f"{v:.0f}%"


def codex_usage(env: TaskEnv) -> dict:
    """Nyx briefs every agent on the Codex plan."""
    r = env.tool("read_plan_usage", plan="codex")
    cx = r["codex"]
    if not cx.get("available"):
        env.say("Codex plan: the codex command isn't installed on this computer, so all work goes to the Claude plan.", kind="status")
        return {"count": 1}
    p, w = cx.get("primary") or {}, cx.get("secondary") or {}
    stop = r["settings"]["codex_stop_percent"]
    msg = (f"Codex plan: {_pct(p.get('used_percent'))} of the 5-hour window and {_pct(w.get('used_percent'))} of the week used "
           f"(reported by Codex). We stop using it at {stop:.0f}%.")
    msg += " You're on Codex now." if r["plan"] == "codex" else " Codex is out for now; work moves to the Claude plan."
    if r["save"] and r["plan"] == "codex":
        msg += " Getting close: keep answers short."
    env.say(msg, kind="status")
    return {"count": 1}


def claude_usage(env: TaskEnv) -> dict:
    """Coda briefs every agent on the Claude plan and how much to save for the owner."""
    r = env.tool("read_plan_usage", plan="claude")
    cl, s = r["claude"], r["settings"]
    if not cl.get("available"):
        env.say("Claude plan: the claude command isn't installed on this computer.", kind="status")
        return {"count": 1}
    used = (f"about {_pct(cl['used_percent'])} of the 5-hour budget (estimate)" if cl.get("used_percent") is not None
            else f"{cl.get('tokens_5h', 0):,} tokens in the last 5 hours (estimate; set a budget for a percentage)")
    msg = f"Claude plan: {used}. Save {s['claude_reserve_percent']:.0f}% for the owner."
    if r["owner_active"]:
        msg += f" The owner is using Claude ({r['owner']['reason']}), so anyone on the Claude plan uses Haiku."
    if cl.get("limit_reported"):
        msg += " Claude reported its limit is reached; nobody uses it until it resets."
    env.say(msg, kind="status")
    return {"count": 1}


FACTORY_HANDLERS = {"claude_sync": claude_sync, "github_sync": github_sync, "codex_sync": codex_sync,
                    "codex_usage": codex_usage, "claude_usage": claude_usage}
