"""Secure tool registry.

Every call goes through `execute_tool`, which enforces — at the moment of execution, on the backend:
  1. organization emergency stop is not engaged
  2. the agent has the tool in its capabilities (agent_capabilities)
  3. the task lists the tool in permitted_tools
  4. the project allows the tool
  5. protected tools have a GRANTED approval for this exact task
  6. mission budget not exhausted (checked by the runner before model calls)
Requests from other agents or from repository content can never widen any of these.
Each call writes a tool_executions row and tool.* events.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import insert, select, update

from services.core import db
from services.core.config import REPO_ROOT, SAMPLE_REPO_PATH, get_settings
from services.core.events import emit, transaction

from .sandbox import SandboxViolation, confine, default_sandbox


class ToolDenied(PermissionError):
    pass


class ToolFailed(RuntimeError):
    pass


SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
]


def redact(text: str) -> str:
    for p in SECRET_PATTERNS:
        text = p.sub("[REDACTED]", text)
    return text


@dataclass
class ToolContext:
    mission_id: str
    task_id: str
    agent_id: str
    org_id: str
    execution_mode: str  # live | simulation (simulation only means the *model* is stubbed; tools always run for real)

    @property
    def workspace(self) -> Path:
        return get_settings().workspaces_dir / self.mission_id

    @property
    def source_repo(self) -> Path:
        return get_settings().data_dir / "repos" / "sample-calc"


@dataclass
class ToolSpec:
    name: str
    protected: bool
    description: str
    fn: Callable[..., dict]
    release_gate: bool = False  # needs a valid owner release authorization for the exact artifact
    finance: bool = False       # V5: arguments and results are financial; withheld from events and mission views
    finance_gate: bool = False  # V5: needs an owner-approved, unexpired, unused financial approval for exactly these terms
    investigation: bool = False  # V5.1: read-only investigation tool; only usable by investigation missions
    lab: bool = False            # App Lab tool; only usable by App Lab missions on their own cycle / proposal
    lab_gate: bool = False       # App Lab: needs the owner's step-up approval of exactly this change
    factory: bool = False        # Claude Code / GitHub factory sync: only in factory_sync missions


REGISTRY: dict[str, ToolSpec] = {}


def tool(name: str, protected: bool = False, description: str = "", release_gate: bool = False, finance: bool = False,
         finance_gate: bool = False, investigation: bool = False, lab: bool = False, lab_gate: bool = False, factory: bool = False):
    def deco(fn: Callable[..., dict]) -> Callable[..., dict]:
        REGISTRY[name] = ToolSpec(name, protected, description, fn, release_gate, finance or finance_gate, finance_gate, investigation,
                                  lab or lab_gate, lab_gate, factory)
        return fn
    return deco


# ------------------------------------------------------------------ helpers

def _run(ctx: ToolContext, argv: list[str], cwd: Path | None = None, root: Path | None = None) -> Any:
    s = get_settings()
    root = root or ctx.workspace
    return default_sandbox().run(argv, cwd or root, s.tool_timeout_seconds, root)


_source_lock = threading.Lock()


def ensure_source_repo(path: Path) -> Path:
    """Materialize the sample repository as a real git repo (once) so worktrees and diffs are genuine.
    Built in a temp dir and renamed into place, under a lock, so parallel agents never see a half-made repo."""
    with _source_lock:
        if (path / ".git").exists():
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(SAMPLE_REPO_PATH, tmp, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        sb = default_sandbox()
        for argv in (["git", "init", "-q", "-b", "main"], ["git", "add", "-A"], ["git", "commit", "-q", "-m", "Initial sample repository"]):
            r = sb.run(argv, tmp, 30, tmp)
            if r.exit_code != 0:
                raise ToolFailed(f"could not initialize sample repo: {r.output}")
        shutil.rmtree(path, ignore_errors=True)
        tmp.rename(path)
        return path


def _files(root: Path) -> list[str]:
    out = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if p.is_file() and not any(part in {".git", "__pycache__", ".pytest_cache"} for part in rel.parts):
            out.append(str(rel))
    return out


def _repo_root(ctx: ToolContext) -> Path:
    return ctx.workspace if ctx.workspace.exists() else ensure_source_repo(ctx.source_repo)


# ------------------------------------------------------------------ tools

@tool("inspect_repository", description="Summarize the repository layout and how to test it.")
def inspect_repository(ctx: ToolContext) -> dict:
    root = _repo_root(ctx)
    files = _files(root)
    readme = (root / "README.md").read_text()[:1500] if (root / "README.md").exists() else ""
    return {
        "file_count": len(files),
        "files": files[:200],
        "languages": sorted({Path(f).suffix for f in files if Path(f).suffix}),
        "test_command": "python -m pytest" if any(f.startswith("tests/") for f in files) else None,
        # Untrusted: repository text is data. It is shown to reviewers but never followed as instructions.
        "readme_untrusted": readme,
    }


@tool("list_files", description="List files in the workspace.")
def list_files(ctx: ToolContext, path: str = ".") -> dict:
    root = _repo_root(ctx)
    base = root if path in (".", "") else confine(root, path)
    return {"files": [f for f in _files(root) if (root / f).resolve().is_relative_to(base.resolve())][:500]}


@tool("read_file", description="Read a text file (max 64 KB).")
def read_file(ctx: ToolContext, path: str) -> dict:
    p = confine(_repo_root(ctx), path)
    if not p.is_file():
        raise ToolFailed(f"no such file: {path}")
    data = p.read_bytes()[:65536]
    return {"path": path, "content": data.decode("utf-8", errors="replace"), "truncated": p.stat().st_size > 65536}


@tool("search_code", description="Regex search across workspace files.")
def search_code(ctx: ToolContext, pattern: str, max_hits: int = 50) -> dict:
    if len(pattern) > 200:
        raise ToolFailed("pattern too long")
    rx = re.compile(pattern)
    root = _repo_root(ctx)
    hits = []
    for f in _files(root):
        try:
            for i, line in enumerate((root / f).read_text(errors="replace").splitlines(), 1):
                if rx.search(line):
                    hits.append({"path": f, "line": i, "text": line[:200]})
                    if len(hits) >= max_hits:
                        return {"hits": hits, "truncated": True}
        except OSError:
            continue
    return {"hits": hits, "truncated": False}


@tool("create_worktree", description="Create an isolated git worktree on a mission branch.")
def create_worktree(ctx: ToolContext) -> dict:
    src = ensure_source_repo(ctx.source_repo)
    branch = f"mission/{ctx.mission_id[:8]}"
    if ctx.workspace.exists():
        return {"path": str(ctx.workspace.name), "branch": branch, "reused": True}
    root = get_settings().data_dir
    r = _run(ctx, ["git", "-C", str(src), "worktree", "add", "-q", "-b", branch, str(ctx.workspace)], cwd=src, root=root)
    if r.exit_code != 0:
        raise ToolFailed(f"worktree failed: {r.output}")
    return {"path": ctx.workspace.name, "branch": branch, "reused": False, "network_isolated": r.network_isolated}


@tool("edit_file", description="Replace one exact occurrence of `old` with `new` in a workspace file.")
def edit_file(ctx: ToolContext, path: str, old: str, new: str) -> dict:
    if not ctx.workspace.exists():
        raise ToolFailed("no worktree; create_worktree first")
    p = confine(ctx.workspace, path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise ToolFailed(f"`old` must match exactly once in {path}, matched {count} times")
    p.write_text(text.replace(old, new, 1))
    return {"path": path, "bytes_before": len(text), "bytes_after": len(text) - len(old) + len(new)}


_SUMMARY = re.compile(r"(\d+) (passed|failed|error|errors|skipped)")


def _parse_pytest(output: str) -> dict:
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    tail = output.strip().splitlines()[-1] if output.strip() else ""
    for n, kind in _SUMMARY.findall(tail):
        counts["errors" if kind.startswith("error") else kind] += int(n)
    failing = re.findall(r"^FAILED (\S+)", output, re.M)
    return {**counts, "failing_tests": failing, "summary_line": tail}


@tool("run_tests", description="Run the repository's pytest suite inside the sandbox.")
def run_tests(ctx: ToolContext) -> dict:
    root = _repo_root(ctx)
    r = _run(ctx, ["python", "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider"], cwd=root, root=root)
    parsed = _parse_pytest(r.stdout)
    return {"exit_code": r.exit_code, "timed_out": r.timed_out, "duration_ms": r.duration_ms,
            "network_isolated": r.network_isolated, **parsed, "output": redact(r.output)[-6000:]}


@tool("run_build", description="Byte-compile all Python sources (syntax check).")
def run_build(ctx: ToolContext) -> dict:
    root = _repo_root(ctx)
    r = _run(ctx, ["python", "-m", "compileall", "-q", "."], cwd=root, root=root)
    return {"exit_code": r.exit_code, "output": redact(r.output)[-3000:]}


@tool("inspect_diff", description="Show the git diff of the mission worktree.")
def inspect_diff(ctx: ToolContext) -> dict:
    if not ctx.workspace.exists():
        return {"diff": "", "files_changed": 0}
    r = _run(ctx, ["git", "diff", "--no-color"])
    stat = _run(ctx, ["git", "diff", "--numstat"])
    return {"diff": redact(r.stdout), "files_changed": len([l for l in stat.stdout.splitlines() if l.strip()])}


@tool("create_artifact", description="Store an artifact for the mission.")
def create_artifact(ctx: ToolContext, kind: str, title: str, content: str) -> dict:
    if kind not in {"diff", "test_report", "patch", "note", "plan"}:
        raise ToolFailed("unknown artifact kind")
    aid = db.new_id()
    with transaction() as conn:
        conn.execute(insert(db.artifacts).values(id=aid, organization_id=ctx.org_id, mission_id=ctx.mission_id,
                                                 task_id=ctx.task_id, agent_id=ctx.agent_id, kind=kind, title=title,
                                                 content=redact(content)[:200_000]))
        emit(conn, "artifact.created", mission_id=ctx.mission_id, agent_id=ctx.agent_id, execution_mode=ctx.execution_mode,
             payload={"artifact_id": aid, "kind": kind, "title": title})
    return {"artifact_id": aid}


@tool("prepare_pull_request", protected=True, description="Commit the change on the mission branch and package a reviewable patch.")
def prepare_pull_request(ctx: ToolContext, title: str, body: str) -> dict:
    if not ctx.workspace.exists():
        raise ToolFailed("no worktree to publish")
    add = _run(ctx, ["git", "add", "-A"])
    staged = _run(ctx, ["git", "diff", "--cached", "--name-only"]).stdout.strip()
    already = _run(ctx, ["git", "log", "-1", "--format=%s"]).stdout.strip() == title[:120]
    if staged or not already:  # a retried task finds its commit already made and goes straight to publishing
        commit = _run(ctx, ["git", "commit", "-q", "-m", title[:120], "-m", body[:2000]])
        if add.exit_code or commit.exit_code:
            raise ToolFailed(f"commit failed: {commit.output}")
    sha = _run(ctx, ["git", "rev-parse", "HEAD"]).stdout.strip()
    patch = _run(ctx, ["git", "log", "-1", "-p", "--no-color", "--format=From %H%nSubject: %s%n%n%b"]).stdout
    out = {"branch": f"mission/{ctx.mission_id[:8]}", "commit": sha, "patch": redact(patch)[:100_000], "remote": None}
    # With AICIV_GITHUB_REPO set, the same commit also becomes a real draft pull request (services/integrations/github.py).
    # Without it, the "pull request" is the committed mission branch + patch artifact.
    from services.integrations.github import GitHubPublisher, PublishError, PublishTarget

    try:
        target = PublishTarget.from_env()
        if target is None:
            return out
        diff = _run(ctx, ["git", "diff", "--no-color", "HEAD~1", "HEAD"])
        if diff.exit_code:
            raise ToolFailed(f"could not read the mission diff: {diff.output}")
        pr = GitHubPublisher(target, get_settings().data_dir / "github").publish(
            ctx.mission_id, diff.stdout, title, body + f"\n\n---\nOpened by AI Civilization mission `{ctx.mission_id}` after the owner approved publication.")
    except PublishError as exc:
        raise ToolFailed(f"GitHub publish failed: {exc}") from exc
    return {**out, "remote": "github", "repo": pr["repo"], "pr_number": pr["pr_number"], "pr_url": pr["pr_url"],
            "pr_branch": pr["branch"], "pr_base": pr["base"], "pr_commit": pr["commit"], "pr_created": pr["created"]}


APPROVED_SOURCES = {"architecture": REPO_ROOT / "docs" / "architecture" / "overview.md"}


@tool("retrieve_approved_source", description="Read a document from the approved-source allowlist.")
def retrieve_approved_source(ctx: ToolContext, source: str) -> dict:
    p = APPROVED_SOURCES.get(source)
    if not p or not p.exists():
        raise ToolFailed(f"source not approved: {source}")
    return {"source": source, "content": p.read_text()[:20000]}


# ------------------------------------------------------------------ enforcement

def _check_permissions(conn, ctx: ToolContext, spec: ToolSpec, args: dict | None = None) -> None:
    org = conn.execute(select(db.organizations).where(db.organizations.c.id == ctx.org_id)).first()
    if org is None or org.emergency_stopped:
        raise ToolDenied("emergency stop engaged")
    caps = {r.tool_name for r in conn.execute(select(db.agent_capabilities.c.tool_name).where(db.agent_capabilities.c.agent_id == ctx.agent_id))}
    if spec.name not in caps:
        raise ToolDenied(f"agent lacks capability {spec.name}")
    task = conn.execute(select(db.tasks).where(db.tasks.c.id == ctx.task_id)).first()
    if task is None or task.mission_id != ctx.mission_id or task.agent_id != ctx.agent_id:
        raise ToolDenied("task does not belong to this agent and mission")
    if spec.name not in (task.permitted_tools or []):
        raise ToolDenied(f"task does not permit {spec.name}")
    mission = conn.execute(select(db.missions).where(db.missions.c.id == ctx.mission_id)).first()
    project = conn.execute(select(db.projects).where(db.projects.c.id == mission.project_id)).first()
    if spec.name not in (project.allowed_tools or []):
        raise ToolDenied(f"project does not allow {spec.name}")
    if mission.status in {"CANCELLED", "FAILED", "COMPLETED"}:
        raise ToolDenied(f"mission is {mission.status}")
    if spec.protected:
        granted = conn.execute(select(db.approvals.c.id).where(
            db.approvals.c.task_id == ctx.task_id, db.approvals.c.status == "GRANTED")).first()
        if not granted:
            raise ToolDenied(f"{spec.name} is protected and has no granted approval")
    _check_investigation(conn, ctx, spec, mission, args or {})
    _check_lab(conn, ctx, spec, mission, args or {})
    if (mission.kind == "factory_sync") != spec.factory and (spec.factory or spec.name not in FACTORY_SHARED):
        raise ToolDenied(f"{spec.name} is not allowed here: factory sync missions use factory tools only, and factory tools run only there")
    if spec.finance or spec.name == "request_purchase":
        _check_finance(conn, ctx, spec, mission, args or {})
    if spec.release_gate:
        from services.management.release import ReleaseDenied, check_authorization
        try:
            check_authorization(conn, ctx.org_id, (args or {}).get("authorization_id", ""), mission.opportunity_id)
        except ReleaseDenied as exc:
            raise ToolDenied(f"release refused: {exc}") from exc


INVESTIGATION_TOOLS = {"investigate_alternatives", "score_alternatives", "sandbox_evaluate_candidate", "review_sandbox_evidence"}


def _check_investigation(conn, ctx: ToolContext, spec: ToolSpec, mission, args: dict) -> None:
    """V5.1: an investigation authorizes research and sandboxed evaluation only. Its missions can use nothing else
    (no purchases, payments, cancellations, pull requests, releases or deployments), and its tools work only for
    the investigation the mission was created for, while that investigation is still running."""
    from services.orchestrator.plan import INVESTIGATION_KINDS

    in_investigation = mission.kind in INVESTIGATION_KINDS
    if in_investigation and spec.name not in INVESTIGATION_TOOLS:
        raise ToolDenied(f"{spec.name} is not allowed in a read-only investigation")
    if spec.investigation:
        if not in_investigation:
            raise ToolDenied(f"{spec.name} only runs inside an owner-requested investigation")
        inv_id = (mission.params or {}).get("investigation_id")
        if not inv_id or args.get("investigation_id") != inv_id:
            raise ToolDenied("this mission is not working on that investigation")
        inv = conn.execute(select(db.savings_investigations).where(db.savings_investigations.c.id == inv_id)).first()
        if inv is None or inv.status not in ("RESEARCHING", "EVALUATING", "TESTING"):
            raise ToolDenied(f"investigation is {inv.status.lower() if inv else 'missing'}")


LAB_TOOLS = {"research_design_insights", "scan_repository", "propose_improvements", "refine_proposal", "draft_patch", "publish_lab_change",
             "read_claude_code_memory"}
FACTORY_SHARED = {"read_claude_code_memory"}
LAB_STAGE = {"research_design_insights": ("lab_research", "RESEARCHING"), "scan_repository": ("lab_analyze", "ANALYZING"),
             "propose_improvements": ("lab_analyze", "ANALYZING"), "refine_proposal": ("lab_analyze", "ANALYZING"),
             "draft_patch": ("lab_analyze", "ANALYZING"), "publish_lab_change": ("lab_publish", None)}


def _check_lab(conn, ctx: ToolContext, spec: ToolSpec, mission, args: dict) -> None:
    """App Lab: its missions can use only App Lab tools; each tool works only for the cycle (or proposal) its mission
    was created for, at the right stage; publishing needs the owner's step-up approval of exactly this change."""
    from services.orchestrator.plan import LAB_KINDS

    in_lab = mission.kind in LAB_KINDS
    if in_lab and spec.name not in LAB_TOOLS:
        raise ToolDenied(f"{spec.name} is not allowed in an App Lab mission")
    if not spec.lab:
        return
    kind, stage = LAB_STAGE[spec.name]
    if mission.kind != kind:
        raise ToolDenied(f"{spec.name} only runs in a {kind} mission")
    params = mission.params or {}
    if spec.lab_gate:
        if not params.get("proposal_id") or args.get("proposal_id") != params.get("proposal_id"):
            raise ToolDenied("this mission was not created for that proposal")
        from services.applab.lab import LabRefused, authorize_publish
        try:
            p, _ = authorize_publish(conn, args["proposal_id"], ctx.org_id)
        except LabRefused as exc:
            raise ToolDenied(f"publishing refused: {exc}") from exc
        if p.publish_mission_id != ctx.mission_id:
            raise ToolDenied("the owner's approval was issued to a different mission")
        if args.get("payload_hash") != p.payload_hash:
            raise ToolDenied("publishing refused: the change differs from what the owner approved")
        return
    if not params.get("cycle_id") or args.get("cycle_id") != params.get("cycle_id"):
        raise ToolDenied("this mission is not working on that App Lab cycle")
    c = conn.execute(select(db.lab_cycles).where(db.lab_cycles.c.id == params["cycle_id"])).first()
    if c is None or c.status != stage:
        raise ToolDenied(f"App Lab cycle is {c.status.lower() if c else 'missing'}")
    repo = conn.execute(select(db.lab_repositories).where(db.lab_repositories.c.id == c.repository_id)).first()
    if repo is None or repo.status != "ACTIVE":
        raise ToolDenied("repository is not authorized for the App Lab")


def _check_finance(conn, ctx: ToolContext, spec: ToolSpec, mission, args: dict) -> None:
    """THREAT_MODEL F4, F7: department, packet scoping and (for execution) the owner's exact approval."""
    from services.finance.permissions import RESEARCH_SHARED_TOOLS

    if spec.finance:
        dept = conn.execute(select(db.departments.c.key).join(db.agents, db.agents.c.department_id == db.departments.c.id)
                            .where(db.agents.c.id == ctx.agent_id)).scalar()
        allowed = {"finance", "research"} if spec.name in RESEARCH_SHARED_TOOLS else {"finance"}
        if dept not in allowed:
            raise ToolDenied(f"{spec.name} is restricted to the {' or '.join(sorted(allowed))} department")
    params = mission.params or {}
    if "packet_id" in args and params.get("packet_id") != args.get("packet_id"):
        raise ToolDenied("this mission is not working on that cost review")
    if spec.finance_gate:
        from services.finance.approvals import ApprovalRefused, authorize_execution

        if params.get("approval_id") != args.get("approval_id"):
            raise ToolDenied("this mission was not created for that approval")
        try:
            authorize_execution(conn, org_id=ctx.org_id, approval_id=args.get("approval_id", ""), action_type=args.get("action_type", ""),
                                amount_minor=int(args.get("amount_minor", -1)), currency=str(args.get("currency", "")),
                                recipient=str(args.get("recipient", "")), account_ref=str(args.get("account_ref", "")))
        except ApprovalRefused as exc:
            raise ToolDenied(f"financial action refused: {exc}") from exc


def execute_tool(ctx: ToolContext, name: str, args: dict | None = None) -> dict:
    args = args or {}
    spec = REGISTRY.get(name)
    if spec is None:
        raise ToolDenied(f"unknown tool {name}")
    exec_id = db.new_id()
    safe_args = json.loads(redact(json.dumps(args)))
    if spec.finance or name == "request_purchase":  # THREAT_MODEL F9: money stays in the bank's own records
        safe_args = {k: v for k, v in args.items() if k in ("packet_id", "approval_id")} | {"withheld": "financial arguments"}
    denied: ToolDenied | None = None
    with transaction() as conn:
        try:
            _check_permissions(conn, ctx, spec, args)
        except ToolDenied as exc:
            denied = exc
    if denied is not None:
        # Recorded in its own transaction so the audit row survives the refusal.
        with transaction() as conn:
            conn.execute(insert(db.tool_executions).values(id=exec_id, organization_id=ctx.org_id, mission_id=ctx.mission_id,
                                                           task_id=ctx.task_id, agent_id=ctx.agent_id, tool_name=name,
                                                           arguments=safe_args, status="DENIED", output_excerpt=str(denied),
                                                           finished_at=db.utcnow()))
            emit(conn, "tool.failed", mission_id=ctx.mission_id, agent_id=ctx.agent_id, execution_mode=ctx.execution_mode,
                 payload={"tool_execution_id": exec_id, "tool": name, "denied": True, "error": str(denied)})
        raise denied
    with transaction() as conn:
        # Re-checked inside the same transaction that records the start, so nothing can change in between.
        _check_permissions(conn, ctx, spec, args)
        conn.execute(insert(db.tool_executions).values(id=exec_id, organization_id=ctx.org_id, mission_id=ctx.mission_id,
                                                       task_id=ctx.task_id, agent_id=ctx.agent_id, tool_name=name,
                                                       arguments=safe_args, status="RUNNING"))
        emit(conn, "tool.started", mission_id=ctx.mission_id, agent_id=ctx.agent_id, execution_mode=ctx.execution_mode,
             payload={"tool_execution_id": exec_id, "tool": name, "arguments": safe_args, "protected": spec.protected or spec.release_gate})
    started = time.monotonic()
    try:
        result = spec.fn(ctx, **args)
        status, error = "COMPLETED", None
    except (ToolFailed, SandboxViolation, OSError, re.error, TypeError, ValueError) as exc:
        result, status, error = {}, "FAILED", f"{type(exc).__name__}: {exc}"
    duration = int((time.monotonic() - started) * 1000)
    excerpt = redact(json.dumps(result, default=str))[:4000] if status == "COMPLETED" else error
    if (spec.factory or name in FACTORY_SHARED) and status == "COMPLETED":  # transcript-derived data stays out of the tool log
        excerpt = json.dumps({k: v for k, v in result.items() if k in ("status", "count", "memory_files", "completed_tasks")})
    elif spec.lab and status == "COMPLETED":
        excerpt = json.dumps({k: v for k, v in result.items() if k in ("cycle_id", "proposal_id", "status", "count", "base_sha", "stack",
                                                                         "file_count", "kind", "number", "url", "data_mode", "detail")})
    elif (spec.finance or spec.investigation) and status == "COMPLETED":
        excerpt = json.dumps({k: v for k, v in result.items() if k in ("packet_id", "approval_id", "investigation_id", "status", "action",
                                                                         "count", "data_mode", "verdict", "passed", "failed", "errors")})
    with transaction() as conn:
        conn.execute(update(db.tool_executions).where(db.tool_executions.c.id == exec_id).values(
            status=status, exit_code=result.get("exit_code") if isinstance(result, dict) else None,
            output_excerpt=excerpt, duration_ms=duration, finished_at=db.utcnow()))
        emit(conn, "tool.completed" if status == "COMPLETED" else "tool.failed", mission_id=ctx.mission_id, agent_id=ctx.agent_id,
             execution_mode=ctx.execution_mode,
             payload={"tool_execution_id": exec_id, "tool": name, "duration_ms": duration,
                      **({"error": error} if error else {"summary": _summarize(name, result)})})
    if status == "FAILED":
        raise ToolFailed(error or "tool failed")
    return result


def _summarize(name: str, result: dict) -> str:
    if name == "run_tests":
        return result.get("summary_line", "")
    if name == "inspect_diff":
        return f"{result.get('files_changed', 0)} file(s) changed"
    if name == "inspect_repository":
        return f"{result.get('file_count')} files"
    if name == "publish_lab_change":
        return f"{'draft pull request' if result.get('kind') == 'pr' else 'Claude Code issue'} #{result.get('number')} {result.get('url')}"
    if name == "prepare_pull_request":
        if result.get("pr_url"):
            return f"draft pull request #{result.get('pr_number')} {result.get('pr_url')}"
        return f"commit {str(result.get('commit', ''))[:10]} on {result.get('branch')}"
    return "ok"

from . import studio_tools  # noqa: E402,F401  (registers the V4 tools)
from services.finance import tools as _finance_tools  # noqa: E402,F401  (registers the V5 financial tools)
from services.finance import investigation_tools as _investigation_tools  # noqa: E402,F401  (V5.1)
from services.applab import tools as _applab_tools  # noqa: E402,F401  (App Lab)
from services.factories import tools as _factory_tools  # noqa: E402,F401  (Claude Code and GitHub factories)
