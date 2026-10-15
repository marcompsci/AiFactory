"""Plans (Codex first, Claude when Codex runs out, smallest model while the owner uses Claude), the Codex Factory and
its meters, and the company knowledge base."""
import json
import os
import stat
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.core import config, db
from services.model_gateway import plans
from services.model_gateway.gateway import ModelGateway, ModelRequest, ProviderError
from tests.conftest import wait_for

NOW = datetime.now(timezone.utc)


def write_codex_home(root: Path, primary: float, secondary: float = 10.0, resets_in: int = 3600) -> Path:
    h = root / "codex-home"
    d = h / "sessions" / NOW.strftime("%Y/%m/%d")
    d.mkdir(parents=True, exist_ok=True)
    recs = [
        {"timestamp": NOW.isoformat(), "type": "session_meta", "payload": {"id": "x", "cwd": "/Users/omari/Create/habit-app"}},
        {"timestamp": NOW.isoformat(), "type": "event_msg", "payload": {"type": "user_message", "message": "Add dark mode to settings"}},
        {"timestamp": NOW.isoformat(), "type": "response_item", "payload": {"type": "function_call", "name": "update_plan", "arguments": json.dumps(
            {"plan": [{"step": "Add theme toggle", "status": "completed"}, {"step": "Persist choice", "status": "in_progress"}]})}},
        {"timestamp": NOW.isoformat(), "type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {
            "input_tokens": 1200, "cached_input_tokens": 200, "output_tokens": 300}},
            "rate_limits": {"primary": {"used_percent": primary, "window_minutes": 299, "resets_in_seconds": resets_in},
                            "secondary": {"used_percent": secondary, "window_minutes": 10079, "resets_in_seconds": 86400}}}},
    ]
    (d / "rollout-2026-test.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    (h / "AGENTS.md").write_text("# House rules\nUse pnpm, not npm.\n\nKeep pull requests under 300 lines.\n")
    return h


def write_claude_home(root: Path, tokens: int, minutes_ago: float) -> Path:
    h = root / "claude-home"
    proj = h / "projects" / "-Users-omari-Create-app"
    proj.mkdir(parents=True, exist_ok=True)
    ts = (NOW - timedelta(minutes=minutes_ago)).isoformat()
    f = proj / "s.jsonl"
    f.write_text(json.dumps({"type": "assistant", "timestamp": ts, "message": {"usage": {"input_tokens": tokens, "output_tokens": 0}}}) + "\n")
    os.utime(f, (time.time() - minutes_ago * 60,) * 2)
    return h


def fake_cli(root: Path, name: str, script: str) -> str:
    p = root / name
    p.write_text("#!/usr/bin/env python3\n" + script)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


CODEX_OK = """import sys, json
sys.stdin.read()
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "codex says hi " + " ".join(sys.argv[1:])}}))
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 50, "cached_input_tokens": 10, "output_tokens": 7}}))
"""
CODEX_LIMIT = """import sys, json
sys.stdin.read()
print(json.dumps({"type": "turn.failed", "error": {"message": "You've hit your usage limit. Try again later."}}))
sys.exit(1)
"""
CLAUDE_OK = """import sys, json
sys.stdin.read()
m = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else "default"
print(json.dumps({"type": "result", "is_error": False, "result": "claude(" + m + ") says hi", "usage": {"input_tokens": 40, "output_tokens": 5}}))
"""


@pytest.fixture
def penv(tmp_path, monkeypatch):
    monkeypatch.setenv("AICIV_USE_PLANS", "1")
    monkeypatch.setenv("AICIV_PLAN_WORKDIR", str(tmp_path / "agent-workdir"))
    monkeypatch.setenv("AICIV_CLAUDE_APP_OPEN", "0")
    monkeypatch.setenv("AICIV_CLAUDE_HOME", str(write_claude_home(tmp_path, 1000, minutes_ago=120)))
    monkeypatch.setenv("AICIV_CODEX_HOME", str(write_codex_home(tmp_path, primary=30)))
    monkeypatch.setenv("AICIV_CODEX_BIN", fake_cli(tmp_path, "codex", CODEX_OK))
    monkeypatch.setenv("AICIV_CLAUDE_BIN", fake_cli(tmp_path, "claude", CLAUDE_OK))
    plans.clear_exhausted()
    config.get_settings.cache_clear()
    yield tmp_path
    plans.clear_exhausted()


def test_codex_meter_reads_codex_rate_limit_reports(penv):
    u = plans.codex_usage()
    assert u["source"] == "reported" and u["primary"]["used_percent"] == 30 and u["secondary"]["used_percent"] == 10
    assert u["tokens_5h"] == 1300
    # once the reported window has rolled over, it reads as fresh
    os.environ["AICIV_CODEX_HOME"] = str(write_codex_home(penv / "old", primary=99, resets_in=-60))
    assert plans.codex_usage()["primary"]["used_percent"] == 0


def test_codex_first_then_claude_then_nothing(penv, monkeypatch):
    g = ModelGateway()
    assert list(g.adapters) == ["plan"] and config.get_settings().model_available
    r = g.complete(ModelRequest(system="s", prompt="hello", model="claude-opus-5-5"), preferred_provider="anthropic")
    assert r.provider == "codex_plan" and r.text.startswith("codex says hi") and r.estimated_cost_usd == 0
    assert "--sandbox read-only" in r.text  # the CLI ran read-only

    # Codex reaches the stop line → Claude, keeping the agent's model family
    monkeypatch.setenv("AICIV_CODEX_HOME", str(write_codex_home(penv / "hi", primary=97)))
    r = ModelGateway().complete(ModelRequest(system="s", prompt="hello again", model="claude-opus-5-5"))
    assert r.provider == "claude_plan" and r.text == "claude(opus) says hi"

    # Codex answers "usage limit" mid-call → marked exhausted, the same call moves to Claude
    monkeypatch.setenv("AICIV_CODEX_HOME", str(write_codex_home(penv / "lo", primary=5)))
    monkeypatch.setenv("AICIV_CODEX_BIN", fake_cli(penv, "codex-limit", CODEX_LIMIT))
    r = ModelGateway().complete(ModelRequest(system="s", prompt="third", model="claude-sonnet-5-5"))
    assert r.provider == "claude_plan" and plans.exhausted("codex")

    # Claude at the owner's reserve line → nothing left; the task waits instead of using an API key
    monkeypatch.setenv("AICIV_CLAUDE_5H_TOKEN_BUDGET", "1000")
    with pytest.raises(ProviderError) as e:
        ModelGateway().complete(ModelRequest(system="s", prompt="fourth"))
    assert e.value.kind == "quota" and "for you" in str(e.value)


def test_owner_using_claude_puts_agents_on_the_smallest_model(penv, monkeypatch):
    monkeypatch.setenv("AICIV_CODEX_HOME", str(write_codex_home(penv / "full", primary=100)))
    monkeypatch.setenv("AICIV_CLAUDE_HOME", str(write_claude_home(penv / "active", 500, minutes_ago=2)))
    b = plans.decide("opus")
    assert b.owner_active and b.plan == "claude" and b.model == "haiku" and b.save
    assert "using Claude" in b.note()
    r = ModelGateway().complete(ModelRequest(system="s", prompt="x", model="claude-opus-5-5"))
    assert r.text == "claude(haiku) says hi"
    # the agents' own Claude runs don't count as the owner using Claude
    monkeypatch.setenv("AICIV_CLAUDE_HOME", str(write_claude_home(penv / "idle", 500, minutes_ago=120)))
    agent_proj = Path(os.environ["AICIV_CLAUDE_HOME"]) / "projects" / plans._agent_project_dir_name()
    agent_proj.mkdir(parents=True)
    (agent_proj / "a.jsonl").write_text("{}\n")
    assert plans.owner_activity()["active"] is False
    assert plans.decide("opus").model == "opus"
    monkeypatch.setenv("AICIV_CLAUDE_APP_OPEN", "1")  # the Claude app open counts (setting on by default)
    assert plans.decide("opus").model == "haiku"


def _client():
    from services.api.main import app
    app.state.gateway = None
    return TestClient(app)


def test_codex_factory_and_meters_brief_every_agent(penv, monkeypatch):
    monkeypatch.setenv("AICIV_FACTORY_SYNC_MINUTES", "60")
    with _client() as c:
        r = c.post("/api/factories/codex/link", json={"enabled": True})
        assert r.status_code == 200
        mid = r.json()["sync_mission_id"]
        try:
            wait_for(lambda: c.get(f"/api/missions/{mid}").json()["mission"]["status"] == "COMPLETED", timeout=60)
        except AssertionError:
            d = c.get(f"/api/missions/{mid}").json()
            raise AssertionError(json.dumps({"m": d["mission"], "tasks": d.get("tasks"), "msgs": d.get("messages")}, default=str)[:3000])
        f = c.get("/api/factories").json()
        s = f["codex"]["data"]["sessions"][0]
        assert s["title"] == "Add dark mode to settings" and s["completed_tasks"] == ["Add theme toggle"]
        assert f["codex"]["data"]["memory"][0]["label"] == "~/.codex/AGENTS.md"
        u = f["plan_usage"]["data"]
        assert u["plan"] == "codex" and u["codex"]["primary"]["used_percent"] == 30 and u["claude"]["source"] == "estimate"
        msgs = c.get(f"/api/missions/{mid}").json()["messages"]
        bodies = " ".join(m["body"] for m in msgs)
        assert "Codex plan: 30% of the 5-hour window" in bodies and "Save 40% for the owner" in bodies
        assert any(m["to_agent_id"] is None and m["body"].startswith("Codex plan") for m in msgs)  # to everyone
        live = c.get("/api/factories/usage").json()
        assert live["plan"] == "codex" and "Usage budget" in live["note"]
        r = c.put("/api/factories/usage/settings", json={"claude_reserve_percent": 50, "claude_5h_token_budget": 200000})
        assert r.status_code == 200 and r.json()["settings"]["claude_reserve_percent"] == 50


def test_knowledge_base_crud_upload_and_agents_pull_skills(penv, monkeypatch):
    monkeypatch.setenv("AICIV_USE_PLANS", "0")
    skill = ("---\nname: app-idea\ndescription: Develop a mobile app idea end to end - concepts, competitors, MVP scope\n---\n\n"
             "# App idea\nStart with the problem. Score each concept on pain, frequency and willingness to pay.\n")
    with _client() as c:
        r = c.post("/api/knowledge", json={"title": "Phoronomics mission", "company": "phoronomics",
                                           "body": "Phoronomics builds apps that help people pay bills on time and grow credit."})
        assert r.status_code == 201 and r.json()["slug"] == "phoronomics-mission"
        r = c.put("/api/knowledge/upload?filename=app-idea/SKILL.md&company=shared", content=skill.encode())
        assert r.status_code == 201 and r.json() == {"slug": "app-idea", "title": "App Idea", "kind": "skill"}
        assert c.put("/api/knowledge/upload?filename=x.exe", content=b"MZ").status_code == 415
        lst = c.get("/api/knowledge").json()
        assert lst["counts"] == {"doc": 1, "skill": 1} and lst["can_edit"]
        assert c.get("/api/knowledge?q=mobile%20app%20concept").json()["items"][0]["slug"] == "app-idea"
        assert "willingness to pay" in c.get("/api/knowledge/app-idea").json()["body"]
        assert c.put("/api/knowledge/phoronomics-mission", json={"title": "Phoronomics mission", "body": "Updated.",
                                                                 "company": "phoronomics"}).status_code == 200
        with db.get_engine().connect() as conn:
            from services.knowledge import kb
            org = conn.execute(db.organizations.select()).first().id
            text, used = kb.context_for(conn, org, "Draft three mobile app concepts and score their willingness to pay")
        assert used == ["App Idea"] and "never overrides your safety rules" in text
        assert c.delete("/api/knowledge/phoronomics-mission").status_code == 200
        assert c.get("/api/knowledge/phoronomics-mission").status_code == 404


def test_skills_folder_is_imported_on_start(tmp_path, monkeypatch):
    k = tmp_path / "knowledge" / "skills" / "deep-research"
    (k / "references").mkdir(parents=True)
    (k / "SKILL.md").write_text("---\nname: deep-research\ndescription: Research across many sources\n---\nBody\n")
    (k / "references" / "notes.md").write_text("# not a skill on its own\n")
    monkeypatch.setenv("AICIV_KNOWLEDGE_DIR", str(tmp_path / "knowledge"))
    with _client() as c:
        items = c.get("/api/knowledge").json()["items"]
    assert [(i["slug"], i["kind"], i["source"]) for i in items] == [("deep-research", "skill", "import")]
