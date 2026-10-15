"""App Lab tools. `_check_lab` in services/tools/registry.py confines them to App Lab missions working on that
cycle or proposal; `publish_lab_change` additionally needs the owner's approval of the exact change."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile

from sqlalchemy import select, update

from services.core import db
from services.core.events import transaction
from services.tools.registry import ToolContext, ToolFailed, tool

from . import lab as L
from .pipeline import cycle, lemit


def _repo_for_cycle(conn, cycle_id: str):
    c = cycle(conn, cycle_id)
    if c is None:
        raise ToolFailed("unknown App Lab cycle")
    return c, L.repo_row(conn, c.repository_id)


@tool("research_design_insights", lab=True,
      description="Collect app design patterns that people engage with, pay for and play, with attributed evidence.")
def research_design_insights(ctx: ToolContext, cycle_id: str) -> dict:
    with transaction() as conn:
        c, repo = _repo_for_cycle(conn, cycle_id)
        conn.execute(db.design_insights.delete().where(db.design_insights.c.cycle_id == cycle_id))  # idempotent on retry
        ids = L.research_insights(conn, c, ["unknown"])  # every pattern; the analysis matches them to the codebase
        modes = {r.data_mode for r in conn.execute(select(db.design_insights.c.data_mode).where(db.design_insights.c.cycle_id == cycle_id))}
        L.record(conn, org=ctx.org_id, actor_type="agent", actor_id=ctx.agent_id, action="lab.insights_collected", subject_id=cycle_id,
                 detail={"count": len(ids)})
    return {"cycle_id": cycle_id, "count": len(ids), "data_mode": "live" if "live" in modes else "fixture"}


@tool("scan_repository", lab=True, description="Read the authorized repository (read-only): stack, files, README, head commit.")
def scan_repository(ctx: ToolContext, cycle_id: str) -> dict:
    with db.get_engine().connect() as conn:
        c, repo = _repo_for_cycle(conn, cycle_id)
    try:
        root, sha = L.checkout(repo)
    except (L.LabRefused, L.PublishError) as exc:
        with transaction() as conn:
            conn.execute(update(db.lab_repositories).where(db.lab_repositories.c.id == repo.id).values(last_error=str(exc)[:500]))
        raise ToolFailed(f"could not read the repository: {exc}") from exc
    info = L.scan(root)
    with transaction() as conn:
        conn.execute(update(db.lab_repositories).where(db.lab_repositories.c.id == repo.id).values(
            head_sha=sha, last_scan_at=db.utcnow(), claude_code_ready=1 if info["claude_code_ready"] else 0, last_error=None))
    return {"cycle_id": cycle_id, "base_sha": sha, "file_count": len(info["files"]), "stack": info["stack"],
            "claude_code_ready": info["claude_code_ready"], "files": info["files"][:400], "readme": info["readme"]}


def _apply_check(root, patch: str) -> tuple[bool, str]:
    """`git apply --check` in a throwaway copy: validates the patch, executes nothing from the repository."""
    work = tempfile.mkdtemp(prefix="lab-check-")
    try:
        shutil.copytree(root, os.path.join(work, "r"), symlinks=True, ignore=shutil.ignore_patterns(".git"))
        pf = os.path.join(work, "change.patch")
        with open(pf, "w") as fh:
            fh.write(patch if patch.endswith("\n") else patch + "\n")
        p = subprocess.run(["git", "apply", "--check", "--whitespace=nowarn", pf], cwd=os.path.join(work, "r"), capture_output=True,
                           text=True, timeout=60, env={"PATH": os.environ.get("PATH", ""), "HOME": work})
        return p.returncode == 0, (p.stderr or p.stdout).strip()[:500]
    finally:
        shutil.rmtree(work, ignore_errors=True)


@tool("propose_improvements", lab=True, description="Turn this cycle's design insights into concrete, reviewable proposals.")
def propose_improvements(ctx: ToolContext, cycle_id: str, max_proposals: int = 3) -> dict:
    with db.get_engine().connect() as conn:
        c, repo = _repo_for_cycle(conn, cycle_id)
        insights = conn.execute(select(db.design_insights).where(db.design_insights.c.cycle_id == cycle_id)).fetchall()
        existing = conn.execute(select(db.lab_proposals.c.id).where(db.lab_proposals.c.cycle_id == cycle_id)).fetchall()
    if existing:  # a retried task does not duplicate proposals
        return {"cycle_id": cycle_id, "count": len(existing), "status": "already proposed"}
    root, sha = L.checkout(repo)
    info = L.scan(root)
    authored = "simulation template" if c.data_mode == "simulated" else "rules template"
    made = []
    with transaction() as conn:
        if not info["claude_code_ready"]:
            patch = L.workflow_patch(repo)
            ok, msg = _apply_check(root, patch)
            pid = L.make_proposal(conn, cycle=c, repo=repo, insight=None, files=[L.WORKFLOW_PATH], base_sha=sha, route="patch", patch=patch,
                                  title="Install the Claude Code GitHub Action",
                                  summary="Adds Anthropic's Claude Code GitHub Action so App Lab issues labeled 'claude' become pull requests. "
                                          "It uses your CLAUDE_CODE_OAUTH_TOKEN repository secret (from `claude setup-token`); add that secret "
                                          "in the repository settings before merging.",
                                  plan=["Add .github/workflows/aiciv-claude-code.yml (pinned template)",
                                        "Add the CLAUDE_CODE_OAUTH_TOKEN secret in GitHub → Settings → Secrets and variables → Actions",
                                        "Review and merge the draft pull request"], authored_by="pinned template", risk="medium")
            conn.execute(update(db.lab_proposals).where(db.lab_proposals.c.id == pid).values(checks={"applies": ok, "detail": msg}))
            made.append(pid)
        ranked = sorted(insights, key=lambda i: -sum({"high": 2, "medium": 1}.get(v, 0) for v in (i.signals or {}).values()))
        for ins in ranked[: max(0, int(max_proposals))]:
            hint = next((p["files_hint"] for p in L.patterns()["patterns"] if p["id"] == ins.pattern), [])
            pid = L.make_proposal(conn, cycle=c, repo=repo, insight=ins, files=L.relevant_files(info["files"], hint), base_sha=sha,
                                  route="claude_code", patch=None, authored_by=authored)
            made.append(pid)
        L.record(conn, org=ctx.org_id, actor_type="agent", actor_id=ctx.agent_id, action="lab.proposals_drafted", subject_id=cycle_id,
                 detail={"count": len(made), "base_sha": sha})
    return {"cycle_id": cycle_id, "count": len(made), "base_sha": sha, "proposal_ids": made, "status": "proposed"}


def _proposal(conn, proposal_id: str):
    p = conn.execute(select(db.lab_proposals).where(db.lab_proposals.c.id == proposal_id)).first()
    if p is None:
        raise ToolFailed("unknown proposal")
    if p.status != "PROPOSED":
        raise ToolFailed(f"proposal is {p.status.lower()}; it can no longer be edited")
    return p


@tool("refine_proposal", lab=True, description="Tailor a proposal's summary and plan to the repository (before review).")
def refine_proposal(ctx: ToolContext, cycle_id: str, proposal_id: str, summary: str, plan: list, model: str = "") -> dict:
    with transaction() as conn:
        p = _proposal(conn, proposal_id)
        if p.cycle_id != cycle_id:
            raise ToolFailed("proposal belongs to another cycle")
        c, repo = _repo_for_cycle(conn, cycle_id)
        plan = [str(s)[:200] for s in plan][:8] or (p.plan or [])
        summary = summary.strip()[:2000] or p.summary
        instructions = L.instructions_for(repo, p.title, summary, plan, p.files or []) if p.route == "claude_code" else None
        conn.execute(update(db.lab_proposals).where(db.lab_proposals.c.id == proposal_id).values(
            summary=summary, plan=plan, instructions=instructions, authored_by=model or p.authored_by,
            payload_hash=L.payload_hash(repo=repo.full_name, base_sha=p.base_sha, route=p.route, title=p.title, patch=p.patch,
                                        instructions=instructions), updated_at=db.utcnow()))
    return {"proposal_id": proposal_id, "status": "refined"}


@tool("draft_patch", lab=True, description="Attach a unified diff to a proposal after `git apply --check` passes in a throwaway copy.")
def draft_patch(ctx: ToolContext, cycle_id: str, proposal_id: str, patch: str, model: str = "") -> dict:
    with db.get_engine().connect() as conn:
        p = _proposal(conn, proposal_id)
        c, repo = _repo_for_cycle(conn, cycle_id)
    if p.cycle_id != cycle_id:
        raise ToolFailed("proposal belongs to another cycle")
    paths = L.patch_paths(patch)
    if not paths:
        raise ToolFailed("the patch changes no files")
    bad = sorted(x for x in paths if L.FORBIDDEN.search(x) or x.startswith("/") or ".." in x.split("/"))
    if bad:
        raise ToolFailed(f"the patch touches protected paths: {', '.join(bad)}")
    root, sha = L.checkout(repo)
    if sha != p.base_sha:
        raise ToolFailed("the repository moved since the proposal was drafted")
    ok, msg = _apply_check(root, patch)
    if not ok:
        return {"proposal_id": proposal_id, "status": "patch_rejected", "detail": msg}
    with transaction() as conn:
        conn.execute(update(db.lab_proposals).where(db.lab_proposals.c.id == proposal_id, db.lab_proposals.c.status == "PROPOSED").values(
            route="patch", patch=patch, patch_sha256=hashlib.sha256(patch.encode()).hexdigest(), instructions=None,
            files=sorted(paths)[:20], checks={"applies": True, "detail": "git apply --check passed"}, authored_by=model or p.authored_by,
            payload_hash=L.payload_hash(repo=repo.full_name, base_sha=p.base_sha, route="patch", title=p.title, patch=patch, instructions=None),
            updated_at=db.utcnow()))
    return {"proposal_id": proposal_id, "status": "patch_attached"}


@tool("publish_lab_change", lab=True, lab_gate=True,
      description="Publish an owner-approved App Lab change: a draft PR on an aiciv/lab-* branch, or a Claude Code issue.")
def publish_lab_change(ctx: ToolContext, proposal_id: str, payload_hash: str) -> dict:
    # Single use: APPROVED → PUBLISHING compare-and-swap, after re-checking the exact approved change.
    with transaction() as conn:
        p, repo = L.authorize_publish(conn, proposal_id, ctx.org_id)
        if p.payload_hash != payload_hash:
            raise ToolFailed("the change differs from what the owner approved")
        n = conn.execute(update(db.lab_proposals).where(db.lab_proposals.c.id == proposal_id, db.lab_proposals.c.status == "APPROVED")
                         .values(status="PUBLISHING", updated_at=db.utcnow())).rowcount
        if n != 1:
            raise ToolFailed("this approval was already used")
    try:
        out = L.publish(p, repo)
    except L.LabRefused as exc:
        with transaction() as conn:
            conn.execute(update(db.lab_proposals).where(db.lab_proposals.c.id == proposal_id).values(
                status="FAILED", tracking={"error": str(exc)[:500]}, updated_at=db.utcnow()))
            L.record(conn, org=ctx.org_id, actor_type="agent", actor_id=ctx.agent_id, action="lab.publish_failed", subject_id=proposal_id,
                     detail={"reason": str(exc)[:300]})
        raise ToolFailed(f"publishing failed: {exc}") from exc
    with transaction() as conn:
        conn.execute(update(db.lab_proposals).where(db.lab_proposals.c.id == proposal_id).values(
            status="PUBLISHED", published=out, tracking={"state": "open"}, updated_at=db.utcnow()))
        L.record(conn, org=ctx.org_id, actor_type="agent", actor_id=ctx.agent_id, action="lab.change_published", subject_id=proposal_id,
                 detail={"kind": out["kind"], "number": out["number"], "url": out["url"]})
        lemit(conn, "lab.change_published", {"proposal_id": proposal_id, "repository_id": repo.id, "repo": repo.full_name, "kind": out["kind"],
                                             "number": out["number"], "url": out["url"], "title": p.title, "data_mode": p.data_mode},
              agent_id=ctx.agent_id, mission_id=ctx.mission_id, simulated=p.data_mode == "simulated")
    return {"proposal_id": proposal_id, "status": "published", **out}
