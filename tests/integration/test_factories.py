"""Claude Code and GitHub factories: opt-in, read-only, owner-only, and their agents do the reading as real missions."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from services.core import config, db
from tests.conftest import wait_for
from tests.integration.test_applab import TOKEN, connect, github, labenv  # noqa: F401  (fixtures)
from tests.integration.test_v5_acceptance import step_up  # noqa: F401

FAKE_KEY = "sk-ant-api03-" + "Z" * 30


def fake_claude_home(root: Path) -> Path:
    h = root / "claude-home"
    proj = h / "projects" / "-Users-omari-Create-habit-app"
    (proj / "memory").mkdir(parents=True)
    (h / "CLAUDE.md").write_text("# Me\nPrefer small pull requests.\n\nAlways run the tests before committing.\n")
    (proj / "memory" / "MEMORY.md").write_text("# Habit app\nThe app uses Next.js; streak logic lives in lib/streak.ts.\n\n"
                                                "Tests: npm test (vitest).\n")
    lines = [
        {"type": "user", "timestamp": "2026-10-14T20:00:00Z", "cwd": "/Users/omari/Create/habit-app", "gitBranch": "main", "sessionId": "s1",
         "message": {"role": "user", "content": f"Add a streak freeze to the home screen. my key is {FAKE_KEY}"}},
        {"type": "assistant", "timestamp": "2026-10-14T20:01:00Z", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "TodoWrite", "input": {"todos": [
                {"content": "Add streak freeze state", "status": "completed"},
                {"content": "Show freeze badge on home", "status": "completed"},
                {"content": "Write tests", "status": "in_progress"}]}}]}},
        {"type": "assistant", "timestamp": "2026-10-14T20:05:00Z", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "SECRET-TRANSCRIPT-BODY should never leave the transcript"}]}},
    ]
    (proj / "s1.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n")
    return h


@pytest.fixture
def fenv(labenv, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("AICIV_CLAUDE_HOME", str(fake_claude_home(tmp_path)))
    monkeypatch.setenv("AICIV_FACTORY_SYNC_MINUTES", "60")
    config.get_settings.cache_clear()


def _client():
    from services.api.main import app
    app.state.gateway = None
    return TestClient(app)


def test_claude_code_factory_reads_sessions_tasks_and_memory_only_when_linked(fenv):
    with _client() as c:
        assert c.get("/api/factories").json()["claude_code"]["linked"] is False
        r = c.post("/api/factories/claude_code/link", json={"enabled": True})
        assert r.status_code == 200 and r.json()["sync_mission_id"]
        mid = r.json()["sync_mission_id"]
        wait_for(lambda: c.get(f"/api/missions/{mid}").json()["mission"]["status"] == "COMPLETED", timeout=60)
        d = c.get("/api/factories").json()["claude_code"]
        s = d["data"]["sessions"][0]
        assert s["project"] == "habit-app" and s["branch"] == "main"
        assert s["completed_tasks"] == ["Add streak freeze state", "Show freeze badge on home"] and s["open_tasks"] == ["Write tests"]
        assert "streak freeze" in s["title"] and FAKE_KEY not in s["title"] and "[REDACTED]" in s["title"]
        labels = {m["label"] for m in d["data"]["memory"]}
        assert "~/.claude/CLAUDE.md" in labels and any("MEMORY.md" in x for x in labels)
        dump = json.dumps(c.get("/api/factories").json())
        assert "SECRET-TRANSCRIPT-BODY" not in dump and FAKE_KEY not in dump
        # the agents really did the work: Coda's tool call is in the mission log, without transcript content
        with db.get_engine().connect() as conn:
            ex = conn.execute(select(db.tool_executions).where(db.tool_executions.c.mission_id == mid)).fetchall()
        assert [e.tool_name for e in ex] == ["sync_claude_code"] and "streak" not in (ex[0].output_excerpt or "")
        # unlinking forgets the snapshot
        c.post("/api/factories/claude_code/link", json={"enabled": False})
        assert c.get("/api/factories").json()["claude_code"]["data"] is None


def test_other_agents_can_read_claude_code_memory_but_not_sync(fenv):
    from services.core.events import transaction
    from services.management.hierarchy import agent_by_key
    from services.management.pipeline import create_mission
    from services.tools.registry import ToolContext, ToolDenied, execute_tool

    with _client() as c:
        org = config.load_seed()["organization_id"]
        with transaction() as conn:
            dev = agent_by_key(conn, "developer")
            mid = create_mission(conn, org_id=org, kind="fix_failing_test", title="t", prompt="x", params={}, opportunity_id=None, created_by=dev.id)
            tid = db.new_id()
            conn.execute(db.tasks.insert().values(id=tid, organization_id=org, mission_id=mid, key="t", title="t", agent_id=dev.id, status="RUNNING",
                                                  district="code-forge", ordinal=0, permitted_tools=["read_claude_code_memory", "sync_claude_code"]))
        ctx = ToolContext(org_id=org, mission_id=mid, task_id=tid, agent_id=dev.id, execution_mode="simulation")
        assert execute_tool(ctx, "read_claude_code_memory", {"query": "tests"})["status"] == "not_linked"  # opt-in first
        c.post("/api/factories/claude_code/link", json={"enabled": True})
        hits = execute_tool(ctx, "read_claude_code_memory", {"query": "streak tests"})["hits"]
        assert any("lib/streak.ts" in h["text"] for h in hits)
        with pytest.raises(ToolDenied):  # capability + factory-mission confinement
            execute_tool(ctx, "sync_claude_code", {})


def test_github_factory_reads_authorized_repos(fenv, github):  # noqa: F811
    from services.finance import stepup  # noqa: F401
    with _client() as c:
        secret = c.post("/api/finance/stepup/enroll").json()["secret"]
        connect(c, secret)
        r = c.post("/api/factories/github/link", json={"enabled": True})
        mid = r.json()["sync_mission_id"]
        wait_for(lambda: c.get(f"/api/missions/{mid}").json()["mission"]["status"] in ("COMPLETED", "FAILED"), timeout=60)
        d = c.get("/api/factories").json()["github"]
        assert d["linked"] and d["data"]["repos"][0]["repo"] == "owner/habit-app"
        # the mock only knows a few endpoints, so the rest are reported as unavailable rather than invented
        assert d["data"]["repos"][0]["commits"] == [] and "commits unavailable" in d["data"]["repos"][0]["errors"]
        assert TOKEN not in json.dumps(c.get("/api/factories").json())
