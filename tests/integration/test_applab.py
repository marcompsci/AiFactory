"""App Lab: research → proposals → General Manager → owner → (only if approved) GitHub.

GitHub is replaced by a local bare repository (git over file://) and a mock REST API, so these tests exercise the
real clone, `git apply --check`, branch push and pull-request / issue calls without network access.
Set AICIV_RECORD_ACCEPTANCE=1 to write docs/acceptance/app-lab-acceptance-log.md.
"""
import json
import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from services.applab import lab as L
from services.core import config, db
from services.finance import stepup
from tests.conftest import ROOT, wait_for
from tests.integration.test_v5_acceptance import all_events, step_up

REPO = "owner/habit-app"
TOKEN = "github_pat_" + "x" * 40  # fake; only ever compared by the mock API


def _git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


@pytest.fixture
def github(tmp_path, monkeypatch):
    """A bare repository served over file:// plus a mock GitHub REST API."""
    base = tmp_path / "gh"
    bare = base / f"{REPO}.git"
    bare.parent.mkdir(parents=True)
    _git("init", "--bare", "-q", "-b", "main", str(bare))
    src = tmp_path / "src"
    (src / "app" / "home").mkdir(parents=True)
    (src / "README.md").write_text("# Habit app\nA small Next.js habit tracker.\n")
    (src / "package.json").write_text('{"name": "habit-app", "dependencies": {"next": "14.2.0"}}\n')
    (src / "app" / "home" / "page.tsx").write_text("export default function Home() { return <main>Today</main>; }\n")
    (src / "app" / "onboarding.tsx").write_text("export function Onboarding() { return null; }\n")
    _git("init", "-q", "-b", "main", cwd=src)
    _git("add", "-A", cwd=src)
    _git("commit", "-q", "-m", "init", cwd=src)
    _git("remote", "add", "origin", str(bare), cwd=src)
    _git("push", "-q", "origin", "main", cwd=src)

    state = {"pulls": [], "issues": [], "calls": [], "merged": set()}

    def handler(req: httpx.Request) -> httpx.Response:
        auth = req.headers.get("authorization", "")
        state["calls"].append((req.method, req.url.path, auth == f"Bearer {TOKEN}"))
        if auth != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"message": "Bad credentials"})
        path = req.url.path
        if req.method == "GET" and path == f"/repos/{REPO}":
            return httpx.Response(200, json={"default_branch": "main", "private": True, "permissions": {"push": True}})
        if req.method == "POST" and path == f"/repos/{REPO}/pulls":
            body = json.loads(req.content)
            assert body["draft"] is True and body["base"] == "main" and body["head"].startswith("aiciv/lab-")
            n = len(state["pulls"]) + len(state["issues"]) + 1
            state["pulls"].append({**body, "number": n})
            return httpx.Response(201, json={"number": n, "html_url": f"https://github.com/{REPO}/pull/{n}"})
        if req.method == "POST" and path == f"/repos/{REPO}/issues":
            body = json.loads(req.content)
            n = len(state["pulls"]) + len(state["issues"]) + 1
            state["issues"].append({**body, "number": n})
            return httpx.Response(201, json={"number": n, "html_url": f"https://github.com/{REPO}/issues/{n}"})
        if req.method == "GET" and (path.startswith(f"/repos/{REPO}/pulls/") or path.startswith(f"/repos/{REPO}/issues/")):
            n = int(path.rsplit("/", 1)[1])
            merged = n in state["merged"]
            return httpx.Response(200, json={"state": "closed" if merged else "open", "merged": merged, "draft": True,
                                             "html_url": f"https://github.com/{REPO}/pull/{n}"})
        return httpx.Response(404, json={"message": "Not Found"})

    monkeypatch.setenv("AICIV_GITHUB_GIT_BASE", f"file://{base}")
    monkeypatch.setattr(L, "github_http", lambda: httpx.Client(base_url="https://api.github.test", transport=httpx.MockTransport(handler)))
    monkeypatch.setenv("AICIV_APPLAB_TRACK_SECONDS", "0")
    monkeypatch.setattr("services.applab.pipeline.TRACK_EVERY_S", 0)
    return {"bare": bare, "state": state, "base": base}


@pytest.fixture
def labenv(monkeypatch):
    monkeypatch.setenv("AICIV_BELT_SPEED", "400")
    monkeypatch.setenv("AICIV_TICK_SCALE", "0.02")
    from services.core.auth import mutation_limiter
    monkeypatch.setattr(mutation_limiter, "burst", 100)
    monkeypatch.setattr(stepup, "STEP", 1)
    config.get_settings.cache_clear()


def _client():
    from services.api.main import app
    app.state.gateway = None
    return TestClient(app)


def connect(c, secret):
    tok = step_up(c, "lab-connect", secret)
    r = c.post("/api/applab/repositories", json={"full_name": REPO, "token": TOKEN}, headers={"X-Step-Up": tok})
    assert r.status_code == 201, r.text
    return r.json()


def cycle_until(c, cid, statuses, timeout=120):
    return wait_for(lambda: (d := c.get(f"/api/applab/cycles/{cid}").json())["cycle"]["status"] in statuses and d, timeout=timeout)


def branches(bare: Path) -> set[str]:
    out = subprocess.run(["git", "for-each-ref", "--format=%(refname:short)", "refs/heads"], cwd=bare, capture_output=True, text=True).stdout
    return set(out.split())


def main_sha(bare: Path) -> str:
    return subprocess.run(["git", "rev-parse", "main"], cwd=bare, capture_output=True, text=True).stdout.strip()


def test_acceptance_app_lab_cycle(labenv, github):
    log = ["# App Lab acceptance run", "", f"Recorded {time.strftime('%Y-%m-%d %H:%M:%S %Z')} by tests/integration/test_applab.py.",
           "GitHub is a local bare repository (git over file://) plus a mock REST API. Design patterns come from the **FIXTURE** pattern "
           "library; no model key, so proposal text is the labeled simulation template.", ""]
    bare, gh = github["bare"], github["state"]
    main_before = main_sha(bare)
    with _client() as c:
        secret = c.post("/api/finance/stepup/enroll").json()["secret"]
        # connecting needs step-up, and a token GitHub accepts
        assert c.post("/api/applab/repositories", json={"full_name": REPO, "token": TOKEN}).status_code == 401
        bad = c.post("/api/applab/repositories", json={"full_name": REPO, "token": "github_pat_" + "y" * 40},
                     headers={"X-Step-Up": step_up(c, "lab-connect", secret)})
        assert bad.status_code == 400
        repo = connect(c, secret)
        assert repo["status"] == "ACTIVE" and repo["has_credentials"] and "secret_ciphertext" not in repo
        with db.get_engine().connect() as conn:
            row = conn.execute(select(db.lab_repositories)).first()
        assert TOKEN not in (row.secret_ciphertext or "")
        log.append(f"1. Owner connected `{REPO}` with step-up; GitHub verified write access; the token is stored encrypted and never "
                   "returned. Without step-up: 401. With a token GitHub rejects: 400.")

        r = c.post(f"/api/applab/repositories/{repo['id']}/cycles")
        assert r.status_code == 201, r.text
        cid = r.json()["cycle_id"]
        assert c.post(f"/api/applab/repositories/{repo['id']}/cycles").status_code == 409  # one cycle at a time
        d = cycle_until(c, cid, ("AWAITING_OWNER", "DONE", "FAILED"))
        assert d["cycle"]["status"] == "AWAITING_OWNER", d["cycle"]
        legs = [(p["origin"], p["destination"], p["status"]) for p in d["packages"]]
        assert ("data-observatory", "code-forge", "RECEIVED") in legs
        assert ("code-forge", "nexus-spire", "RECEIVED") in legs
        assert ("nexus-spire", "owners-tower", "RECEIVED") in legs
        assert d["insights"] and all(e["source_url"] for i in d["insights"] for e in i["evidence"])
        log.append(f"2. Cycle travelled {' → '.join(['data-observatory', 'code-forge', 'nexus-spire', 'owners-tower'])} as physical packages; "
                   f"research produced {len(d['insights'])} design insight(s), each with a source.")

        props = d["proposals"]
        install = next(p for p in props if p["route"] == "patch")
        ideas = [p for p in props if p["route"] == "claude_code"]
        assert install["files"] == [L.WORKFLOW_PATH] and install["checks"]["applies"] is True
        assert ideas and all(p["status"] == "AWAITING_OWNER" for p in props)
        assert all(p["gm_review"]["verdict"] == "recommend" and p["gm_review"]["authorizes_publish"] is False for p in props)
        assert any("[simulation" in p["gm_review"]["briefing"] for p in props)
        # nothing touched GitHub yet
        assert branches(bare) == {"main"} and main_sha(bare) == main_before
        assert not gh["pulls"] and not gh["issues"]
        log.append(f"3. Code Forge read the repository (read-only) and drafted {len(props)} proposal(s): the pinned Claude Code workflow "
                   f"(patch; `git apply --check` passed) and {len(ideas)} Claude Code task(s). The General Manager reviewed every one "
                   "(`authorizes_publish: false`) and briefed the owner. **Nothing was pushed: GitHub still has only `main`.**")

        # approving needs step-up bound to that proposal and the exact payload hash
        detail = c.get(f"/api/applab/proposals/{install['id']}").json()["proposal"]
        assert detail["patch"].startswith(f"diff --git a/{L.WORKFLOW_PATH}")
        r = c.post(f"/api/applab/proposals/{install['id']}/decide", json={"decision": "APPROVE", "payload_hash": install["payload_hash"]})
        assert r.status_code == 401
        wrong = step_up(c, f"lab:{ideas[0]['id']}", secret)
        r = c.post(f"/api/applab/proposals/{install['id']}/decide", json={"decision": "APPROVE", "payload_hash": install["payload_hash"]},
                   headers={"X-Step-Up": wrong})
        assert r.status_code == 401
        tok = step_up(c, f"lab:{install['id']}", secret)
        r = c.post(f"/api/applab/proposals/{install['id']}/decide", json={"decision": "APPROVE", "payload_hash": "0" * 64},
                   headers={"X-Step-Up": tok})
        assert r.status_code == 409
        r = c.post(f"/api/applab/proposals/{install['id']}/decide", json={"decision": "APPROVE", "payload_hash": install["payload_hash"]},
                   headers={"X-Step-Up": tok})
        assert r.status_code == 200, r.text
        p1 = wait_for(lambda: (x := c.get(f"/api/applab/proposals/{install['id']}").json()["proposal"])["status"] in ("PUBLISHED", "FAILED") and x,
                      timeout=60)
        assert p1["status"] == "PUBLISHED", p1
        assert p1["published"]["kind"] == "pr" and p1["published"]["branch"].startswith("aiciv/lab-")
        assert main_sha(bare) == main_before and p1["published"]["branch"] in branches(bare)
        assert gh["pulls"][0]["draft"] is True
        log.append(f"4. Approval without step-up: 401; with a step-up token for another proposal: 401; with a different payload hash: 409. "
                   f"The approved install was pushed to `{p1['published']['branch']}` and opened as **draft** PR #{p1['published']['number']}; "
                   "`main` is unchanged.")

        # a Claude Code task becomes an issue labeled `claude`
        idea = ideas[0]
        tok = step_up(c, f"lab:{idea['id']}", secret)
        assert c.post(f"/api/applab/proposals/{idea['id']}/decide", json={"decision": "APPROVE", "payload_hash": idea["payload_hash"]},
                      headers={"X-Step-Up": tok}).status_code == 200
        p2 = wait_for(lambda: (x := c.get(f"/api/applab/proposals/{idea['id']}").json()["proposal"])["status"] in ("PUBLISHED", "FAILED") and x,
                      timeout=60)
        assert p2["status"] == "PUBLISHED" and p2["published"]["kind"] == "issue"
        issue = gh["issues"][0]
        assert "claude" in issue["labels"] and issue["body"].startswith("@claude") and "Do not push to `main`" in issue["body"]
        log.append(f"5. A second approved proposal was handed to Claude Code as issue #{p2['published']['number']} labeled `claude`, whose "
                   "instructions forbid pushing to the default branch and touching CI or secrets.")

        # the rest: reject / defer; the cycle completes when all are decided
        for other in ideas[1:]:
            assert c.post(f"/api/applab/proposals/{other['id']}/decide",
                          json={"decision": "REJECT", "payload_hash": other["payload_hash"]}).status_code == 200
        cycle_until(c, cid, ("DONE",))
        # approvals are single-use: re-running the publish tool refuses
        assert c.post(f"/api/applab/proposals/{install['id']}/decide",
                      json={"decision": "APPROVE", "payload_hash": install["payload_hash"]},
                      headers={"X-Step-Up": step_up(c, f"lab:{install['id']}", secret)}).status_code == 409

        # GitHub status is tracked read-only and the GM reports the merge
        github["state"]["merged"].add(p1["published"]["number"])
        wait_for(lambda: c.get(f"/api/applab/proposals/{install['id']}").json()["proposal"]["tracking"].get("merged"), timeout=30)
        with db.get_engine().connect() as conn:
            wait_for(lambda: any("was merged" in r.body for r in conn.execute(select(db.agent_reports.c.body)).fetchall()), timeout=30)
        events = [e["event_type"] for e in all_events(c)]
        for t in ("lab.cycle_status_changed", "lab.proposals_ready", "lab.proposal_decided", "lab.change_published", "lab.change_status"):
            assert t in events, t
        # no event ever carries the token
        assert TOKEN not in json.dumps(all_events(c))
        log.append("6. Remaining proposals rejected; the cycle finished `DONE`. Re-approving a published proposal: 409. After the PR was "
                   "merged on GitHub, status tracking (read-only) picked it up and the General Manager reported it. No event contains the token.")

        # revoking access stops everything and drops the token
        assert c.post(f"/api/applab/repositories/{repo['id']}/revoke").status_code == 200
        with db.get_engine().connect() as conn:
            row = conn.execute(select(db.lab_repositories)).first()
        assert row.status == "REVOKED" and row.secret_ciphertext is None
        assert c.post(f"/api/applab/repositories/{repo['id']}/cycles").status_code == 409
        log.append("7. Owner revoked access: the encrypted token was deleted and new cycles are refused (409).")
    if os.environ.get("AICIV_RECORD_ACCEPTANCE") == "1":
        out = ROOT / "docs" / "acceptance" / "app-lab-acceptance-log.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(log) + "\n")


def test_lab_tools_are_confined(labenv, github):
    """Backend authorization, not prompts: lab tools need a lab mission on that cycle, at that stage; lab missions can
    use nothing else; publishing needs the owner's approval of the exact change, issued to that mission."""
    from services.core.events import transaction
    from services.management.hierarchy import agent_by_key
    from services.management.pipeline import create_mission
    from services.tools.registry import ToolContext, ToolDenied, execute_tool

    with _client() as c:
        secret = c.post("/api/finance/stepup/enroll").json()["secret"]
        repo = connect(c, secret)
        cid = c.post(f"/api/applab/repositories/{repo['id']}/cycles").json()["cycle_id"]
        d = cycle_until(c, cid, ("AWAITING_OWNER",))
        prop = d["proposals"][0]
        org = config.load_seed()["organization_id"]
        with transaction() as conn:
            dev = agent_by_key(conn, "developer")
            rogue = create_mission(conn, org_id=org, kind="lab_publish", title="rogue", prompt="x", params={"proposal_id": prop["id"]},
                                   opportunity_id=None, created_by=dev.id)
            other = create_mission(conn, org_id=org, kind="lab_analyze", title="x", prompt="x", params={"cycle_id": cid}, opportunity_id=None,
                                   created_by=dev.id)
            task_id = db.new_id()
            for mid in (rogue, other):
                conn.execute(db.tasks.insert().values(id=task_id if mid == rogue else db.new_id(), organization_id=org, mission_id=mid,
                                                      key="t", title="t", agent_id=dev.id, status="RUNNING", district="code-forge", ordinal=0,
                                                      permitted_tools=["publish_lab_change", "scan_repository", "edit_file"]))
            other_task = conn.execute(select(db.tasks.c.id).where(db.tasks.c.mission_id == other)).scalar()
        ctx = ToolContext(org_id=org, mission_id=rogue, task_id=task_id, agent_id=dev.id, execution_mode="simulation")
        # not approved by the owner
        with pytest.raises(ToolDenied, match="not approved|publishing refused"):
            execute_tool(ctx, "publish_lab_change", {"proposal_id": prop["id"], "payload_hash": prop["payload_hash"]})
        # approved — but for a different mission
        tok = step_up(c, f"lab:{prop['id']}", secret)
        assert c.post(f"/api/applab/proposals/{prop['id']}/decide", json={"decision": "APPROVE", "payload_hash": prop["payload_hash"]},
                      headers={"X-Step-Up": tok}).status_code == 200
        with pytest.raises(ToolDenied):
            execute_tool(ctx, "publish_lab_change", {"proposal_id": prop["id"], "payload_hash": prop["payload_hash"]})
        # lab missions cannot use other tools; analysis tools refuse once the cycle moved on
        octx = ToolContext(org_id=org, mission_id=other, task_id=other_task, agent_id=dev.id, execution_mode="simulation")
        with pytest.raises(ToolDenied, match="not allowed in an App Lab mission"):
            execute_tool(octx, "edit_file", {"path": "x", "old": "a", "new": "b"})
        with pytest.raises(ToolDenied, match="cycle is"):
            execute_tool(octx, "scan_repository", {"cycle_id": cid})
        wait_for(lambda: c.get(f"/api/applab/proposals/{prop['id']}").json()["proposal"]["status"] == "PUBLISHED", timeout=60)


def test_gm_blocks_protected_paths_and_restart_survives(labenv, github):
    """The GM rules block patches that touch .github/ (other than the pinned template), secrets, or are too large; and a
    cycle resumes after the worker restarts."""
    from types import SimpleNamespace

    repo = SimpleNamespace(full_name=REPO, default_branch="main", claude_code_ready=1)
    evil = "diff --git a/.github/workflows/x.yml b/.github/workflows/x.yml\n--- /dev/null\n+++ b/.github/workflows/x.yml\n@@ -0,0 +1 @@\n+on: push\n"
    p = SimpleNamespace(route="patch", patch=evil, patch_sha256="nope", checks={"applies": True}, instructions=None)
    r = L.gm_rules(p, repo)
    assert r["verdict"] == "blocked" and "protected paths" in r["issues"][0]
    env_patch = "diff --git a/.env b/.env\n--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n-A=1\n+A=2\n"
    assert L.gm_rules(SimpleNamespace(route="patch", patch=env_patch, patch_sha256="n", checks={"applies": True}, instructions=None),
                      repo)["verdict"] == "blocked"
    big = "diff --git a/a.ts b/a.ts\n--- a/a.ts\n+++ b/a.ts\n@@ -1 +1,500 @@\n" + "+x\n" * 500
    assert "review limit" in L.gm_rules(SimpleNamespace(route="patch", patch=big, patch_sha256="n", checks={"applies": True}, instructions=None),
                                        repo)["issues"][0]
    with _client() as c:
        secret = c.post("/api/finance/stepup/enroll").json()["secret"]
        rid = connect(c, secret)["id"]
        cid = c.post(f"/api/applab/repositories/{rid}/cycles").json()["cycle_id"]
        wait_for(lambda: c.get(f"/api/applab/cycles/{cid}").json()["cycle"]["status"] != "RESEARCHING", timeout=60)
    # the app (worker + scheduler) stopped mid-cycle; a new one resumes from the database
    with _client() as c:
        d = cycle_until(c, cid, ("AWAITING_OWNER", "DONE", "FAILED"))
        assert d["cycle"]["status"] == "AWAITING_OWNER"
