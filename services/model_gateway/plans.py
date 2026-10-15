"""Run the agents on your own subscriptions: the Codex plan first, the Claude plan when Codex runs out.

How it works
- Each model call goes through the official command-line tool for the plan you're signed in to on this computer:
  `codex exec` (ChatGPT/Codex plan) or `claude -p` (Claude plan). This app never sees or stores the plan's
  credentials; each CLI uses its own sign-in. Use is subject to each plan's terms and its usage limits.
- The agents only ever get text answers back: both CLIs run with tools off (`claude --tools ""`, no MCP) or in a
  read-only sandbox in an empty folder (`codex exec --sandbox read-only`), so a model can't run commands for them.
- Routing, in order:
    1. Codex, unless its own 5-hour or weekly window is at or above the stop line (default 95%) or Codex said the
       limit is reached.
    2. Claude, unless Claude said the limit is reached or (when you've set a 5-hour budget) the estimate has reached
       the share you keep for yourself (default: agents stop at 60%, leaving 40% for you).
    3. Otherwise the call fails with `quota` and the task waits; nothing falls back to a paid API key.
- While you're using Claude yourself (a Claude Code session written to in the last 10 minutes, or the Claude app
  open), agents on the Claude plan use the smallest model (Haiku), so your own work has the room.

Usage figures
- Codex: read from Codex's own rate-limit reports in ~/.codex/sessions (what `/status` shows). Labeled "reported".
- Claude: there is no public usage API for subscriptions, so it's an ESTIMATE: tokens in your Claude Code sessions in
  the last 5 hours plus what the agents used, against a 5-hour budget you set. Without a budget, only the token count
  is shown. A "limit reached" answer from Claude always counts, budget or not.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.model_gateway.gateway import ModelRequest, ModelResponse, ProviderError, fit_context

LIMIT_RX = re.compile(r"usage limit|rate limit|limit reached|limit has been reached|quota|too many requests|out of (credits|usage)", re.I)
_EXHAUSTED: dict[str, float] = {}       # plan -> epoch seconds until which we treat it as exhausted
_LOCK = threading.Semaphore(int(os.environ.get("AICIV_PLAN_CONCURRENCY", "2")))


def enabled() -> bool:
    return os.environ.get("AICIV_USE_PLANS", "") in ("1", "true", "yes") and bool(codex_bin() or claude_bin())


def codex_bin() -> str | None:
    return os.environ.get("AICIV_CODEX_BIN") or shutil.which("codex")


def claude_bin() -> str | None:
    return os.environ.get("AICIV_CLAUDE_BIN") or shutil.which("claude")


def codex_home() -> Path:
    return Path(os.environ.get("AICIV_CODEX_HOME") or os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()


def claude_home() -> Path:
    return Path(os.environ.get("AICIV_CLAUDE_HOME") or Path.home() / ".claude").expanduser()


def workdir() -> Path:
    """An empty folder the CLIs run in, so they never see a project (and their own sessions are recognisable)."""
    p = Path(os.environ.get("AICIV_PLAN_WORKDIR") or Path.home() / ".aiciv" / "agent-workdir").expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def mark_exhausted(plan: str, minutes: float = 60) -> None:
    _EXHAUSTED[plan] = time.time() + minutes * 60


def exhausted(plan: str) -> bool:
    return _EXHAUSTED.get(plan, 0) > time.time()


def clear_exhausted() -> None:
    _EXHAUSTED.clear()


# ------------------------------------------------------------------ settings

DEFAULTS = {"codex_stop_percent": 95.0, "claude_reserve_percent": 40.0, "claude_5h_token_budget": None,
            "owner_active_minutes": 10.0, "app_open_counts_as_active": True, "prefer": "codex"}


def settings(conn=None) -> dict:
    """Owner-editable routing settings (services/api/usage.py), falling back to environment and defaults."""
    out = dict(DEFAULTS)
    env = {"codex_stop_percent": "AICIV_CODEX_STOP_PERCENT", "claude_reserve_percent": "AICIV_CLAUDE_RESERVE_PERCENT",
           "claude_5h_token_budget": "AICIV_CLAUDE_5H_TOKEN_BUDGET", "owner_active_minutes": "AICIV_OWNER_ACTIVE_MINUTES"}
    for k, name in env.items():
        if os.environ.get(name):
            try:
                out[k] = float(os.environ[name])
            except ValueError:
                pass
    try:
        from sqlalchemy import select

        from services.core import db
        if conn is None:
            with db.get_engine().connect() as c:
                row = c.execute(select(db.plan_settings.c.data).order_by(db.plan_settings.c.updated_at.desc())).first()
        else:
            row = conn.execute(select(db.plan_settings.c.data).order_by(db.plan_settings.c.updated_at.desc())).first()
        if row and isinstance(row.data, dict):
            out.update({k: v for k, v in row.data.items() if k in DEFAULTS})
    except Exception:  # noqa: BLE001 — settings table may not exist yet during migrations/tests
        pass
    return out


# ------------------------------------------------------------------ usage readers

def _parse_ts(s) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def codex_usage(now: datetime | None = None) -> dict:
    """The latest rate-limit report Codex wrote to its session files (5-hour and weekly windows)."""
    now = now or datetime.now(timezone.utc)
    root = codex_home() / "sessions"
    out = {"plan": "codex", "available": bool(codex_bin()), "source": "reported", "primary": None, "secondary": None,
           "reported_at": None, "tokens_5h": 0}
    if not root.is_dir():
        out["source"] = "none"
        return out
    files = sorted(root.glob("**/rollout-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:40]
    since = now - timedelta(hours=5)
    for f in files:
        try:
            lines = f.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            if '"token_count"' not in line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            p = rec.get("payload") or {}
            if p.get("type") != "token_count":
                continue
            ts = _parse_ts(rec.get("timestamp"))
            last = ((p.get("info") or {}).get("last_token_usage") or {})
            if ts and ts >= since:
                out["tokens_5h"] += int(last.get("input_tokens", 0) or 0) - int(last.get("cached_input_tokens", 0) or 0) + int(last.get("output_tokens", 0) or 0)
            rl = p.get("rate_limits")
            if rl and ts and (out["reported_at"] is None or ts > _parse_ts(out["reported_at"])):
                out["reported_at"] = ts.isoformat()
                for k in ("primary", "secondary"):
                    w = rl.get(k)
                    if not w:
                        continue
                    resets = None
                    if w.get("resets_at"):
                        resets = datetime.fromtimestamp(float(w["resets_at"]), timezone.utc)
                    elif w.get("resets_in_seconds") is not None:
                        resets = ts + timedelta(seconds=float(w["resets_in_seconds"]))
                    used = float(w.get("used_percent", 0) or 0)
                    if resets and resets <= now:
                        used = 0.0  # that window has rolled over since the report
                    out[k] = {"used_percent": round(used, 1), "window_minutes": w.get("window_minutes"),
                              "resets_at": resets.isoformat() if resets else None}
    if out["reported_at"] is None:
        out["source"] = "none"
    return out


def _agent_project_dir_name() -> str:
    # Claude Code names project folders after the path with "/" and "." turned into "-"
    return re.sub(r"[/.]", "-", str(workdir()))


def claude_usage(now: datetime | None = None, agent_tokens_5h: int = 0, budget: float | None = None) -> dict:
    """ESTIMATE: tokens in your Claude Code sessions in the last 5 hours plus the agents' own, against your budget."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=5)
    root = claude_home() / "projects"
    owner_tokens = 0
    if root.is_dir():
        skip = _agent_project_dir_name()
        cutoff = since.timestamp()
        for f in root.glob("*/*.jsonl"):
            if f.parent.name == skip:
                continue
            try:
                if f.stat().st_mtime < cutoff:
                    continue
                lines = f.read_text(errors="replace").splitlines()
            except OSError:
                continue
            for line in lines:
                if '"usage"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = _parse_ts(rec.get("timestamp"))
                if not ts or ts < since:
                    continue
                u = (rec.get("message") or {}).get("usage") or {}
                # cache reads are cheap against limits; count fresh input + cache writes + output
                owner_tokens += int(u.get("input_tokens", 0) or 0) + int(u.get("cache_creation_input_tokens", 0) or 0) + int(u.get("output_tokens", 0) or 0)
    total = owner_tokens + agent_tokens_5h
    pct = round(100 * total / budget, 1) if budget else None
    return {"plan": "claude", "available": bool(claude_bin()), "source": "estimate", "owner_tokens_5h": owner_tokens,
            "agent_tokens_5h": agent_tokens_5h, "tokens_5h": total, "budget_5h": budget, "used_percent": pct,
            "limit_reported": exhausted("claude")}


def owner_activity(now: datetime | None = None, minutes: float = 10, app_counts: bool = True) -> dict:
    """Are you using Claude right now? Recent writes to your Claude Code sessions (not the agents'), or the Claude app open."""
    now = now or datetime.now(timezone.utc)
    root = claude_home() / "projects"
    latest = None
    if root.is_dir():
        skip = _agent_project_dir_name()
        for f in root.glob("*/*.jsonl"):
            if f.parent.name == skip:
                continue
            try:
                m = f.stat().st_mtime
            except OSError:
                continue
            latest = m if latest is None or m > latest else latest
    recent = bool(latest and now.timestamp() - latest < minutes * 60)
    app_open = _claude_app_running()
    active = recent or (app_counts and app_open)
    reason = "a Claude Code session in the last %d min" % minutes if recent else ("the Claude app is open" if active else "not using Claude")
    return {"active": active, "claude_code_recent": recent, "claude_app_open": app_open,
            "last_activity_at": datetime.fromtimestamp(latest, timezone.utc).isoformat() if latest else None, "reason": reason}


def _claude_app_running() -> bool:
    if os.environ.get("AICIV_CLAUDE_APP_OPEN") in ("0", "1"):
        return os.environ["AICIV_CLAUDE_APP_OPEN"] == "1"
    try:
        out = subprocess.run(["ps", "-axo", "comm"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return any(line.strip().endswith("Claude.app/Contents/MacOS/Claude") or line.strip() == "Claude" for line in out.splitlines())


# ------------------------------------------------------------------ the decision

@dataclass
class Budget:
    plan: str | None                       # "codex" | "claude" | None (nothing left)
    model: str | None                      # model alias passed to the CLI (None = the CLI's default)
    effort: str | None = None              # codex reasoning effort when saving
    reason: str = ""
    owner_active: bool = False
    save: bool = False                     # keep answers short
    codex: dict = field(default_factory=dict)
    claude: dict = field(default_factory=dict)
    owner: dict = field(default_factory=dict)
    settings: dict = field(default_factory=dict)

    def note(self) -> str:
        """One line every agent sees in its instructions."""
        c = self.codex.get("primary") or {}
        cw = self.codex.get("secondary") or {}
        parts = []
        if self.codex.get("available"):
            parts.append(f"Codex plan {c.get('used_percent', '?')}% of 5h" + (f", {cw.get('used_percent')}% of week" if cw else ""))
        if self.claude.get("available"):
            cl = self.claude
            parts.append("Claude plan " + (f"~{cl['used_percent']}% of 5h (estimate)" if cl.get("used_percent") is not None
                                           else f"{cl.get('tokens_5h', 0):,} tokens in 5h (estimate)"))
        who = "The owner is using Claude now; " if self.owner_active else ""
        return (f"Usage budget: {'; '.join(parts) or 'unknown'}. {who}You are running on the "
                f"{self.plan or 'no'} plan{(' with ' + self.model) if self.model else ''}. "
                + ("Save usage: be brief and only do what the task needs." if self.save else "Be efficient."))


def agent_tokens(conn, plan: str, hours: float = 5) -> int:
    from sqlalchemy import func, select

    from services.core import db
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    try:
        r = conn.execute(select(func.coalesce(func.sum(db.usage_records.c.input_tokens + db.usage_records.c.output_tokens), 0))
                         .where(db.usage_records.c.provider == f"{plan}_plan", db.usage_records.c.created_at >= since)).scalar()
    except Exception:  # noqa: BLE001 — no database yet: count only what's on disk
        conn.rollback() if hasattr(conn, "rollback") else None
        return 0
    return int(r or 0)


def decide(family: str | None = None, conn=None) -> Budget:
    """Which plan and model the next agent call uses, and why. `family` is the agent's model family (opus/sonnet/haiku)."""
    s = settings(conn)
    if conn is None:
        from services.core import db
        with db.get_engine().connect() as c:
            claude_agent = agent_tokens(c, "claude")
    else:
        claude_agent = agent_tokens(conn, "claude")
    cx = codex_usage()
    budget = float(s["claude_5h_token_budget"]) if s.get("claude_5h_token_budget") else None
    cl = claude_usage(agent_tokens_5h=claude_agent, budget=budget)
    who = owner_activity(minutes=float(s["owner_active_minutes"]), app_counts=bool(s["app_open_counts_as_active"]))
    stop = float(s["codex_stop_percent"])
    cx_used = max((cx.get("primary") or {}).get("used_percent", 0) or 0, (cx.get("secondary") or {}).get("used_percent", 0) or 0)
    codex_ok = cx["available"] and not exhausted("codex") and cx_used < stop
    agents_line = 100 - float(s["claude_reserve_percent"])
    claude_ok = cl["available"] and not exhausted("claude") and (cl["used_percent"] is None or cl["used_percent"] < agents_line)
    base = dict(codex=cx, claude=cl, owner=who, settings=s, owner_active=who["active"])
    order = ["claude", "codex"] if s.get("prefer") == "claude" else ["codex", "claude"]
    for plan in order:
        if plan == "codex" and codex_ok:
            save = cx_used >= stop - 20
            return Budget("codex", os.environ.get("AICIV_CODEX_MODEL") or None, "low" if save else None,
                          f"Codex plan at {cx_used:.0f}% (stops at {stop:.0f}%)", save=save, **base)
        if plan == "claude" and claude_ok:
            low = who["active"] or (cl["used_percent"] is not None and cl["used_percent"] >= agents_line - 20)
            model = "haiku" if low else (family or "sonnet")
            why = ("you're using Claude, so agents use Haiku" if who["active"] else
                   "Codex is out; Claude plan" + (f" ~{cl['used_percent']:.0f}% used (estimate)" if cl["used_percent"] is not None else ""))
            return Budget("claude", model, None, why, save=low, **base)
    reasons = []
    if cx["available"]:
        reasons.append("Codex limit reached" if exhausted("codex") or cx_used >= stop else "Codex unavailable")
    if cl["available"]:
        reasons.append("Claude limit reached" if exhausted("claude") else f"keeping {s['claude_reserve_percent']:.0f}% of Claude for you")
    return Budget(None, None, None, "; ".join(reasons) or "no plan CLI found", save=True, **base)


# ------------------------------------------------------------------ the CLI adapters

def _run(cmd: list[str], stdin: str, timeout: float, env: dict | None = None) -> subprocess.CompletedProcess:
    with _LOCK:
        try:
            return subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout, cwd=str(workdir()),
                                  env={**os.environ, **(env or {})})
        except subprocess.TimeoutExpired as exc:
            raise ProviderError("timeout", f"{cmd[0]} took longer than {timeout:.0f}s", "plan") from exc
        except OSError as exc:
            raise ProviderError("unavailable", str(exc), "plan") from exc


def run_codex(system: str, prompt: str, model: str | None, effort: str | None, timeout: float) -> tuple[str, int, int]:
    exe = codex_bin()
    if not exe:
        raise ProviderError("unavailable", "codex CLI not found", "codex_plan")
    cmd = [exe, "exec", "--json", "--skip-git-repo-check", "--sandbox", "read-only", "-C", str(workdir())]
    if model:
        cmd += ["-m", model]
    if effort:
        cmd += ["-c", f'model_reasoning_effort="{effort}"']
    cmd.append("-")
    text = (f"{system}\n\nAnswer with text only. Do not run commands or edit files.\n\n{fit_context(prompt)}")
    p = _run(cmd, text, timeout)
    answer, it, ot, err = "", 0, 0, ""
    for line in p.stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = ev.get("type")
        if t == "item.completed" and (ev.get("item") or {}).get("type") in ("agent_message", "assistant_message"):
            answer = (ev["item"].get("text") or answer)
        elif t == "turn.completed":
            u = ev.get("usage") or {}
            it += int(u.get("input_tokens", 0) or 0) - int(u.get("cached_input_tokens", 0) or 0)
            ot += int(u.get("output_tokens", 0) or 0)
        elif t in ("turn.failed", "error"):
            err = ((ev.get("error") or {}).get("message") if isinstance(ev.get("error"), dict) else None) or ev.get("message") or str(ev)
    if not answer:
        msg = err or p.stderr.strip()[-400:] or f"codex exited {p.returncode}"
        if LIMIT_RX.search(msg):
            mark_exhausted("codex")
            raise ProviderError("quota", "Codex plan limit reached", "codex_plan")
        raise ProviderError("server" if p.returncode else "bad_request", msg[:300], "codex_plan")
    return answer.strip(), max(it, 0), ot


def run_claude(system: str, prompt: str, model: str | None, timeout: float) -> tuple[str, int, int]:
    exe = claude_bin()
    if not exe:
        raise ProviderError("unavailable", "claude CLI not found", "claude_plan")
    cmd = [exe, "-p", "--output-format", "json", "--tools", "", "--strict-mcp-config", "--disallowedTools", "mcp__*",
           "--no-session-persistence", "--max-turns", "1", "--system-prompt", system]
    if model:
        cmd += ["--model", model]
    p = _run(cmd, fit_context(prompt), timeout)
    try:
        out = json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {}
    except (json.JSONDecodeError, IndexError):
        out = {}
    result = out.get("result") or ""
    if out.get("is_error") or not result or p.returncode:
        msg = result or p.stderr.strip()[-400:] or f"claude exited {p.returncode}"
        if LIMIT_RX.search(msg):
            mark_exhausted("claude")
            raise ProviderError("quota", "Claude plan limit reached", "claude_plan")
        raise ProviderError("auth" if "log in" in msg.lower() or "login" in msg.lower() else "server", msg[:300], "claude_plan")
    u = out.get("usage") or {}
    it = int(u.get("input_tokens", 0) or 0) + int(u.get("cache_creation_input_tokens", 0) or 0)
    return result.strip(), it, int(u.get("output_tokens", 0) or 0)


def _family(model: str | None) -> str | None:
    return next((f for f in ("opus", "sonnet", "haiku", "fable") if model and f in model), None)


class PlanAdapter:
    """Gateway adapter: picks the plan per call (see `decide`), tells the agent its budget, and falls over once."""

    provider = "plan"
    model = "plan"
    capabilities = {"system_prompt": True, "tool_use": False, "json_mode": False, "subscription": True}

    def __init__(self, runner_codex=run_codex, runner_claude=run_claude) -> None:
        self.run_codex = runner_codex
        self.run_claude = runner_claude
        self.last: Budget | None = None

    def complete(self, req: ModelRequest, timeout: float) -> ModelResponse:
        tried: list[str] = []
        for _ in range(2):
            b = decide(_family(req.model))
            self.last = b
            if b.plan is None or b.plan in tried:
                raise ProviderError("quota", b.reason or "no plan has usage left", "plan")
            tried.append(b.plan)
            system = f"{req.system}\n\n{b.note()}"
            started = time.monotonic()
            try:
                if b.plan == "codex":
                    text, it, ot = self.run_codex(system, req.prompt, b.model, b.effort, timeout * 4)
                else:
                    text, it, ot = self.run_claude(system, req.prompt, b.model, timeout * 4)
            except ProviderError as exc:
                if exc.kind == "quota":
                    continue  # that plan just ran out; decide() now skips it
                raise
            return ModelResponse(text, f"{b.plan}_plan", b.model or f"{b.plan}-default", it, ot, 0.0,
                                 int((time.monotonic() - started) * 1000), "end_turn",
                                 {**self.capabilities, "plan": b.plan, "why": b.reason, "owner_active": b.owner_active})
        raise ProviderError("quota", "both plans are out of usage", "plan")

