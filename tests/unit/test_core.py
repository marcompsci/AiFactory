"""Unit tests: state machines, planning, sandbox, auth, memory, cost accounting."""
import json
import os
from pathlib import Path

import httpx
import jwt
import pytest

from services.core.state import InvalidTransition, assert_transition
from services.orchestrator.plan import FIX_FAILING_TEST_GRAPH, PlanError, TaskSpec, validate_graph, validate_prompt
from services.tools.sandbox import ProcessSandbox, SandboxViolation, confine


# ------------------------------------------------------------------ state machines
@pytest.mark.parametrize("kind,a,b", [
    ("mission", "CREATED", "VALIDATING"), ("mission", "RUNNING", "WAITING_FOR_APPROVAL"), ("mission", "WAITING_FOR_APPROVAL", "RUNNING"),
    ("task", "PENDING", "RUNNING"), ("task", "RUNNING", "PENDING"), ("task", "WAITING_FOR_APPROVAL", "SKIPPED"),
    ("agent", "IDLE", "ASSIGNED"), ("agent", "EXECUTING", "WAITING_FOR_APPROVAL"), ("agent", "COMPLETED", "IDLE"),
])
def test_allowed_transitions(kind, a, b):
    assert_transition(kind, a, b)


@pytest.mark.parametrize("kind,a,b", [
    ("mission", "CREATED", "RUNNING"), ("mission", "COMPLETED", "RUNNING"), ("mission", "QUEUED", "COMPLETED"),
    ("task", "CANCELLED", "RUNNING"), ("agent", "IDLE", "EXECUTING"), ("agent", "EXECUTING", "IDLE"),
])
def test_rejected_transitions(kind, a, b):
    with pytest.raises(InvalidTransition):
        assert_transition(kind, a, b)


def test_movement_is_not_an_execution_state():
    from services.core.state import AGENT_TRANSITIONS
    assert "MOVING" not in AGENT_TRANSITIONS


# ------------------------------------------------------------------ planning
def test_shipped_graph_is_valid():
    validate_graph(FIX_FAILING_TEST_GRAPH)
    roots = [t.key for t in FIX_FAILING_TEST_GRAPH if not t.depends_on]
    assert set(roots) == {"inspect", "reproduce"}, "independent tasks should start in parallel"


def test_graph_cycle_rejected():
    g = [TaskSpec("a", "qa", "A", "sentinel-citadel", "citadel-testbay", ["run_tests"], ["b"]),
         TaskSpec("b", "qa", "B", "sentinel-citadel", "citadel-testbay", ["run_tests"], ["a"])]
    with pytest.raises(PlanError, match="cycle"):
        validate_graph(g)


def test_graph_rejects_tool_agent_cannot_use():
    g = [TaskSpec("a", "designer", "A", "vision-quarter", "vision-studio", ["edit_file"])]
    with pytest.raises(PlanError, match="cannot use"):
        validate_graph(g)


def test_commander_cannot_edit_code():
    g = [TaskSpec("a", "commander", "A", "nexus-spire", "nexus-command", ["edit_file"])]
    with pytest.raises(PlanError):
        validate_graph(g)


@pytest.mark.parametrize("bad", ["", "fix", "x" * 5000])
def test_prompt_validation(bad):
    with pytest.raises(PlanError):
        validate_prompt(bad)


# ------------------------------------------------------------------ sandbox
def test_confine_blocks_escapes(tmp_path):
    (tmp_path / "ok.txt").write_text("hi")
    assert confine(tmp_path, "ok.txt") == (tmp_path / "ok.txt").resolve()
    for bad in ["../x", "/etc/passwd", "a/../../x", ".git/config", ""]:
        with pytest.raises(SandboxViolation):
            confine(tmp_path, bad)
    (tmp_path / "link").symlink_to("/etc")
    with pytest.raises(SandboxViolation):
        confine(tmp_path, "link/passwd")


@pytest.mark.parametrize("argv", [["bash", "-c", "id"], ["python", "-c", "print(1)"], ["git", "push"], ["git", "-C", "/", "clone", "x"],
                                  ["curl", "http://example.com"], ["python", "-m", "pip", "install", "x"]])
def test_sandbox_refuses_non_allowlisted(tmp_path, argv):
    with pytest.raises(SandboxViolation):
        ProcessSandbox().run(argv, tmp_path, 5, tmp_path)


def test_sandbox_git_c_must_stay_inside(tmp_path):
    with pytest.raises(SandboxViolation):
        ProcessSandbox().run(["git", "-C", "/tmp", "status"], tmp_path, 5, tmp_path)


def test_sandbox_scrubs_secrets_and_blocks_network(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_env.py").write_text(
        "import os, socket\n"
        "def test_no_secret():\n    assert 'ANTHROPIC_API_KEY' not in os.environ\n"
        "def test_no_network():\n"
        "    s = socket.socket(); s.settimeout(2)\n"
        "    try:\n        s.connect(('1.1.1.1', 443)); assert False, 'network reachable'\n"
        "    except OSError:\n        pass\n"
    )
    r = ProcessSandbox().run(["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"], tmp_path, 60, tmp_path)
    if not r.network_isolated:
        pytest.skip("network namespaces unavailable on this host")
    assert r.exit_code == 0, r.output


def test_sandbox_timeout_kills(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_slow.py").write_text("import time\ndef test_slow():\n    time.sleep(30)\n")
    r = ProcessSandbox().run(["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"], tmp_path, 2, tmp_path)
    assert r.timed_out and r.duration_ms < 10_000


def test_docker_sandbox_command_is_locked_down(tmp_path):
    from services.tools.sandbox import DockerSandbox
    cmd = DockerSandbox().command(["python", "-m", "pytest"], tmp_path, tmp_path)
    for flag in ["--network", "none", "--read-only", "--cap-drop", "ALL", "no-new-privileges", "--pids-limit"]:
        assert flag in cmd
    assert "/var/run/docker.sock" not in " ".join(cmd)


# ------------------------------------------------------------------ model gateway
def _gateway_with(handler, provider="anthropic"):
    from services.model_gateway.gateway import AnthropicAdapter, ModelGateway, OpenAIAdapter
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://x")
    adapter = AnthropicAdapter("k", "m", client) if provider == "anthropic" else OpenAIAdapter("k", "m", client)
    return ModelGateway({provider: adapter}, max_retries=2, timeout=5)


def test_anthropic_adapter_parses_usage():
    from services.model_gateway.gateway import ModelRequest
    gw = _gateway_with(lambda r: httpx.Response(200, json={"content": [{"type": "text", "text": "hi"}],
                                                           "usage": {"input_tokens": 1000, "output_tokens": 500}, "stop_reason": "end_turn"}))
    res = gw.complete(ModelRequest(system="s", prompt="p"))
    assert res.text == "hi" and res.input_tokens == 1000 and res.output_tokens == 500
    assert res.estimated_cost_usd == pytest.approx(1000 / 1e6 * 3 + 500 / 1e6 * 15)


def test_openai_adapter_parses_usage():
    from services.model_gateway.gateway import ModelRequest
    gw = _gateway_with(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                                                           "usage": {"prompt_tokens": 10, "completion_tokens": 2}}), "openai")
    res = gw.complete(ModelRequest(system="s", prompt="p"), preferred_provider="openai")
    assert (res.text, res.input_tokens, res.output_tokens) == ("ok", 10, 2)


def test_gateway_retries_rate_limits_then_succeeds(monkeypatch):
    from services.model_gateway import gateway as g
    monkeypatch.setattr(g.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def handler(r):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}], "usage": {}})
    assert _gateway_with(handler).complete(g.ModelRequest(system="s", prompt="p")).text == "ok"
    assert calls["n"] == 3


@pytest.mark.parametrize("status,kind,retries", [(401, "auth", 1), (400, "bad_request", 1), (500, "server", 3)])
def test_gateway_normalizes_errors(monkeypatch, status, kind, retries):
    from services.model_gateway import gateway as g
    monkeypatch.setattr(g.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def handler(r):
        calls["n"] += 1
        return httpx.Response(status, text="nope")
    with pytest.raises(g.ProviderError) as e:
        _gateway_with(handler).complete(g.ModelRequest(system="s", prompt="p"))
    assert e.value.kind == kind and calls["n"] == retries


def test_context_window_truncation():
    from services.model_gateway.gateway import fit_context
    out = fit_context("a" * 1000 + "b" * 1000, limit=500)
    assert len(out) <= 560 and out.startswith("a") and out.endswith("b") and "truncated" in out


def test_no_provider_means_unavailable():
    from services.model_gateway.gateway import ModelGateway, ModelRequest, ProviderError
    with pytest.raises(ProviderError) as e:
        ModelGateway({}).complete(ModelRequest(system="s", prompt="p"))
    assert e.value.kind == "unavailable"


# ------------------------------------------------------------------ auth
def _req(headers=None, path="/api/health", query=b""):
    from starlette.requests import Request
    return Request({"type": "http", "path": path, "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
                    "query_string": query, "method": "GET"})


def test_token_auth(monkeypatch):
    from fastapi import HTTPException
    from services.core import auth, config
    monkeypatch.setenv("AICIV_API_TOKEN", "s3cret")
    config.get_settings.cache_clear()
    with pytest.raises(HTTPException):
        auth.authenticate(_req())
    with pytest.raises(HTTPException):
        auth.authenticate(_req({"Authorization": "Bearer wrong"}))
    assert auth.authenticate(_req({"Authorization": "Bearer s3cret"})).role == "owner"
    # query token accepted only on the stream endpoint
    with pytest.raises(HTTPException):
        auth.authenticate(_req(query=b"access_token=s3cret"))
    assert auth.authenticate(_req(path="/api/stream", query=b"access_token=s3cret")).mode == "token"


def test_supabase_jwt_roles(monkeypatch):
    from fastapi import HTTPException
    from services.core import auth, config
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "x" * 32)
    config.get_settings.cache_clear()
    tok = jwt.encode({"sub": "u1", "aud": "authenticated", "app_metadata": {"role": "viewer"}}, "x" * 32, algorithm="HS256")
    p = auth.authenticate(_req({"Authorization": f"Bearer {tok}"}))
    assert p.role == "viewer"
    with pytest.raises(HTTPException):
        p.require("operator")
    forged = jwt.encode({"sub": "u1", "aud": "authenticated", "app_metadata": {"role": "owner"}}, "y" * 32, algorithm="HS256")
    with pytest.raises(HTTPException):
        auth.authenticate(_req({"Authorization": f"Bearer {forged}"}))


def test_rate_limiter():
    from fastapi import HTTPException
    from services.core.auth import RateLimiter
    rl = RateLimiter(rate_per_minute=1, burst=2)
    rl.check("a")
    rl.check("a")
    with pytest.raises(HTTPException):
        rl.check("a")
    rl.check("b")


# ------------------------------------------------------------------ memory + redaction
def test_verified_memory_requires_source():
    from services.core import db
    from services.core.config import load_seed
    from services.core.events import transaction
    from services.memory import store
    db.init_db()
    o = load_seed()["organization_id"]
    with transaction() as conn:
        with pytest.raises(ValueError):
            store.remember(conn, org_id=o, scope="project", trust="verified", content="x", source="model said so")
        mid = store.remember(conn, org_id=o, scope="project", trust="hypothesis", content="maybe", source="mission:1")
        assert store.search(conn, o, "may")[0]["trust"] == "hypothesis"
        assert store.forget(conn, o, mid)
        store.remember(conn, org_id=o, scope="shared", trust="hypothesis", content="old", source="m", ttl_days=-1)
        assert store.search(conn, o, "old") == []
        assert store.purge_expired(conn) == 1


def test_secret_redaction():
    from services.tools.registry import redact
    s = redact("key sk-ant-abcdefghijklmnop token ghp_" + "a" * 30)
    assert "sk-ant" not in s and "ghp_" not in s
