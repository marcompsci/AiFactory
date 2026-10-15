"""Read-only view of Claude Code on the machine that runs the API (the owner's own computer when run locally).

Sources, under AICIV_CLAUDE_HOME (default ~/.claude), per Claude Code's documented layout
(https://code.claude.com/docs/en/memory):
  * sessions — projects/<project>/<session-id>.jsonl transcripts. Only metadata leaves this module: the session's
    summary or first request (truncated, secrets scrubbed), timestamps, project folder name, branch, and the titles of
    tasks marked completed (TodoWrite / TaskUpdate). Nothing else from a transcript is stored or shown.
  * memory   — CLAUDE.md files (~/.claude/CLAUDE.md, ~/.claude/rules/*.md, and CLAUDE.md / CLAUDE.local.md in the
    projects those sessions ran in) and auto memory (projects/<project>/memory/*.md).

Agents read memory through the `read_claude_code_memory` tool. Excerpts are scrubbed of secrets and always passed to
models as untrusted text. Nothing here writes to ~/.claude or to any project.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from services.tools.registry import redact

MAX_TAIL = 2_000_000          # bytes read from the end of a transcript
MAX_SESSIONS = 20
MAX_MEMORY_FILE = 200_000


def home() -> Path:
    return Path(os.environ.get("AICIV_CLAUDE_HOME") or Path.home() / ".claude").expanduser()


def available() -> bool:
    return (home() / "projects").is_dir() or (home() / "CLAUDE.md").is_file()


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    return ""


def _clean(s: str, n: int = 140) -> str:
    s = re.sub(r"<[^>]{1,80}>", " ", s or "")          # drop wrapper tags such as <command-name>
    s = redact(" ".join(s.split()))
    return s[: n - 1] + "…" if len(s) > n else s


def _tail_lines(path: Path) -> list[str]:
    size = path.stat().st_size
    with path.open("rb") as fh:
        if size > MAX_TAIL:
            fh.seek(size - MAX_TAIL)
            fh.readline()  # skip the partial first line
        return fh.read().decode("utf-8", "replace").splitlines()


def _head_lines(path: Path, n: int = 60) -> list[str]:
    out = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for _ in range(n):
            line = fh.readline()
            if not line:
                break
            out.append(line)
    return out


def parse_session(path: Path) -> dict | None:
    title = summary = None
    cwd = branch = None
    first_at = last_at = None
    messages = 0
    todos: dict[str, str] = {}          # content → status (TodoWrite keeps the full list each time)
    tasks: dict[str, dict] = {}         # TaskCreate / TaskUpdate
    for raw in _head_lines(path) + _tail_lines(path):
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        if e.get("type") == "summary" and e.get("summary"):
            summary = e["summary"]
        ts = e.get("timestamp")
        if ts:
            first_at = first_at or ts
            last_at = max(last_at or ts, ts)
        cwd = e.get("cwd") or cwd
        branch = e.get("gitBranch") or branch
        msg = e.get("message") if isinstance(e.get("message"), dict) else None
        if e.get("type") == "user" and msg:
            messages += 1
            t = _text(msg.get("content"))
            if t and not title and not t.lstrip().startswith(("<local-command", "<command-", "Caveat:")):
                title = t
        elif e.get("type") == "assistant" and msg:
            messages += 1
            for c in msg.get("content") or []:
                if not (isinstance(c, dict) and c.get("type") == "tool_use"):
                    continue
                inp = c.get("input") or {}
                if c.get("name") == "TodoWrite":
                    todos = {str(t.get("content", "")): str(t.get("status", "")) for t in inp.get("todos") or [] if isinstance(t, dict)}
                elif c.get("name") == "TaskCreate" and inp.get("subject"):
                    tasks[str(c.get("id"))] = {"subject": str(inp["subject"]), "status": "pending", "at": ts}
                elif c.get("name") == "TaskUpdate" and inp.get("status"):
                    key = str(inp.get("taskId"))
                    hit = next((v for k, v in tasks.items() if k.endswith(key) or v.get("task_id") == key), None)
                    if hit is None:
                        hit = tasks.setdefault(f"id:{key}", {"subject": str(inp.get("subject") or f"Task {key}"), "status": "pending"})
                    hit["status"], hit["at"] = str(inp["status"]), ts
    if not (title or summary) and not messages:
        return None
    completed = [k for k, v in todos.items() if v == "completed"] + [t["subject"] for t in tasks.values() if t.get("status") == "completed"]
    open_items = [k for k, v in todos.items() if v != "completed"] + [t["subject"] for t in tasks.values() if t.get("status") != "completed"]
    project = (Path(cwd).name if cwd else path.parent.name.split("-")[-1]) or path.parent.name
    return {"id": path.stem, "project": _clean(project, 60), "branch": _clean(branch or "", 60) or None,
            "title": _clean(summary or title or "(untitled session)"), "started_at": first_at, "last_activity_at": last_at,
            "messages": messages, "completed_tasks": [_clean(t, 100) for t in completed][-8:],
            "open_tasks": [_clean(t, 100) for t in open_items][:8], "_cwd": cwd, "_dir": path.parent.name}


def sessions(limit: int = MAX_SESSIONS) -> list[dict]:
    root = home() / "projects"
    if not root.is_dir():
        return []
    files = sorted(root.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
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
    """CLAUDE.md files and auto memory, with a label safe to show (paths relative to ~ / the project)."""
    h = home()
    found: list[tuple[str, Path]] = []
    if (h / "CLAUDE.md").is_file():
        found.append(("~/.claude/CLAUDE.md", h / "CLAUDE.md"))
    found += [(f"~/.claude/rules/{p.name}", p) for p in sorted((h / "rules").glob("*.md"))] if (h / "rules").is_dir() else []
    names = {s.get("_dir"): s.get("project") for s in (session_list or []) if s.get("_dir")}
    if (h / "projects").is_dir():
        for p in sorted((h / "projects").glob("*/memory/*.md")):
            d = p.parent.parent.name
            found.append((f"auto memory · {names.get(d) or d.split('-')[-1] or d}/{p.name}", p))
    seen = set()
    for s in (session_list or [])[:10]:
        cwd = s.get("_cwd")
        if not cwd or cwd in seen:
            continue
        seen.add(cwd)
        for name in ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md"):
            p = Path(cwd) / name
            if p.is_file():
                found.append((f"{Path(cwd).name}/{name}", p))
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
    """Paragraph-level keyword search across Claude Code's memory. Returns scrubbed excerpts with their source."""
    terms = [t for t in re.findall(r"[a-z0-9_]{3,}", query.lower())]
    hits = []
    for f in memory_files(sessions(10)):
        for para in re.split(r"\n\s*\n", f["_text"]):
            p = para.strip()
            if not p:
                continue
            low = p.lower()
            score = sum(low.count(t) for t in terms) if terms else 1
            if score:
                hits.append((score, f["label"], p))
    hits.sort(key=lambda h: -h[0])
    return [{"source": label, "text": redact(p[:800])} for _, label, p in hits[:k]]


def public(s: dict) -> dict:
    return {k: v for k, v in s.items() if not k.startswith("_")}
