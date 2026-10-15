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


FACTORY_HANDLERS = {"claude_sync": claude_sync, "github_sync": github_sync}
