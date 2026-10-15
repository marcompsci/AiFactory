"""App Lab core: repository access, design research, proposals, the General Manager's briefing, the owner gate and
publishing.

Safety rules (enforced here and in services/tools/registry.py, not in prompts):
* A repository is used only after the owner authorized it here, with step-up, with a token kept encrypted at rest.
* Research and analysis read the repository; they never write to it.
* Publishing needs an owner approval of the exact change: repository, base commit, route, and the patch or Claude
  Code instructions, all bound by a hash. It is re-checked inside the publishing tool and works once.
* Nothing is pushed to the default branch. Changes go to `aiciv/lab-<id>` as a draft pull request, or to an issue
  that Anthropic's Claude Code GitHub Action picks up and turns into its own pull request. Merging is the owner's,
  on GitHub.
* Patches may not touch `.github/`, `.git/` or secrets, with one exception: the pinned Claude Code workflow template,
  which the owner approves like any other change.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from functools import lru_cache
from pathlib import Path

import httpx
from sqlalchemy import select, update
from sqlalchemy.engine import Connection

from services.core import db
from services.core.config import get_settings
from services.finance import audit, crypto
from services.integrations.github import GitHubPublisher, PublishError, PublishTarget, patch_paths

FIXTURES = Path(__file__).parent / "fixtures"
WORKFLOW_PATH = ".github/workflows/aiciv-claude-code.yml"
MAX_PATCH_LINES = 400
FORBIDDEN = re.compile(r"(^|/)(\.github/|\.git/|\.env|secrets?[./]|.*\.pem$|.*\.key$|id_rsa)")
SKIP_DIRS = {".git", "node_modules", ".next", "dist", "build", ".venv", "venv", "__pycache__", "Pods", ".data"}


class LabRefused(PermissionError):
    pass


@lru_cache
def patterns() -> dict:
    return json.loads((FIXTURES / "design_patterns.json").read_text())


def workflow_template() -> str:
    return (FIXTURES / "claude-code-workflow.yml").read_text()


def git_base() -> str:
    return os.environ.get("AICIV_GITHUB_GIT_BASE", "https://github.com").rstrip("/")


def github_http() -> httpx.Client:
    """Replaced in tests with a mock transport."""
    return httpx.Client(base_url=os.environ.get("AICIV_GITHUB_API_BASE", "https://api.github.com"), timeout=30)


def repo_row(conn: Connection, repo_id: str):
    return conn.execute(select(db.lab_repositories).where(db.lab_repositories.c.id == repo_id)).first()


def publisher_for(repo) -> GitHubPublisher:
    if repo.status != "ACTIVE":
        raise LabRefused("this repository is not authorized for the App Lab")
    token = crypto.decrypt(repo.secret_ciphertext) if repo.secret_ciphertext else None
    target = PublishTarget(repo.full_name, repo.default_branch, "", "ambient" if not token else "token")
    remote = f"{git_base()}/{repo.full_name}.git"
    return GitHubPublisher(target, get_settings().data_dir / "lab" / "repos", client=github_http(), remote_url=remote, token=token)


# ------------------------------------------------------------------ read the repository (never written here)
def checkout(repo) -> tuple[Path, str]:
    pub = publisher_for(repo)
    work = get_settings().data_dir / "lab" / "scan" / repo.full_name.replace("/", "__")
    if not (work / ".git").exists():
        work.parent.mkdir(parents=True, exist_ok=True)
        pub._git(["clone", "--quiet", "--depth", "1", "--branch", repo.default_branch, pub.remote_url, str(work)])
    else:
        pub._git(["fetch", "--quiet", "--depth", "1", "origin", repo.default_branch], cwd=work)
        pub._git(["checkout", "--quiet", "--force", f"origin/{repo.default_branch}"], cwd=work)
    sha = pub._git(["rev-parse", "HEAD"], cwd=work).strip()
    return work, sha


def scan(root: Path) -> dict:
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            files.append(str((Path(dirpath) / f).relative_to(root)))
            if len(files) >= 3000:
                break
    files.sort()
    names = " ".join(files).lower()
    stack = [s for s, rx in (("ios", r"\.swift\b|project\.yml|\.xcodeproj"), ("web", r"package\.json|\.tsx?\b|next\.config"),
                             ("android", r"\.kt\b|build\.gradle"), ("python", r"\.py\b|pyproject\.toml|requirements\.txt"),
                             ("game", r"game|godot|unity|phaser|three")) if re.search(rx, names)]
    readme = next((root / f for f in files if f.lower() in ("readme.md", "readme")), None)
    has_workflow = any(re.match(r"\.github/workflows/.*claude.*\.ya?ml$", f) for f in files)
    return {"files": files, "stack": stack or ["unknown"], "readme": readme.read_text(errors="replace")[:4000] if readme else "",
            "claude_code_ready": has_workflow}


# ------------------------------------------------------------------ research: what people engage with, buy and play
def research_insights(conn: Connection, cycle, repo_stack: list[str]) -> list[str]:
    from services.core.config import load_seed

    org = cycle.organization_id or load_seed()["organization_id"]
    live = conn.execute(select(db.research_findings).where(db.research_findings.c.data_mode == "live")
                        .order_by(db.research_findings.c.created_at.desc()).limit(5)).fetchall()
    ids = []
    for p in patterns()["patterns"]:
        if not (set(p["applies_to"]) & set(repo_stack)) and "unknown" not in repo_stack:
            continue
        evidence = [{"claim": p["why"], "source_url": f"fixture://design-patterns/{p['id']}", "as_of": patterns()["as_of"], "data_mode": "fixture"}]
        evidence += [{"claim": f"Currently charting: {f.title}", "source_url": f.source_url, "as_of": f.collected_at, "data_mode": "live"}
                     for f in live[:2]]
        iid = db.new_id()
        conn.execute(db.design_insights.insert().values(id=iid, organization_id=org, cycle_id=cycle.id, pattern=p["id"], title=p["title"],
                                                        why_it_works=p["why"], signals=p["signals"], evidence=evidence,
                                                        data_mode="live" if live else "fixture"))
        ids.append(iid)
    return ids


# ------------------------------------------------------------------ proposals
def payload_hash(*, repo: str, base_sha: str | None, route: str, title: str, patch: str | None, instructions: str | None) -> str:
    body = json.dumps({"repo": repo, "base": base_sha, "route": route, "title": title,
                       "patch": hashlib.sha256((patch or "").encode()).hexdigest(),
                       "instructions": hashlib.sha256((instructions or "").encode()).hexdigest()}, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()


def instructions_for(repo, title: str, summary: str, plan: list[str], files: list[str]) -> str:
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(plan, start=1))
    where = "\n".join(f"- `{f}`" for f in files[:12]) or "- (find the right place in the codebase)"
    return (f"@claude Please implement this App Lab improvement, approved by the repository owner.\n\n## {title}\n\n{summary}\n\n"
            f"### Plan\n{steps}\n\n### Likely files\n{where}\n\n### Constraints\n"
            f"- Work on a new branch and open a pull request against `{repo.default_branch}`. Do not push to `{repo.default_branch}`.\n"
            "- Do not change `.github/`, secrets, CI, billing or deployment configuration.\n"
            "- Keep the change focused; add or update tests where the project has them.\n"
            "- Explain in the pull request what changed and how to try it.\n")


def make_proposal(conn: Connection, *, cycle, repo, insight, files: list[str], base_sha: str, route: str, patch: str | None,
                  title: str | None = None, summary: str | None = None, plan: list[str] | None = None, authored_by: str,
                  risk: str = "low") -> str:
    p = next((x for x in patterns()["patterns"] if x["id"] == insight.pattern), None) if insight else None
    title = title or (p["title"] if p else "Improvement")
    summary = summary or (p["why"] if p else "")
    plan = plan or (p["plan"] if p else [])
    instructions = instructions_for(repo, title, summary, plan, files) if route == "claude_code" else None
    pid = db.new_id()
    conn.execute(db.lab_proposals.insert().values(
        id=pid, organization_id=repo.organization_id, cycle_id=cycle.id, repository_id=repo.id, status="PROPOSED", title=title[:120],
        summary=summary[:2000], insight_ids=[insight.id] if insight else [], files=files[:20], plan=plan, risk=risk, route=route,
        base_sha=base_sha, patch=patch, patch_sha256=hashlib.sha256(patch.encode()).hexdigest() if patch else None,
        instructions=instructions, payload_hash=payload_hash(repo=repo.full_name, base_sha=base_sha, route=route, title=title[:120], patch=patch,
                                                             instructions=instructions),
        authored_by=authored_by, data_mode=cycle.data_mode))
    return pid


def relevant_files(files: list[str], hints: list[str]) -> list[str]:
    code = [f for f in files if re.search(r"\.(tsx?|jsx?|swift|kt|py|vue|svelte|dart)$", f)]
    scored = sorted(code, key=lambda f: (-sum(h in f.lower() for h in hints), len(f)))
    return [f for f in scored if any(h in f.lower() for h in hints)][:8] or scored[:5]


# ------------------------------------------------------------------ the General Manager's briefing (rules; Opus may only tighten)
def gm_rules(proposal, repo) -> dict:
    issues, notes = [], []
    if proposal.route == "patch":
        if not proposal.patch:
            issues.append("patch route without a patch")
        else:
            paths = patch_paths(proposal.patch)
            bad = [p for p in paths if FORBIDDEN.search(p) and not (p == WORKFLOW_PATH and proposal.patch_sha256 == workflow_patch_sha(repo))]
            if bad:
                issues.append(f"touches protected paths: {', '.join(sorted(bad))}")
            lines = sum(1 for ln in proposal.patch.splitlines() if ln[:1] in "+-" and not ln.startswith(("+++", "---")))
            if lines > MAX_PATCH_LINES:
                issues.append(f"{lines} changed lines is more than the {MAX_PATCH_LINES}-line review limit")
            if not (proposal.checks or {}).get("applies"):
                issues.append("the patch did not apply cleanly to the base commit in the sandbox")
    else:
        if not repo.claude_code_ready:
            notes.append("Claude Code isn't installed in this repository yet; approve the App Lab's install proposal first, or nothing will pick "
                         "the task up")
        if not (proposal.instructions or "").strip():
            issues.append("no instructions for Claude Code")
    verdict = "blocked" if issues else "recommend"
    return {"verdict": verdict, "issues": issues, "notes": notes, "method": "rules", "authorizes_publish": False}


def workflow_patch(repo) -> str:
    body = workflow_template()
    lines = body.splitlines()
    return (f"diff --git a/{WORKFLOW_PATH} b/{WORKFLOW_PATH}\nnew file mode 100644\n--- /dev/null\n+++ b/{WORKFLOW_PATH}\n"
            f"@@ -0,0 +1,{len(lines)} @@\n" + "".join(f"+{ln}\n" for ln in lines))


def workflow_patch_sha(repo) -> str:
    return hashlib.sha256(workflow_patch(repo).encode()).hexdigest()


# ------------------------------------------------------------------ owner gate
def authorize_publish(conn: Connection, proposal_id: str, org_id: str):
    """Called at the tool boundary inside the publishing transaction."""
    p = conn.execute(select(db.lab_proposals).where(db.lab_proposals.c.id == proposal_id)).first()
    if p is None or p.organization_id != org_id:
        raise LabRefused("no such proposal")
    if p.status == "PUBLISHED" or (p.published or {}).get("url"):
        raise LabRefused("this proposal was already published")
    if p.status != "APPROVED":
        raise LabRefused(f"proposal is {p.status.lower()}, not approved by the owner")
    if not p.decided_by or not p.step_up_method:
        raise LabRefused("approval lacks an owner decision with step-up verification")
    repo = repo_row(conn, p.repository_id)
    if repo is None or repo.status != "ACTIVE":
        raise LabRefused("repository is not authorized")
    expected = payload_hash(repo=repo.full_name, base_sha=p.base_sha, route=p.route, title=p.title, patch=p.patch, instructions=p.instructions)
    if expected != p.payload_hash:
        raise LabRefused("the change differs from what the owner approved")
    if p.patch and hashlib.sha256(p.patch.encode()).hexdigest() != p.patch_sha256:
        raise LabRefused("the patch was modified after approval")
    return p, repo


def publish(p, repo) -> dict:
    pub = publisher_for(repo)
    body = (f"{p.summary}\n\n" + "".join(f"- {s}\n" for s in (p.plan or [])) +
            f"\n---\nProposed by AI Civilization's App Lab, briefed by the General Manager, approved by the owner (proposal `{p.id}`).")
    try:
        if p.route == "patch":
            allow = p.patch_sha256 == workflow_patch_sha(repo)
            if allow:  # the one protected path the owner can approve: the pinned Claude Code workflow
                pub_paths = patch_paths(p.patch)
                if pub_paths != {WORKFLOW_PATH}:
                    raise LabRefused("workflow patch must contain only the pinned workflow file")
                return _publish_workflow(pub, p, body)
            out = pub.publish(p.id, p.patch, p.title, body, branch=f"aiciv/lab-{p.id[:8]}")
            return {"kind": "pr", "url": out["pr_url"], "number": out["pr_number"], "branch": out["branch"], "commit": out["commit"]}
        out = pub.create_issue(p.title, p.instructions + "\n\n" + body, ["claude", "aiciv-app-lab"])
        return {"kind": "issue", "url": out["issue_url"], "number": out["issue_number"]}
    except PublishError as exc:
        raise LabRefused(str(exc)) from exc


def _publish_workflow(pub: GitHubPublisher, p, body: str) -> dict:
    # GitHubPublisher refuses .github/ paths on purpose; this narrow path applies exactly the pinned template.
    import tempfile

    branch = f"aiciv/lab-{p.id[:8]}"
    repo_dir = pub.workdir / pub.t.repo.replace("/", "__")
    if not (repo_dir / ".git").exists():
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        pub._git(["clone", "--quiet", "--depth", "1", "--branch", pub.t.base, pub.remote_url, str(repo_dir)])
    else:
        pub._git(["fetch", "--quiet", "--depth", "1", "origin", pub.t.base], cwd=repo_dir)
    pub._git(["checkout", "--quiet", "--force", "-B", branch, f"origin/{pub.t.base}"], cwd=repo_dir)
    with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False) as fh:
        fh.write(p.patch)
        name = fh.name
    try:
        pub._git(["apply", "--index", name], cwd=repo_dir)
    finally:
        os.unlink(name)
    pub._git(["commit", "--quiet", "-m", p.title[:120], "-m", body[:4000]], cwd=repo_dir)
    commit = pub._git(["rev-parse", "HEAD"], cwd=repo_dir).strip()
    pub._git(["push", "--quiet", "--force", "origin", f"HEAD:refs/heads/{branch}"], cwd=repo_dir)
    pr = pub._open_or_find_pr(branch, p.title, body)
    return {"kind": "pr", "url": pr["pr_url"], "number": pr["pr_number"], "branch": branch, "commit": commit}


def record(conn: Connection, *, org: str, actor_type: str, actor_id: str | None, action: str, subject_id: str, detail: dict | None = None) -> None:
    audit.record(conn, org_id=org, actor_type=actor_type, actor_id=actor_id, action=action, subject_type="lab", subject_id=subject_id,
                 detail=detail or {})


def set_cycle(conn: Connection, cycle_id: str, status: str, **values) -> None:
    conn.execute(update(db.lab_cycles).where(db.lab_cycles.c.id == cycle_id).values(status=status, updated_at=db.utcnow(), **values))
