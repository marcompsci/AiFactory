"""V4 unit tests: logistics graph and durable routing, scoring, connectors, hierarchy, state machines, bundles."""
import json
import os
import time
from pathlib import Path

import httpx
import pytest

from services.core.config import load_districts
from services.core.state import InvalidTransition, assert_v4_transition
from services.logistics.graph import build, shortest_path


def _segments():
    nodes, segs = build(load_districts())
    return nodes, [{"id": s.id, "from_node": s.from_node, "to_node": s.to_node, "length": s.length, "status": "UP"} for s in segs]


# ------------------------------------------------------------------ graph
def test_every_district_can_reach_every_other():
    nodes, segs = _segments()
    districts = [d["id"] for d in load_districts()]
    assert len(nodes) == 3 * len(districts)
    for a in districts:
        for b in districts:
            if a != b:
                assert shortest_path(segs, f"{a}:dispatch", f"{b}:receiving"), (a, b)


def test_ring_gives_an_alternative_path_when_a_belt_fails():
    _, segs = _segments()
    best = shortest_path(segs, "data-observatory:dispatch", "nexus-spire:receiving")
    ring = next(s for s in best if s["from_node"].startswith("junction:") and s["to_node"].startswith("junction:"))
    ring["status"] = "DOWN"
    alt = shortest_path(segs, "data-observatory:dispatch", "nexus-spire:receiving")
    assert alt and ring["id"] not in [s["id"] for s in alt]


def test_congestion_changes_the_choice():
    _, segs = _segments()
    base = shortest_path(segs, "code-forge:dispatch", "sentinel-citadel:receiving")
    busy = {s["id"] for s in base if s["from_node"].startswith("junction:") and s["to_node"].startswith("junction:")}
    alt = shortest_path(segs, "code-forge:dispatch", "sentinel-citadel:receiving", cost=lambda s: s["length"] * (50 if s["id"] in busy else 1))
    assert not busy & {s["id"] for s in alt}


# ------------------------------------------------------------------ durable routing
@pytest.fixture
def dbconn(monkeypatch):
    from services.core import db
    db.init_db()
    return db


def test_package_lifecycle_is_backend_driven(dbconn, monkeypatch):
    from services.core.events import transaction
    from services.logistics import service as L
    monkeypatch.setenv("AICIV_BELT_SPEED", "1000000")
    org = json.loads((Path(__file__).parents[2] / "packages/shared-types/seed/agents.json").read_text())["organization_id"]
    with transaction() as conn:
        pid = L.create_package(conn, org_id=org, package_type="code_artifact", origin="code-forge", destination="sentinel-citadel")
        p = L._package(conn, pid)
        assert p.status == "IN_TRANSIT" and p.route and p.eta
    time.sleep(0.01)
    with transaction() as conn:
        assert L.tick(conn)["arrived"] == 1
        assert L._package(conn, pid).status == "ARRIVED"
        L.receive(conn, pid)
        assert L._package(conn, pid).status == "RECEIVED"
        transitions = [r.to_status for r in conn.execute(dbconn.package_transitions.select().where(dbconn.package_transitions.c.package_id == pid))]
    assert transitions == ["QUEUED", "IN_TRANSIT", "ARRIVED", "RECEIVED"]


def test_reroute_and_failed_delivery_recovery(dbconn, monkeypatch):
    from sqlalchemy import update

    from services.core.events import transaction
    from services.logistics import service as L
    monkeypatch.setenv("AICIV_BELT_SPEED", "0.001")  # slow: package stays on its first belt
    org = json.loads((Path(__file__).parents[2] / "packages/shared-types/seed/agents.json").read_text())["organization_id"]
    with transaction() as conn:
        pid = L.create_package(conn, org_id=org, package_type="test_report", origin="sentinel-citadel", destination="nexus-spire")
        p = L._package(conn, pid)
        ring = [sid for sid in p.route if sid.startswith("junction:") and "->junction:" in sid][0]
        L.set_route_status(conn, ring, "DOWN")
        assert L.tick(conn)["rerouted"] == 1
        p2 = L._package(conn, pid)
        assert ring not in p2.route and p2.status == "IN_TRANSIT"
        # cut every belt into the destination: the package fails, then retries once a belt is back
        conn.execute(update(dbconn.logistics_routes).where(dbconn.logistics_routes.c.to_node == "nexus-spire:receiving").values(status="DOWN"))
        L.tick(conn)
        assert L._package(conn, pid).status == "DELIVERY_FAILED"
        conn.execute(update(dbconn.logistics_routes).values(status="UP"))
        conn.execute(update(dbconn.logistics_packages).where(dbconn.logistics_packages.c.id == pid).values(next_attempt_at="2000-01-01T00:00:00+00:00"))
        assert L.tick(conn)["retried"] == 1
        assert L._package(conn, pid).status == "IN_TRANSIT"


def test_package_state_machine():
    assert_v4_transition("package", "IN_TRANSIT", "ARRIVED")
    for a, b in [("ARRIVED", "IN_TRANSIT"), ("RECEIVED", "ARRIVED"), ("QUEUED", "RECEIVED")]:
        with pytest.raises(InvalidTransition):
            assert_v4_transition("package", a, b)


@pytest.mark.parametrize("a,b", [("RESEARCHED", "IN_PRODUCTION"), ("MANAGER_APPROVAL", "RELEASE_AUTHORIZED"),
                                 ("QUALITY_REVIEW", "OWNER_APPROVAL"), ("CANCELLED", "MANAGER_REVIEW")])
def test_opportunity_cannot_skip_gates(a, b):
    with pytest.raises(InvalidTransition):
        assert_v4_transition("opportunity", a, b)


# ------------------------------------------------------------------ scoring
def _finding(entries, mode="fixture"):
    return {"measurement_type": "ranking", "metrics": {"entries": entries, "chart_size": 50}, "data_mode": mode, "confidence": "medium"}


def test_scoring_components_and_flags(monkeypatch):
    from services.research.scoring import COMPONENTS, score_app_category
    entries = [{"rank": 4, "previous_rank": 9, "rating": 4.2}, {"rank": 22, "previous_rank": 40, "rating": 4.1}, {"rank": 38, "previous_rank": None, "rating": 3.9}]
    total, comps, conf, flags = score_app_category("productivity", [_finding(entries)], 1.5)
    assert set(comps) == set(COMPONENTS) and 0 < total < 1
    assert all(comps[k].evidence for k in COMPONENTS)
    assert any(f.startswith("fixture_data") for f in flags)
    _, comps2, _, flags2 = score_app_category("finance", [_finding(entries, "live")], 1.5)
    assert comps2["policy_risk"].score < comps["policy_risk"].score and "high_policy_risk_category" in flags2


def test_weights_are_configurable(monkeypatch):
    from services.research.scoring import score_app_category
    entries = [{"rank": 4, "previous_rank": 9, "rating": 4.2}, {"rank": 22, "previous_rank": 40, "rating": 4.1}]
    base, *_ = score_app_category("productivity", [_finding(entries)], 1.5)
    monkeypatch.setenv("AICIV_SCORE_WEIGHTS", json.dumps({"demand": 20}))
    heavy, *_ = score_app_category("productivity", [_finding(entries)], 1.5)
    assert heavy != base


def test_no_evidence_means_low_confidence():
    from services.research.scoring import score_app_category
    _, _, conf, flags = score_app_category("productivity", [], 1.5)
    assert conf == "low" and "no_demand_evidence" in flags


# ------------------------------------------------------------------ connectors
def test_fixture_mode_is_labeled(monkeypatch):
    from services.research.connectors import AppleChartsConnector, EtsyConnector
    monkeypatch.setenv("AICIV_RESEARCH_MODE", "fixture")
    r = AppleChartsConnector().fetch("productivity")
    assert r.data_mode == "fixture" and r.source_url.startswith("fixture://") and "FIXTURE" in r.notice
    assert r.measurement_type == "ranking" and all("Productivity" in e["genre"] for e in r.items)
    e = EtsyConnector().fetch("planner")
    assert e.measurement_type == "listing_count" and e.data_mode == "fixture"


def test_live_mode_never_falls_back_to_fixtures(monkeypatch):
    from services.research.connectors import EtsyConnector, Unavailable
    monkeypatch.setenv("AICIV_RESEARCH_MODE", "live")
    monkeypatch.delenv("ETSY_API_KEY", raising=False)
    with pytest.raises(Unavailable):
        EtsyConnector().fetch("planner")


def test_auto_mode_records_why_live_was_unavailable(monkeypatch):
    from services.research.connectors import DepopConnector
    monkeypatch.setenv("AICIV_RESEARCH_MODE", "auto")
    r = DepopConnector().fetch("skate tee")
    assert r.data_mode == "fixture" and "partner" in r.extra["live_unavailable_reason"]


def test_apple_live_parses_public_feed_without_sales(monkeypatch):
    from services.research.connectors import AppleChartsConnector
    monkeypatch.setenv("AICIV_RESEARCH_MODE", "live")
    feed = {"feed": {"results": [{"name": "Focus A", "genres": [{"name": "Productivity"}], "url": "https://apps.apple.com/x"},
                                 {"name": "Game B", "genres": [{"name": "Games"}]}]}}
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=feed)))
    r = AppleChartsConnector(client).fetch("productivity")
    assert r.data_mode == "live" and r.source_url.startswith("https://rss.marketingtools.apple.com/")
    assert [i["name"] for i in r.items] == ["Focus A"] and r.measurement_type == "ranking"


def test_etsy_respects_rate_limit_response(monkeypatch):
    from services.research.connectors import EtsyConnector, Unavailable
    monkeypatch.setenv("AICIV_RESEARCH_MODE", "live")
    monkeypatch.setenv("ETSY_API_KEY", "k")
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429)))
    with pytest.raises(Unavailable, match="rate limit"):
        EtsyConnector(client).fetch("planner")


def test_research_cache_dedupes_and_limits_apply(dbconn, monkeypatch):
    from sqlalchemy import update

    from services.core.events import transaction
    from services.research import service as R
    monkeypatch.setenv("AICIV_RESEARCH_MODE", "fixture")
    org = json.loads((Path(__file__).parents[2] / "packages/shared-types/seed/agents.json").read_text())["organization_id"]
    agent = "a1000000-0000-4000-8000-000000000008"
    first = R.run(transaction, org_id=org, agent_id=agent, mission_id=None, source_key="apple_charts", query="productivity")
    second = R.run(transaction, org_id=org, agent_id=agent, mission_id=None, source_key="apple_charts", query="Productivity ")
    assert not first["from_cache"] and second["from_cache"]
    assert second["findings"][0]["data_mode"] == "fixture"  # cached fixtures stay labeled as fixtures
    with transaction() as conn:
        conn.execute(update(dbconn.market_sources).values(daily_query_limit=2))
    with pytest.raises(R.ResearchLimit):
        R.run(transaction, org_id=org, agent_id=agent, mission_id=None, source_key="apple_charts", query="games")


# ------------------------------------------------------------------ hierarchy and append-only records
def test_reporting_chain(dbconn):
    from services.management.hierarchy import agent_by_key, chain_of_command, submit_report
    from services.core.events import transaction
    with transaction() as conn:
        pip, lumen, atlas = (agent_by_key(conn, k) for k in ("research_apps", "researcher", "general_manager"))
        assert chain_of_command(conn, pip.id) == [lumen.id, atlas.id]
        assert chain_of_command(conn, atlas.id) == []  # the GM reports to the owner
        rid = submit_report(conn, org_id=pip.organization_id, agent_id=pip.id, kind="blocker", body="source unavailable")
        row = conn.execute(dbconn.agent_reports.select().where(dbconn.agent_reports.c.id == rid)).first()
        assert row.supervisor_agent_id == lumen.id
        with pytest.raises(ValueError):
            submit_report(conn, org_id=pip.organization_id, agent_id=pip.id, kind="score", body="x")


def test_owner_decisions_are_append_only(dbconn):
    from sqlalchemy import exc, insert

    from services.core.events import transaction
    import uuid

    ids = [str(uuid.uuid4()) for _ in range(5)]
    with transaction() as conn:
        if conn.dialect.name == "postgresql":  # this test is about the append-only trigger, not the foreign keys
            conn.exec_driver_sql("set local session_replication_role = replica")
        conn.execute(insert(dbconn.owner_decisions).values(id=ids[0], organization_id=ids[1], opportunity_id=ids[2], manager_review_id=ids[3],
                                                           artifact_id=ids[4], artifact_digest="x" * 64, decision="APPROVE", decided_by=ids[1]))
    for stmt in (dbconn.owner_decisions.update().values(decision="REJECT"), dbconn.owner_decisions.delete()):
        with pytest.raises(exc.DatabaseError):
            with transaction() as conn:
                conn.execute(stmt)


# ------------------------------------------------------------------ bundles and template
def test_bundle_is_deterministic_and_safe(tmp_path):
    from services.studio import bundle as B
    from services.studio.template import render
    src = tmp_path / "src"
    for rel, content in render({"app_name": "Steady Focus", "features": ["streaks"]}).items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text(content)
    d1, m1 = B.make(src, tmp_path / "a.zip")
    d2, _ = B.make(src, tmp_path / "b.zip")
    assert d1 == d2 and B.digest(tmp_path / "a.zip") == d1 and any(f["path"] == "app/core.py" for f in m1)
    (src / "README.md").write_text("changed")
    d3, _ = B.make(src, tmp_path / "c.zip")
    assert d3 != d1
    import zipfile
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("../escape.txt", "x")
    with pytest.raises(ValueError):
        B.extract(evil, tmp_path / "out")


def test_template_prototype_passes_its_own_tests(tmp_path):
    from services.studio.template import render
    from services.tools.sandbox import ProcessSandbox
    for rel, content in render({"app_name": "Steady Focus", "features": ["focus_sessions", "streaks", "daily_goal"]}).items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(content)
    r = ProcessSandbox().run(["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"], tmp_path, 60, tmp_path)
    assert r.exit_code == 0, r.output


def test_manager_verdict_rules():
    from services.management.release import verdict_for
    ok = [("tests", "pass", ""), ("known_limitations", "warn", "")]
    assert verdict_for(ok) == "APPROVED_FOR_OWNER_REVIEW"
    assert verdict_for(ok + [("accessibility", "fail", "")]) == "CHANGES_REQUESTED"
    assert verdict_for(ok + [("privacy", "fail", ""), ("tests", "fail", "")]) == "BLOCKED"
    assert verdict_for(ok + [("market_rationale", "fail", "")]) == "REJECTED"


def test_model_ids_routed_per_agent():
    seed = json.loads((Path(__file__).parents[2] / "packages/shared-types/seed/agents.json").read_text())
    models = {a["key"]: a["model"]["model"] for a in seed["agents"]}
    assert models["general_manager"] == "claude-opus-5-5"
    assert models["research_apps"] == models["research_marketplaces"] == "claude-haiku-5-5"
    assert models["developer"] == "claude-sonnet-5-5"
    from services.model_gateway.gateway import estimate_cost
    assert estimate_cost("anthropic", 1000, 1000, "claude-opus-5-5") > estimate_cost("anthropic", 1000, 1000, "claude-haiku-5-5")


def test_backend_graph_matches_client_fixture():
    """The browser draws belts from the same geometry the backend routes on (see world.test.ts)."""
    fx = json.loads((Path(__file__).parents[2] / "packages/world-engine/src/__fixtures__/graph.json").read_text())
    nodes, segs = build(load_districts())
    assert [n.id for n in nodes] == [n["id"] for n in fx["nodes"]]
    assert [[s.id, s.length] for s in segs] == [[r["id"], r["length"]] for r in fx["routes"]]


def test_model_override_per_agent(monkeypatch):
    monkeypatch.setenv("AICIV_MODEL_RESEARCH_APPS", "claude-haiku-custom")
    from services.core import db
    db.init_db()
    with db.get_engine().connect() as conn:
        assert conn.execute(db.agents.select().where(db.agents.c.key == "research_apps")).first().model_name == "claude-haiku-custom"


def test_logistics_tick_stays_fast_under_load(dbconn, monkeypatch):
    """200 packages in flight: one tick (route checks + arrivals) must stay well under the 1 s tick interval."""
    from services.core.events import transaction
    from services.logistics import service as L
    monkeypatch.setenv("AICIV_BELT_SPEED", "0.5")
    org = json.loads((Path(__file__).parents[2] / "packages/shared-types/seed/agents.json").read_text())["organization_id"]
    districts = [d["id"] for d in load_districts()]
    with transaction() as conn:
        for i in range(200):
            L.create_package(conn, org_id=org, package_type="code_artifact", origin=districts[i % 7], destination=districts[(i + 3) % 7])
    started = time.perf_counter()
    with transaction() as conn:
        L.tick(conn)
    elapsed = time.perf_counter() - started
    print(f"logistics tick with 200 packages: {elapsed * 1000:.0f} ms")
    assert elapsed < 0.9
