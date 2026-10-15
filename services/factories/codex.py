"""Read-only view of Codex on the machine that runs the API, for the Codex Factory.

Sources, under AICIV_CODEX_HOME (default ~/.codex):
  * sessions — sessions/YYYY/MM/DD/rollout-*.jsonl. Only metadata leaves this module: the first request (truncated,
    secrets scrubbed), timestamps, project folder name, and the steps Codex marked completed in its plan
    (`update_plan`). Sessions the agents themselves ran (in the agent work folder) are labeled as theirs.
  * memory   — AGENTS.md files (~/.codex/AGENTS.md and AGENTS.md in the projects those sessions ran in), shared
    with the other agents the same way as Claude Code's memory: scrubbed, and passed to models as untrusted text.
Nothing here writes to ~/.codex or to any project.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from services.model_gateway import plans
from services.tools.registry import redact

from .claude_code import MAX_MEMORY_FILE, _clean, _head_lines, _tail_lines

MAX_SESSIONS = 20


def home() -> Path:
    return plans.codex_home()


def available() -> bool:
    return (home() / "sessions").is_dir() or (home() / "AGENTS.md").is_file()


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") in ("input_text", "output_text", "text"))
    return ""


def parse_session(path: Path) -> dict | None:
    title = cwd = None
    first_at = last_at = None
    messages = 0
    steps: dict[str, str] = {}
    for raw in _head_lines(path, 40) + _tail_lines(path):
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        ts = e.get("timestamp")
        if ts:
            first_at = first_at or ts
            last_at = max(last_at or ts, ts)
        p = e.get("payload") if isinstance(e.get("payload"), dict) else {}
        t = e.get("type")
        if t == "session_meta":
            cwd = p.get("cwd") or cwd
        elif t == "event_msg" and p.get("type") == "user_message":
            messages += 1
            msg = p.get("message") or ""
            if msg and not title and not msg.lstrip().startswith("<"):
                title = msg
        elif t == "event_msg" and p.get("type") == "agent_message":
            messages += 1
        elif t == "response_item" and p.get("type") == "message" and p.get("role") == "user" and not title:
            txt = _content_text(p.get("content"))
            if txt and not txt.lstrip().startswith("<"):
                title = txt
        elif t == "response_item" and p.get("type") == "function_call" and p.get("name") == "update_plan":
            try:
                args = json.loads(p.get("arguments") or "{}")
            except ValueError:
                args = {}
            steps = {str(s.get("step", "")): str(s.get("status", "")) for s in args.get("plan") or [] if isinstance(s, dict)}
    if not title and not messages:
        return None
    by_agents = bool(cwd) and Path(cwd).resolve() == plans.workdir().resolve()
    return {"id": path.stem, "project": "AI Civilization agents" if by_agents else _clean(Path(cwd).name if cwd else "", 60) or "—",
            "title": _clean(title or "(untitled session)"), "started_at": first_at, "last_activity_at": last_at, "messages": messages,
            "completed_tasks": [_clean(k, 100) for k, v in steps.items() if v == "completed"][-8:],
            "open_tasks": [_clean(k, 100) for k, v in steps.items() if v != "completed"][:8], "by_agents": by_agents, "_cwd": cwd}


def sessions(limit: int = MAX_SESSIONS) -> list[dict]:
    root = home() / "sessions"
    if not root.is_dir():
        return []
    files = sorted(root.glob("**/rollout-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    out = []
    now = datetime.now(timezone.utc).timestamp()
    for f in files:
        try:
            s = parse_session(f)
        except OSError:
            continue
        if s:
            s["active"] = now - f.stat().st_mtime < 600
            out.append(s)
    return out


def memory_files(session_list: list[dict] | None = None) -> list[dict]:
    h = home()
    found = [("~/.codex/AGENTS.md", h / "AGENTS.md")] if (h / "AGENTS.md").is_file() else []
    seen = set()
    for s in (session_list or [])[:10]:
        cwd = s.get("_cwd")
        if not cwd or cwd in seen or s.get("by_agents"):
            continue
        seen.add(cwd)
        p = Path(cwd) / "AGENTS.md"
        if p.is_file():
            found.append((f"{Path(cwd).name}/AGENTS.md", p))
    out = []
    for label, p in found:
        try:
            text = p.read_text(errors="replace")[:MAX_MEMORY_FILE]
        except OSError:
            continue
        out.append({"label": label, "bytes": len(text), "updated_at": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
                    "excerpt": _clean(text, 240), "_text": text})
    return out


def search_memory(query: str, k: int = 6) -> list[dict]:
    terms = re.findall(r"[a-z0-9_]{3,}", query.lower())
    hits = []
    for f in memory_files(sessions(10)):
        for para in re.split(r"\n\s*\n", f["_text"]):
            p = para.strip()
            if not p:
                continue
            score = sum(p.lower().count(t) for t in terms) if terms else 1
            if score:
                hits.append((score, f["label"], p))
    hits.sort(key=lambda h: -h[0])
    return [{"source": label, "text": redact(p[:800])} for _, label, p in hits[:k]]


def public(s: dict) -> dict:
    return {k: v for k, v in s.items() if not k.startswith("_")}
