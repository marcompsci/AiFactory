"""V5.1 acceptance: owner-directed, read-only free-alternative investigation.

Set AICIV_RECORD_ACCEPTANCE=1 to write docs/acceptance/v51-acceptance-log.md.
"""
import json
import os
import re
import time
from pathlib import Path

import jsonschema
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from services.core import config, db
from services.finance import stepup
from tests.conftest import ROOT, wait_for
from tests.integration.test_missions import SCHEMA
from tests.integration.test_v5_acceptance import all_events, at_tower, request_tool, step_up


@pytest.fixture
def v51env(monkeypatch):
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


def inv_detail(c, iid):
    return c.get(f"/api/finance/investigations/{iid}").json()


def until(c, iid, statuses=("AWAITING_OWNER", "BLOCKED", "FAILED", "CANCELLED"), timeout=120):
    return wait_for(lambda: (d := inv_detail(c, iid))["investigation"]["status"] in statuses and d, timeout=timeout)


def start(c, pid, note="is there a free option?"):
    r = c.post(f"/api/finance/packets/{pid}/decide", json={"decision": "RESEARCH_FREE_ALTERNATIVE", "note": note})
    assert r.status_code == 200, r.text
    return r.json()


def test_acceptance_free_alternative_investigation(v51env):
    log = ["# V5.1 acceptance run: free-alternative investigation", "",
           f"Recorded {time.strftime('%Y-%m-%d %H:%M:%S %Z')} by tests/integration/test_v51_investigation.py.",
           "Candidates come from the bundled **FIXTURE** catalog (labeled everywhere). The sandbox runs real pytest against **FIXTURE "
           "compatibility kits** that model each candidate's documented behavior; no downloaded software is executed. Financial data is "
           "**SIMULATED**.", ""]
    with _client() as c:
        c.post("/api/finance/simulated")
        pid = request_tool(c)
        before = at_tower(c, pid)
        approvals_before = {a["id"]: a["status"] for a in before["approvals"]}

        # 1-3: the owner's research decision authorizes research only; the request stays pending
        r = start(c, pid)
        assert r["request_status"] == "PENDING_OWNER_DECISION" and r["authorizes"] == "research and sandboxed evaluation only"
        iid = r["investigation_id"]
        pk = c.get(f"/api/finance/packets/{pid}").json()
        assert pk["packet"]["status"] == "OWNER_DECISION" and pk["request_status"] == "PENDING_OWNER_DECISION"
        assert {a["id"]: a["status"] for a in pk["approvals"]} == approvals_before
        assert c.post(f"/api/finance/packets/{pid}/decide", json={"decision": "RESEARCH_FREE_ALTERNATIVE"}).status_code == 409  # one at a time
        log.append("1. Owner chose **RESEARCH_FREE_ALTERNATIVE**. The purchase request stayed `PENDING_OWNER_DECISION` with its approval "
                   "requests untouched; a second concurrent investigation was refused (409).")

        d = until(c, iid)
        inv = d["investigation"]
        assert inv["status"] == "AWAITING_OWNER", inv

        # 4, 13: the packet physically travelled bank → observatory → bank → forge → citadel → nexus → tower
        legs = [(x["origin"], x["destination"]) for x in d["packages"]]
        assert legs == [("central-bank", "data-observatory"), ("data-observatory", "central-bank"), ("central-bank", "code-forge"),
                        ("code-forge", "sentinel-citadel"), ("sentinel-citadel", "nexus-spire"), ("nexus-spire", "owners-tower")]
        assert all(x["status"] == "RECEIVED" for x in d["packages"])
        log.append("2. Savings Investigation Packet: " + " → ".join(f"{o}→{t}" for o, t in legs) + " (each leg delivered by the backend).")

        # 5-6: ≤ 5 candidates, each traceable
        cands = d["candidates"]
        assert 1 <= len(cands) <= 5
        for cnd in cands:
            assert cnd["source_url"].startswith("fixture://alternatives/") and cnd["data_mode"] == "fixture"
            assert cnd["license"] and cnd["evidence_as_of"] and cnd["confidence"] in ("low", "medium", "high")
            assert cnd["estimated_costs"]["three_year_minor"] is not None and cnd["limitations"] is not None
            kinds = {e["kind"] for e in cnd["evidence"]}
            assert {"pricing", "license", "features", "maintenance", "documentation"} <= kinds
            assert all(e["source_url"] and e["as_of"] and e["data_mode"] == "fixture" for e in cnd["evidence"])
        log.append(f"3. {len(cands)} candidates, each with source URL, license, pricing evidence (source + as-of), features, maintenance, "
                   "documentation, limitations, estimated costs and confidence:")
        log += [f"   - #{x['rank']} **{x['name']}** ({x['license']}) score {x['assessment']['total_score']:.2f}, three-year "
                f"${x['estimated_costs']['three_year_minor'] / 100:,.0f}{', shortlisted' if x['shortlisted'] else ''}" for x in cands]

        # 7-8: scored and shortlisted; the top candidate is the strongest
        scores = sorted(cands, key=lambda x: x["rank"])
        assert scores[0]["id"] == inv["top_candidate_id"] and sum(x["shortlisted"] for x in cands) == min(3, len(cands))
        assert all(set(x["assessment"]) >= {"compatibility", "security", "functionality", "migration", "total_cost"} for x in cands)

        # 9-10: real sandbox results, reported accurately, reviewed by QA
        ev = d["sandbox_evaluations"][0]
        assert ev["candidate_id"] == inv["top_candidate_id"] and ev["status"] in ("PASSED", "FAILED")
        assert ev["passed"] + ev["failed"] + ev["errors"] == len(ev["results"]) > 0 and ev["kit_sha256"]
        assert "FIXTURE compatibility kit" in ev["subject"]
        failed = [r["requirement"] for r in ev["results"] if r["outcome"] != "passed"]
        assert (ev["status"] == "FAILED") == bool(failed)
        art = c.get(f"/api/artifacts/{ev['artifact_id']}").json()
        assert f"{ev['passed']} passed" in art["content"]
        qa = next(r for r in d["reviews"] if r["stage"] == "qa")
        assert qa["verdict"] == ("gaps_found" if failed else "meets_requirements")
        log.append(f"4. Code Forge ran the requirements in a disposable `{ev['sandbox']}` sandbox (network isolated: {bool(ev['network_isolated'])}): "
                   f"**{ev['status']}**, {ev['passed']} passed / {ev['failed']} failed / {ev['errors']} errors."
                   + (f" Failed: {', '.join(failed)}." if failed else "") + f" QA: {qa['verdict']}: {qa['summary']}")

        # 11-12: manager recommendation is evidence-backed and authorizes nothing
        rec = inv["recommendation"]
        assert rec["authorizes_transaction"] is False and rec["sandbox"]["status"] == ev["status"] and rec["qa"]["verdict"] == qa["verdict"]
        mgr = next(r for r in d["reviews"] if r["stage"] == "manager")
        assert mgr["verdict"] == rec["verdict"]
        pk = c.get(f"/api/finance/packets/{pid}").json()
        assert all(a["status"] in ("REQUESTED", "EXPIRED", "INVALIDATED") for a in pk["approvals"])
        assert not [t for t in c.get("/api/finance/transactions?limit=500").json()["transactions"] if "approved by owner" in t["description"]]
        log.append(f"5. General Manager: **{rec['verdict']}**: {rec['headline']} (authorizes_transaction = false; approvals unchanged; no money moved).")

        # the owner gets a complete comparison: the original plus every candidate
        labels = [x["label"] for x in d["cost_comparisons"]]
        assert any("(requested)" in lbl for lbl in labels) and len(d["cost_comparisons"]) == len(cands) + 1
        log.append("6. Cost comparison delivered to the owner: " + "; ".join(
            f"{x['label']} ${x['three_year_minor'] / 100:,.0f}/3y" for x in sorted(d["cost_comparisons"], key=lambda x: x["three_year_minor"])))

        # 14: a separate, valid owner approval is still required for any money to move
        opts = {a["details"]["option"]: a for a in pk["approvals"] if a["status"] == "REQUESTED"}
        req = opts.get("requested") or next(iter(opts.values()))
        r = c.post(f"/api/finance/packets/{pid}/decide", json={"decision": "APPROVE", "approval_id": req["id"], "payload_hash": req["payload_hash"]})
        assert r.status_code == 401  # no step-up, no purchase
        secret = c.post("/api/finance/stepup/enroll").json()["secret"]
        r = c.post(f"/api/finance/packets/{pid}/decide", json={"decision": "APPROVE", "approval_id": req["id"], "payload_hash": req["payload_hash"]},
                   headers={"X-Step-Up": step_up(c, req["id"], secret)})
        assert r.status_code == 200
        wait_for(lambda: c.get(f"/api/finance/packets/{pid}").json()["packet"]["status"] == "EXECUTED", timeout=60)
        log.append(f"7. Only after a new, explicit owner approval with step-up did the Bill Manager execute the {req['recipient']} purchase "
                   "(simulated).")

        events = all_events(c)
        for e in events:
            jsonschema.validate(e, SCHEMA)
        seq = [e["payload"]["to"] for e in events if e["event_type"] == "finance.investigation_status_changed" and e["payload"]["investigation_id"] == iid]
        assert seq == ["REQUESTED", "RESEARCHING", "EVALUATING", "TESTING", "MANAGER_REVIEW", "AWAITING_OWNER"]
        money = re.compile(r'"(amount|amount_minor|three_year_minor|price_minor|recipient|account_ref)"')
        assert not [e for e in events if e["event_type"].startswith(("finance.", "package.")) and money.search(json.dumps(e["payload"]))]
        log.append("8. Realtime events: " + " → ".join(seq) + ". No amounts or recipients in any finance or package event.")
        log += ["", "## Audit trail", "", "| # | action | actor |", "|---|---|---|"]
        log += [f"| {t['seq']} | {t['action']} | {t['actor_type']} |" for t in inv_detail(c, iid)["audit"]]
    out = Path(os.environ.get("AICIV_ACCEPTANCE_DIR", "/tmp")) / "v51-acceptance-log.md"
    if os.environ.get("AICIV_RECORD_ACCEPTANCE") == "1":
        out = ROOT / "docs" / "acceptance" / "v51-acceptance-log.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(log) + "\n")


def test_investigation_survives_worker_restart_and_reconnection(v51env, monkeypatch):
    with _client() as c:
        c.post("/api/finance/simulated")
        pid = request_tool(c)
        at_tower(c, pid)
        iid = start(c, pid)["investigation_id"]
        wait_for(lambda: inv_detail(c, iid)["investigation"]["status"] in ("RESEARCHING", "EVALUATING"))
        seen = c.get("/api/snapshot").json()["sequence"]
    # the whole process stops (worker, scheduler, stream) and comes back
    from services.core import db as _db
    _db.reset_engine()
    with _client() as c:
        d = until(c, iid)
        assert d["investigation"]["status"] == "AWAITING_OWNER"
        # a reconnecting browser: hydrate from the snapshot, then replay what it missed, in order
        later = [e for e in all_events(c) if e["sequence"] > seen]
        assert [e["sequence"] for e in later] == list(range(seen + 1, seen + 1 + len(later)))
        assert any(e["event_type"] == "finance.investigation_ready" and e["payload"]["investigation_id"] == iid for e in later)


def test_unknown_tool_blocks_without_guessing(v51env):
    with _client() as c:
        c.post("/api/finance/simulated")
        pid = request_tool(c, vendor="Obscure Studio", item="Pro seat", amount=19, justification="Niche plugin the designers asked for")
        at_tower(c, pid)
        iid = start(c, pid)["investigation_id"]
        d = until(c, iid)
        assert d["investigation"]["status"] == "BLOCKED" and "nothing was guessed" in d["investigation"]["reason"]
        assert d["candidates"] == []


def test_owner_decision_during_investigation_cancels_it(v51env):
    with _client() as c:
        c.post("/api/finance/simulated")
        pid = request_tool(c)
        at_tower(c, pid)
        iid = start(c, pid)["investigation_id"]
        assert c.post(f"/api/finance/packets/{pid}/decide", json={"decision": "REJECT", "note": "not now"}).status_code == 200
        d = inv_detail(c, iid)
        assert d["investigation"]["status"] == "CANCELLED" and "owner decided" in d["investigation"]["reason"]


# ------------------------------------------------------------------ backend authorization, not prompts
def _inv_mission(conn, kind="alt_sandbox", agent_key="developer", tools=("sandbox_evaluate_candidate",), inv_id=None):
    from sqlalchemy import insert, update

    from services.management.pipeline import create_mission
    a = conn.execute(select(db.agents).where(db.agents.c.key == agent_key)).first()
    mid = create_mission(conn, org_id=a.organization_id, kind=kind, title="t", prompt="test", params={"investigation_id": inv_id},
                         opportunity_id=None, created_by=a.id)
    conn.execute(update(db.missions).where(db.missions.c.id == mid).values(status="RUNNING"))
    tid = db.new_id()
    conn.execute(insert(db.tasks).values(id=tid, organization_id=a.organization_id, mission_id=mid, agent_id=a.id, key=kind, title="t",
                                         district="code-forge", status="RUNNING", permitted_tools=list(tools), ordinal=0))
    from services.tools.registry import ToolContext
    return ToolContext(mission_id=mid, task_id=tid, agent_id=a.id, org_id=a.organization_id, execution_mode="simulation")


def test_investigation_missions_cannot_spend_cancel_or_deploy():
    from services.core.events import transaction
    from services.tools.registry import REGISTRY, ToolDenied, execute_tool
    db.init_db()
    with transaction() as conn:
        conn.execute(db.agent_capabilities.insert().values(
            agent_id=conn.execute(select(db.agents.c.id).where(db.agents.c.key == "developer")).scalar(), tool_name="execute_financial_action"))
        ctx = _inv_mission(conn, tools=("sandbox_evaluate_candidate", "execute_financial_action", "prepare_pull_request", "request_purchase"))
    for name in ("execute_financial_action", "prepare_pull_request", "request_purchase"):
        with pytest.raises(ToolDenied):
            execute_tool(ctx, name, {"approval_id": "x"})
    # and there is no tool anywhere that cancels a service, moves money between accounts, or deploys to production
    assert not [n for n in REGISTRY if re.search(r"cancel|unsubscribe|transfer|deploy|payout", n)]


def test_investigation_tools_refuse_outside_their_investigation():
    from services.core.events import transaction
    from services.tools.registry import ToolDenied, execute_tool
    db.init_db()
    with transaction() as conn:
        ctx_other = _inv_mission(conn, kind="fix_failing_test", tools=("sandbox_evaluate_candidate",), inv_id="x")
        ctx = _inv_mission(conn, inv_id=db.new_id())
    with pytest.raises(ToolDenied, match="only runs inside an owner-requested investigation"):
        execute_tool(ctx_other, "sandbox_evaluate_candidate", {"investigation_id": "x"})
    with pytest.raises(ToolDenied, match="not working on that investigation"):
        execute_tool(ctx, "sandbox_evaluate_candidate", {"investigation_id": "someone-elses"})


def test_failed_sandbox_runs_are_reported_as_errors(monkeypatch, tmp_path):
    """A kit that cannot even be collected is an ERROR with the reason, never a pass."""
    from types import SimpleNamespace

    from services.core.events import transaction
    from services.finance import alt_research as R
    db.init_db()
    broken = tmp_path / "kits"
    broken.mkdir()
    (broken / "kitbase.py").write_text("")
    (broken / "kit.py").write_text("def export_svg(:\n")  # syntax error
    req = tmp_path / "req.py"
    req.write_text("import kit\n\ndef test_svg_export():\n    assert kit.export_svg({})\n")
    monkeypatch.setattr(R, "kit_files", lambda slug, cat: {"kitbase.py": broken / "kitbase.py", "kit.py": broken / "kit.py",
                                                           "test_requirements.py": req})
    with transaction() as conn:
        org = conn.execute(select(db.organizations.c.id)).scalar()
        pk = db.new_id()
        conn.execute(db.cost_review_packets.insert().values(id=pk, organization_id=org, origin="purchase_request", status="OWNER_DECISION",
                                                            vendor="Figma", item="Pro", amount_minor=1500, currency="USD", interval="month",
                                                            data_mode="simulated"))
        iid = db.new_id()
        conn.execute(db.savings_investigations.insert().values(id=iid, organization_id=org, packet_id=pk, status="TESTING", requested_by=org,
                                                               category="design_tools", data_mode="simulated"))
        cid = db.new_id()
        conn.execute(db.alternative_candidates.insert().values(id=cid, organization_id=org, investigation_id=iid, slug="penpot", name="Penpot",
                                                               source_url="fixture://x", license="MPL-2.0", evidence_as_of="fixture",
                                                               confidence="low", data_mode="fixture"))
    inv = SimpleNamespace(id=iid, organization_id=org, category="design_tools")
    cand = SimpleNamespace(id=cid, name="Penpot", slug="penpot", data_mode="fixture")
    r = R.run_sandbox(transaction, inv, cand, None)
    assert r["status"] == "ERROR" and r["passed"] == 0
    with db.get_engine().connect() as conn:
        ev = conn.execute(select(db.sandbox_evaluations).where(db.sandbox_evaluations.c.id == r["evaluation_id"])).first()
    assert ev.status == "ERROR" and "could not be evaluated" in ev.output_excerpt
    live = SimpleNamespace(id=cid, name="Downloaded thing", slug="x", data_mode="live")
    with pytest.raises(PermissionError, match="downloaded software"):
        R.run_sandbox(transaction, inv, live, None)
