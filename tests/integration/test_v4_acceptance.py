"""V4.0 acceptance scenario, end to end, with a recorded execution log.

A Haiku research agent finds an app-market opportunity from permitted sources (labeled fixture data here,
because no marketplace credentials or network exist in CI) → cited research package travels to the Opus
General Manager → GM routes it to App Studio → App Studio builds a working prototype → QA runs the real
tests on the exact bundle → GM documents a 12-category review → release package reaches the Owner's Tower →
release is refused until the owner approves that exact artifact → approval → release executes → tampering
afterwards invalidates the approval and forces a rebuild and renewed review.

Set AICIV_RECORD_ACCEPTANCE=1 to write the log to docs/acceptance/.
"""
import json
import os
import time
from pathlib import Path

import jsonschema
import pytest
from fastapi.testclient import TestClient

from services.core import config
from tests.conftest import ROOT, wait_for
from tests.integration.test_missions import SCHEMA, FakeGateway


@pytest.fixture
def v4env(monkeypatch):
    monkeypatch.setenv("AICIV_RESEARCH_MODE", "fixture")
    monkeypatch.setenv("AICIV_BELT_SPEED", "400")
    monkeypatch.setenv("AICIV_TICK_SCALE", "0.02")
    config.get_settings.cache_clear()


def _client(gateway=None):
    from services.api.main import app
    app.state.gateway = gateway
    return TestClient(app)


def opp_of(c):
    return wait_for(lambda: (o := c.get("/api/opportunities").json()["opportunities"]) and o[0])


def dossier(c, oid):
    return c.get(f"/api/opportunities/{oid}").json()


def until_owner(c, oid, timeout=60):
    return wait_for(lambda: (d := dossier(c, oid))["awaiting_owner"] and d, timeout=timeout)


def write_log(c, name: str, lines: list[str]) -> None:
    events = c.get("/api/events?after=0&limit=2000").json()["events"]
    body = "\n".join(lines) + "\n\n## Event log\n\n| # | event | agent | mode | detail |\n|---|---|---|---|---|\n"
    agents = {a["id"]: a["name"] for a in c.get("/api/snapshot").json()["agents"]}
    for e in events:
        p = e["payload"]
        detail = p.get("title") or p.get("summary") or p.get("body") or p.get("tool") or p.get("to") or p.get("outcome") or p.get("package_type") or ""
        body += f"| {e['sequence']} | {e['event_type']} | {agents.get(e['agent_id'], '')} | {e['execution_mode']} | {str(detail)[:90].replace('|', '/')} |\n"
    out = Path(os.environ.get("AICIV_ACCEPTANCE_DIR", "/tmp")) / f"{name}.md"
    if os.environ.get("AICIV_RECORD_ACCEPTANCE") == "1":
        out = ROOT / "docs" / "acceptance" / f"{name}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body)


def test_acceptance_research_to_owner_gated_release(v4env, tmp_path):
    log = ["# V4.0 acceptance run", "", f"Recorded {time.strftime('%Y-%m-%d %H:%M:%S %Z')} by tests/integration/test_v4_acceptance.py.",
           "Research data: **labeled fixtures** (no marketplace credentials or network in the test environment).", ""]
    with _client() as c:
        snap = c.get("/api/snapshot").json()
        gm = next(a for a in snap["agents"] if a["key"] == "general_manager")
        pip = next(a for a in snap["agents"] if a["key"] == "research_apps")
        assert gm["model_name"] == "claude-opus-5-5" and gm["tier"] == "general_manager"
        assert pip["model_name"] == "claude-haiku-5-5" and pip["supervisor_agent_id"] != gm["id"]  # Pip → Lumen → Atlas
        r = c.post("/api/research", json={"source": "apple_charts", "query": "productivity"})
        assert r.status_code == 201
        o = opp_of(c)
        d = until_owner(c, o["id"])
        opp = d["opportunity"]
        log.append(f"1. Research: **{opp['title']}** scored {opp['opportunity_score']:.2f} ({opp['confidence']}), data_mode `{opp['data_mode']}`.")

        # cited, labeled evidence; no invented sales
        assert opp["data_mode"] == "fixture" and any("fixture_data" in f for f in opp["risk_flags"])
        assert d["findings"] and all(f["source_url"].startswith("fixture://") and f["data_mode"] == "fixture" for f in d["findings"])
        assert all(f["measurement_type"] != "direct_sales" for f in d["findings"])
        assert {s["component"] for s in d["scores"]} == {"demand", "momentum", "saturation", "differentiation", "feasibility",
                                                         "production_cost", "monetization", "policy_risk", "owner_alignment"}
        assert all(s["evidence"] for s in d["scores"])

        # physical handoffs, in order, each one received by the right building
        types = [p["package_type"] for p in d["packages"]]
        assert types == ["research_brief", "product_proposal", "code_artifact", "test_report", "release_package"]
        assert [(p["origin_district"], p["destination_district"]) for p in d["packages"]] == [
            ("data-observatory", "nexus-spire"), ("nexus-spire", "code-forge"), ("code-forge", "sentinel-citadel"),
            ("sentinel-citadel", "nexus-spire"), ("nexus-spire", "owners-tower")]
        assert all(p["status"] == "RECEIVED" and p["delivered_at"] and p["route"] for p in d["packages"])
        log.append("2. Packages: " + " → ".join(f"{p['package_type']} ({p['origin_district']}→{p['destination_district']})" for p in d["packages"]))

        decisions = [(x["decision_type"], x["outcome"]) for x in d["decisions"]]
        assert ("opportunity_review", "route") in decisions and ("acceptance", "accepted") in decisions
        assert ("release_review", "APPROVED_FOR_OWNER_REVIEW") in decisions
        log.append(f"3. Manager decisions: {decisions}")

        # QA tested the exact bundle under review
        tr = d["test_report"]
        assert tr["failed"] == 0 and tr["passed"] >= 6 and tr["bundle_digest"] == d["bundle"]["digest"] == d["manager_review"]["artifact_digest"]
        assert len(d["checklist"]) == 12 and not [x for x in d["checklist"] if x["status"] == "fail"]
        log.append(f"4. QA: {tr['summary_line']} on bundle `{tr['bundle_digest'][:16]}`; manager checklist " +
                   ", ".join(f"{x['category']}={x['status']}" for x in sorted(d["checklist"], key=lambda r: r["category"])))

        # release refused without owner approval: a release mission with no valid authorization is denied at the tool boundary
        from services.core import db
        from services.core.events import transaction
        from services.management.pipeline import create_mission
        with transaction() as conn:
            rogue = create_mission(conn, org_id=opp["organization_id"], kind="release", title="Unauthorized release attempt",
                                   prompt="release without approval", params={"authorization_id": "00000000-0000-4000-8000-00000000dead"},
                                   opportunity_id=opp["id"], created_by=gm["id"])
        from services.api.main import state
        state.worker.enqueue(rogue)
        m = wait_for(lambda: (x := c.get(f"/api/missions/{rogue}").json())["mission"]["status"] in ("FAILED", "COMPLETED") and x)
        assert m["mission"]["status"] == "FAILED"
        assert any(t["tool_name"] == "submit_release" and t["status"] == "DENIED" and "release refused" in t["output_excerpt"] for t in m["tool_executions"])
        assert not list((Path(os.environ["AICIV_DATA_DIR"]) / "releases").glob("**/*.zip"))
        log.append("5. Release attempted without owner approval: **refused** at the tool boundary (`submit_release` DENIED), nothing written.")

        # the owner must approve the exact digest
        bad = c.post(f"/api/opportunities/{opp['id']}/owner-decision", json={"decision": "APPROVE", "artifact_digest": "0" * 64})
        assert bad.status_code == 409
        ok = c.post(f"/api/opportunities/{opp['id']}/owner-decision", json={"decision": "APPROVE", "artifact_digest": d["bundle"]["digest"],
                                                                            "note": "ship the prototype"})
        assert ok.status_code == 200, ok.text
        auth_id = ok.json()["authorization_id"]
        log.append(f"6. Owner approved digest `{d['bundle']['digest'][:16]}` → authorization `{auth_id[:8]}` (a wrong digest was rejected first).")
        d2 = wait_for(lambda: (x := dossier(c, opp["id"]))["releases"] and x)
        rel = d2["releases"][0]
        assert rel["artifact_digest"] == d["bundle"]["digest"]
        released = Path(os.environ["AICIV_DATA_DIR"]) / rel["destination"]
        assert released.exists()
        log.append(f"7. Released to `{rel['destination']}` (local release channel).")

        # owner decisions and authorizations are append-only
        with pytest.raises(Exception):
            with transaction() as conn:
                conn.execute(db.owner_decisions.update().values(decision="REJECT"))

        # tamper with the approved bundle → approval invalidated → rebuild → renewed manager and owner review
        bundle_path = Path(next(a for a in [db.get_engine().connect().execute(
            db.artifacts.select().where(db.artifacts.c.id == d["bundle"]["artifact_id"])).first()]).storage_path)
        bundle_path.write_bytes(bundle_path.read_bytes() + b"tampered")
        d3 = wait_for(lambda: (x := dossier(c, opp["id"]))["awaiting_owner"] and x["bundle"]["artifact_id"] != d["bundle"]["artifact_id"] and x, timeout=60)
        assert any(a["id"] == auth_id and a["invalidated"] for a in d3["authorizations"])
        assert d3["opportunity"]["revision_count"] >= 1
        assert d3["manager_review"]["artifact_id"] == d3["bundle"]["artifact_id"] != d["manager_review"]["artifact_id"]
        # the owner's earlier approval does not carry over to the rebuilt artifact
        assert d3["opportunity"]["status"] == "OWNER_APPROVAL"
        log.append(f"8. Bundle file tampered after release: approval `{auth_id[:8]}` **invalidated**; App Studio rebuilt "
                   f"a new artifact `{d3['bundle']['artifact_id'][:8]}` from the template (identical bytes rebuild to the same digest "
                   f"`{d3['bundle']['digest'][:16]}`, but approvals are tied to the artifact, so QA retested it, the manager re-reviewed it, "
                   "and the owner must decide again).")
        # the old authorization can no longer release anything
        with transaction() as conn:
            rogue2 = create_mission(conn, org_id=opp["organization_id"], kind="release", title="Replay old approval",
                                    prompt="replay", params={"authorization_id": auth_id}, opportunity_id=opp["id"], created_by=gm["id"])
        state.worker.enqueue(rogue2)
        m2 = wait_for(lambda: (x := c.get(f"/api/missions/{rogue2}").json())["mission"]["status"] in ("FAILED", "COMPLETED") and x)
        assert m2["mission"]["status"] == "FAILED"
        log.append("9. Replaying the old approval: **refused**.")

        # every event in the run follows the versioned contract
        for e in c.get("/api/events?after=0&limit=2000").json()["events"]:
            jsonschema.validate(e, SCHEMA)
        types = {e["event_type"] for e in c.get("/api/events?after=0&limit=2000").json()["events"]}
        for t in ["research.started", "research.finding_created", "research.opportunity_identified", "research.completed",
                  "manager.review_started", "manager.review_completed", "manager.goal_assigned", "manager.revision_requested",
                  "package.dispatched", "package.in_transit", "package.arrived", "release.manager_approved",
                  "release.owner_approval_requested", "release.owner_approved", "release.authorized", "release.invalidated",
                  "release.executed", "report.submitted"]:
            assert t in types, t
        write_log(c, "v4-acceptance-log", log)


def test_live_mode_uses_opus_for_judgment_only_and_haiku_for_research(v4env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    config.get_settings.cache_clear()
    gw = FakeGateway()

    def complete(req, preferred_provider="anthropic"):
        gw.calls.append(req)
        from services.model_gateway.gateway import ModelResponse
        if "propose a small app" in req.prompt:
            text = json.dumps({"app_name": "Deep Streak", "tagline": "Focus daily.", "features": ["focus_sessions", "streaks"], "keywords": ["focus"]})
        elif "research packet" in req.prompt:
            text = json.dumps({"proceed": True, "note": "Demand evidence is a ranking proxy; fine for a prototype."})
        elif "release recommendation" in req.prompt:
            text = json.dumps({"summary": "All checks pass on the reviewed bundle.", "concern": False})
        else:
            text = "ok"
        return ModelResponse(text, "anthropic", req.model or "default", 500, 100, 0.002, 3)
    gw.complete = complete
    with _client(gw) as c:
        c.post("/api/research", json={"source": "apple_charts", "query": "productivity"})
        o = opp_of(c)
        d = until_owner(c, o["id"])
        assert d["opportunity"]["spec"]["app_name"] == "Deep Streak"
        models = [x.model for x in gw.calls]
        assert "claude-haiku-5-5" in models and "claude-opus-5-5" in models
        opus_calls = [x for x in gw.calls if x.model == "claude-opus-5-5"]
        assert len(opus_calls) == 2, "Opus is called only for the packet review and the release review"
        assert all(x["method"] in ("rules", "model") for x in d["decisions"])
        assert d["manager_review"]["method"] == "model" and d["manager_review"]["model"] == "claude-opus-5-5"


def test_gm_model_can_only_tighten(v4env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    config.get_settings.cache_clear()
    gw = FakeGateway()

    def complete(req, preferred_provider="anthropic"):
        from services.model_gateway.gateway import ModelResponse
        text = json.dumps({"proceed": False, "note": "Too crowded."}) if "research packet" in req.prompt else json.dumps(
            {"app_name": "X", "features": ["streaks"]})
        return ModelResponse(text, "anthropic", req.model or "m", 10, 10, 0.0001, 1)
    gw.complete = complete
    with _client(gw) as c:
        c.post("/api/research", json={"source": "apple_charts", "query": "productivity"})
        o = opp_of(c)
        final = wait_for(lambda: (x := dossier(c, o["id"]))["opportunity"]["status"] == "REJECTED" and x)
        assert any(x["decision_type"] == "opportunity_review" and x["outcome"] == "reject" and x["method"] == "model" for x in final["decisions"])
        assert not [p for p in final["packages"] if p["package_type"] == "product_proposal"]


def test_low_confidence_research_never_reaches_production(v4env):
    with _client() as c:
        c.post("/api/research", json={"source": "apple_charts", "query": "finance"})  # one fixture row → low confidence
        m = wait_for(lambda: (ms := c.get("/api/missions").json()["missions"]) and ms[0]["status"] in ("COMPLETED", "FAILED") and ms[0])
        opps = c.get("/api/opportunities").json()["opportunities"]
        assert not opps or all(o["status"] in ("REJECTED", "RESEARCHED", "MANAGER_REVIEW") for o in opps)
        time.sleep(0.5)
        assert not [x for x in c.get("/api/missions").json()["missions"] if x["kind"] == "build_prototype"]


def test_spend_beyond_delegated_limit_escalates_to_owner(v4env, monkeypatch):
    monkeypatch.setenv("AICIV_GM_DELEGATED_LIMIT_USD", "0.5")
    with _client() as c:
        c.post("/api/research", json={"source": "apple_charts", "query": "productivity"})
        o = opp_of(c)
        wait_for(lambda: any(x["outcome"] == "escalate" for x in dossier(c, o["id"])["decisions"]))
        time.sleep(0.3)
        assert dossier(c, o["id"])["opportunity"]["status"] == "MANAGER_REVIEW"
        assert c.post(f"/api/opportunities/{o['id']}/owner-commit", json={"approve": True}).status_code == 200
        wait_for(lambda: dossier(c, o["id"])["opportunity"]["status"] in ("IN_PRODUCTION", "QUALITY_REVIEW", "MANAGER_APPROVAL", "OWNER_APPROVAL"))


def test_owner_request_changes_and_defer_paths(v4env):
    with _client() as c:
        c.post("/api/research", json={"source": "apple_charts", "query": "productivity"})
        o = opp_of(c)
        d = until_owner(c, o["id"])
        first = d["bundle"]["digest"]
        assert c.post(f"/api/opportunities/{o['id']}/owner-decision", json={"decision": "REQUEST_CHANGES", "artifact_digest": first,
                                                                            "note": "rename it"}).status_code == 200
        d2 = until_owner(c, o["id"])
        assert d2["opportunity"]["revision_count"] == 1 and len(d2["owner_decisions"]) == 1
        assert c.post(f"/api/opportunities/{o['id']}/owner-decision", json={"decision": "DEFER", "artifact_digest": d2["bundle"]["digest"]}).status_code == 200
        assert dossier(c, o["id"])["opportunity"]["status"] == "DEFERRED"
        assert c.post(f"/api/opportunities/{o['id']}/reopen").status_code == 200
        assert dossier(c, o["id"])["opportunity"]["status"] == "OWNER_APPROVAL"


def test_viewer_cannot_approve_releases(v4env, monkeypatch):
    import jwt
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "s" * 32)
    config.get_settings.cache_clear()
    tok = lambda role: jwt.encode({"sub": "u", "aud": "authenticated", "app_metadata": {"role": role}}, "s" * 32, algorithm="HS256")
    with _client() as c:
        h = {"Authorization": f"Bearer {tok('admin')}"}
        r = c.post("/api/opportunities/x/owner-decision", json={"decision": "APPROVE", "artifact_digest": "a" * 64}, headers=h)
        assert r.status_code == 403  # even admins and the GM cannot make the owner's release decision
