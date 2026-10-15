"""V5.0 acceptance scenario (spec §12), end to end, over the HTTP API with the real worker, scheduler and conveyors.

A development agent requests a paid tool → the request travels to AI Central Bank → the Chief Financial Agent
opens a fee review → the Research Division searches for legitimate alternatives (labeled fixture catalog) → the
findings return to the bank → the General Manager evaluates the recommendation → a decision package travels to the
Owner's Tower → the owner can approve, reject, defer or ask for more research → nothing is bought until the owner
explicitly approves with step-up → every transition is an event (and a package on the belts).

All financial data is SIMULATED and labeled. Set AICIV_RECORD_ACCEPTANCE=1 to write docs/acceptance/v5-acceptance-log.md.
"""
import json
import os
import re
import time
from pathlib import Path

import jsonschema
import pytest
from fastapi.testclient import TestClient

from services.core import config
from services.finance import stepup
from tests.conftest import ROOT, wait_for
from tests.integration.test_missions import SCHEMA


@pytest.fixture
def v5env(monkeypatch):
    monkeypatch.setenv("AICIV_BELT_SPEED", "400")
    monkeypatch.setenv("AICIV_TICK_SCALE", "0.02")
    from services.core.auth import mutation_limiter
    monkeypatch.setattr(mutation_limiter, "burst", 100)  # the scenario makes more owner decisions per minute than a person would
    monkeypatch.setattr(stepup, "STEP", 1)  # 1-second TOTP steps so single-use codes don't make the test wait 30 s
    config.get_settings.cache_clear()


def _client():
    from services.api.main import app
    app.state.gateway = None
    return TestClient(app)


def all_events(c) -> list[dict]:
    out, after = [], 0
    while True:
        page = c.get(f"/api/events?after={after}&limit=500").json()["events"]
        if not page:
            return out
        out += page
        after = page[-1]["sequence"]


def request_tool(c, **kw) -> str:
    body = {"vendor": "Figma", "item": "Professional (per editor)", "amount": 15, "interval": "month",
            "justification": "Design reviews for the iOS app redesign", **kw}
    assert c.post("/api/finance/tool-requests", json=body).status_code == 201
    return wait_for(lambda: next((p["id"] for p in c.get("/api/finance/packets").json()["packets"]
                                  if p["origin"] == "purchase_request" and p["vendor"] == body["vendor"] and p["status"] not in ("REJECTED", "CLOSED")),
                                 None))


def at_tower(c, pid, timeout=90):
    def ready():
        d = c.get(f"/api/finance/packets/{pid}").json()
        arrived = any(x["type"] == "owner_approval_request" and x["status"] == "RECEIVED" for x in d["packages"])
        return d if d["packet"]["status"] == "OWNER_DECISION" and arrived else None
    return wait_for(ready, timeout=timeout)


def step_up(c, purpose: str, secret: str) -> str:
    time.sleep(1.05)  # each TOTP code is single-use: wait for the next (1-second, in tests) step
    r = c.post("/api/finance/stepup/verify", json={"code": stepup.totp(secret), "purpose": purpose})
    assert r.status_code == 200, r.text
    return r.json()["step_up_token"]


def test_acceptance_paid_tool_request_to_owner_decision(v5env):
    log = ["# V5.0 acceptance run: AI Central Bank fee review", "",
           f"Recorded {time.strftime('%Y-%m-%d %H:%M:%S %Z')} by tests/integration/test_v5_acceptance.py.",
           "Financial data: **SIMULATED** (labeled in every row, response and export). Alternatives come from the bundled **fixture** "
           "vendor catalog. No model key: agent text is templated and labeled `[simulation]`.", ""]
    with _client() as c:
        sim = c.post("/api/finance/simulated").json()
        log.append(f"0. Loaded a simulated ledger: {sim['inserted']} transactions; the Expense Auditor opened {sim['fee_reviews_opened']} fee review(s).")
        snap = c.get("/api/snapshot").json()
        by_key = {a["key"]: a for a in snap["agents"]}
        assert by_key["cfo"]["supervisor_agent_id"] == by_key["general_manager"]["id"]
        assert all(by_key[k]["supervisor_agent_id"] == by_key["cfo"]["id"] for k in
                   ("revenue_analyst", "expense_auditor", "bill_manager", "tax_agent", "savings_strategist", "forecaster"))
        assert by_key["expense_auditor"]["model_name"] == "claude-haiku-5-5" and by_key["general_manager"]["model_name"] == "claude-opus-5-5"
        assert any(d["id"] == "central-bank" for d in snap["districts"])

        # 1-7: request → bank → research → bank → GM → Owner's Tower
        pid = request_tool(c)
        d = at_tower(c, pid)
        p = d["packet"]
        types = [(x["type"], x["origin"], x["destination"]) for x in d["packages"]]
        assert types == [("purchase_request", "code-forge", "central-bank"), ("fee_research_request", "central-bank", "data-observatory"),
                         ("savings_recommendation", "data-observatory", "central-bank"), ("purchase_request", "central-bank", "nexus-spire"),
                         ("owner_approval_request", "nexus-spire", "owners-tower")]
        assert p["significant"] and p["gm_decision"]["outcome"] == "forward"
        assert p["findings"] and all(f["source"].startswith(("fixture://", "request")) for f in p["findings"])
        log += [f"1. Kade (Developer) requested **{p['vendor']} {p['item']}** at ${p['amount_minor'] / 100:.2f}/{p['interval']}: "
                f"classified *{p['classification']}*, significant={bool(p['significant'])}, risk={p['risk']}.",
                "2. Packages: " + " → ".join(f"`{t}` {o}→{dst}" for t, o, dst in types) + ".",
                f"3. Research: {len(p['findings'])} options from the fixture catalog. Recommendation: **{p['recommendation']['action']}**: "
                f"{p['recommendation']['summary']}",
                f"4. General Manager ({p['gm_decision']['method']}): {p['gm_decision']['outcome']}."]
        opts = {a["details"]["option"]: a for a in d["approvals"]}
        assert set(opts) == {"recommended", "requested"} and all(a["status"] == "REQUESTED" for a in opts.values())

        # nothing has been bought
        def figma_spend():
            return [t for t in c.get("/api/finance/transactions?limit=500").json()["transactions"] if "approved by owner" in t["description"]]
        assert figma_spend() == []

        # 8: refusals: no step-up, wrong hash, admin-only fields untouched
        rec = opts["recommended"]
        r = c.post(f"/api/finance/packets/{pid}/decide", json={"decision": "APPROVE", "approval_id": rec["id"], "payload_hash": rec["payload_hash"]})
        assert r.status_code == 401 and r.json()["detail"]["code"] == "step_up_required"
        secret = c.post("/api/finance/stepup/enroll").json()["secret"]
        tok = step_up(c, rec["id"], secret)
        r = c.post(f"/api/finance/packets/{pid}/decide", json={"decision": "APPROVE", "approval_id": rec["id"], "payload_hash": "f" * 64},
                   headers={"X-Step-Up": tok})
        assert r.status_code == 409 and "not what is on record" in r.json()["detail"]
        wrong_purpose = step_up(c, "something-else", secret)
        r = c.post(f"/api/finance/packets/{pid}/decide", json={"decision": "APPROVE", "approval_id": rec["id"], "payload_hash": rec["payload_hash"]},
                   headers={"X-Step-Up": wrong_purpose})
        assert r.status_code == 401
        log.append("5. Refused: approval without step-up (401), with a mismatched payload hash (409), and with a step-up token issued for "
                   "another action (401). Nothing was bought.")

        # 8b: the owner asks for more research, then the package returns to the tower
        r = c.post(f"/api/finance/packets/{pid}/decide", json={"decision": "MORE_RESEARCH", "note": "check self-hosted options too"})
        assert r.status_code == 200
        d = at_tower(c, pid)
        assert d["packet"]["research_rounds"] == 2
        log.append("6. Owner asked for more research → `fee_research_request` Owner's Tower→Data Observatory → second round "
                   f"(by {'Wren' if d['packet']['research_rounds'] % 2 == 0 else 'Pip'}) → back through the bank and the GM to the tower.")
        opts = {a["details"]["option"]: a for a in d["approvals"] if a["status"] == "REQUESTED"}

        # 8c: approve exactly the recommended option, with step-up
        rec = opts["recommended"]
        tok = step_up(c, rec["id"], secret)
        r = c.post(f"/api/finance/packets/{pid}/decide", json={"decision": "APPROVE", "approval_id": rec["id"], "payload_hash": rec["payload_hash"]},
                   headers={"X-Step-Up": tok})
        assert r.status_code == 200 and r.json()["step_up_method"] == "totp"
        final = wait_for(lambda: (x := c.get(f"/api/finance/packets/{pid}").json())["packet"]["status"] == "EXECUTED" and x, timeout=60)
        states = {a["details"]["option"]: a["status"] for a in final["approvals"] if a["status"] != "INVALIDATED" or a["details"]["option"] == "requested"}
        assert states["recommended"] == "EXECUTED" and final["approvals"][-1]["status"] in ("INVALIDATED", "EXECUTED")
        assert all(a["status"] != "EXECUTED" for a in final["approvals"] if a["id"] != rec["id"])
        executed = next(a for a in final["approvals"] if a["status"] == "EXECUTED")
        assert executed["execution_mode"] == "simulated" and executed["execution_ref"].startswith("SIM-")
        log.append(f"7. Owner approved **{rec['recipient']}** (step-up: TOTP). The Bill Manager's execution was re-checked at the tool "
                   f"boundary and recorded as **simulated** ({executed['execution_ref']}). The other option was invalidated.")

        # second request: reject, and a third: defer → reopen
        pid2 = request_tool(c, vendor="Sentry", item="Team", amount=26, justification="Crash reporting for the iOS beta")
        d2 = at_tower(c, pid2)
        assert c.post(f"/api/finance/packets/{pid2}/decide", json={"decision": "REJECT", "note": "not this quarter"}).status_code == 200
        assert c.get(f"/api/finance/packets/{pid2}").json()["packet"]["status"] == "REJECTED"
        pid3 = request_tool(c, vendor="Vercel", item="Pro (per member)", amount=20, justification="Preview deployments for client demos")
        at_tower(c, pid3)
        assert c.post(f"/api/finance/packets/{pid3}/decide", json={"decision": "DEFER", "defer_days": 14}).status_code == 200
        assert c.get(f"/api/finance/packets/{pid3}").json()["packet"]["status"] == "DEFERRED"
        assert c.post(f"/api/finance/packets/{pid3}/reopen").status_code == 200
        d3 = at_tower(c, pid3)
        assert all(a["status"] == "REQUESTED" for a in d3["approvals"] if a["status"] not in ("DEFERRED",))
        log.append(f"8. A Sentry request was **rejected** and a Vercel request **deferred** then reopened (fresh approval requests, new expiry). "
                   f"Neither bought anything: {len(d2['approvals'])} + {len(d3['approvals'])} approvals, none executed.")
        assert all(a["status"] != "EXECUTED" for a in d2["approvals"] + d3["approvals"])

        # every transition is an event; finance events carry no money; envelopes are valid
        events = all_events(c)
        for e in events:
            jsonschema.validate(e, SCHEMA)
        fin = [e for e in events if e["event_type"].startswith("finance.") and e["payload"].get("packet_id") == pid]
        statuses = [e["payload"]["to"] for e in fin if e["event_type"] == "finance.packet_status_changed"]
        assert statuses == ["AT_BANK", "RESEARCH_REQUESTED", "RESEARCHING", "FINDINGS_RETURNED", "GM_REVIEW", "OWNER_DECISION",
                            "RESEARCH_REQUESTED", "RESEARCHING", "FINDINGS_RETURNED", "GM_REVIEW", "OWNER_DECISION", "APPROVED", "EXECUTED"]
        money = re.compile(r'"(amount|amount_minor|balance|account_ref|recipient|available_balance_minor|current_balance_minor)"')
        assert not [e for e in events if e["event_type"].startswith(("finance.", "package.")) and money.search(json.dumps(e["payload"]))]
        tool_events = [e for e in events if e["event_type"] == "tool.started" and e["payload"]["tool"] in
                       ("request_purchase", "execute_financial_action", "propose_financial_action")]
        assert tool_events and all(e["payload"]["arguments"].get("withheld") == "financial arguments" for e in tool_events)
        moved = [e for e in events if e["event_type"] == "agent.arrived" and e["payload"].get("district") == "central-bank"]
        assert moved, "finance agents should be seen moving to their bank floors"
        log.append(f"9. {len(events)} events, all valid against the v1 envelope schema. The packet passed through "
                   + " → ".join(statuses) + ". Finance and package events carry no amounts, balances, recipients or account references.")

        audit = c.get("/api/finance/audit").json()
        assert audit["chain"]["ok"]
        log.append(f"10. Financial audit log: {audit['chain']['entries']} hash-chained entries, chain verified.")
        log += ["", "## Packet timeline (from the bank's own audit trail)", "", "| # | action | actor | detail |", "|---|---|---|---|"]
        for t in c.get(f"/api/finance/packets/{pid}").json()["audit"]:
            det = {k: v for k, v in t["detail"].items() if k in ("from", "to", "reason", "outcome", "action", "category", "count", "execution_mode")}
            log.append(f"| {t['seq']} | {t['action']} | {t['actor_type']} | {json.dumps(det)[:110].replace('|', '/')} |")
        out = Path(os.environ.get("AICIV_ACCEPTANCE_DIR", "/tmp")) / "v5-acceptance-log.md"
        if os.environ.get("AICIV_RECORD_ACCEPTANCE") == "1":
            out = ROOT / "docs" / "acceptance" / "v5-acceptance-log.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(log) + "\n")


def test_fee_reviews_from_simulated_ledger_reach_the_owner_without_spending(v5env):
    with _client() as c:
        c.post("/api/finance/simulated")
        def done():
            ps = [p for p in c.get("/api/finance/packets").json()["packets"] if p["origin"] == "fee_detected"]
            return ps if ps and all(p["status"] == "OWNER_DECISION" for p in ps) else None
        ps = wait_for(done, timeout=120)
        items = {p["item"]: p for p in ps}
        assert {"Monthly maintenance fee", "Stripe processing fee", "App Store commission", "Outgoing wire fee"} <= set(items)
        maint = items["Monthly maintenance fee"]
        assert maint["classification"] == "optional"
        for p in ps:
            d = c.get(f"/api/finance/packets/{p['id']}").json()
            assert d["approvals"] == []  # fee reviews recommend; switching or cancelling is the owner's own action
        r = c.post(f"/api/finance/packets/{maint['id']}/decide", json={"decision": "ACKNOWLEDGE"})
        assert r.status_code == 200 and c.get(f"/api/finance/packets/{maint['id']}").json()["packet"]["status"] == "CLOSED"
        dash = c.get("/api/finance/dashboard").json()
        assert dash["simulated"] and dash["savings"] and dash["reconciliation"]["matched"] > 0
        assert dash["last_30_days"]["revenue_gross_minor"] > 0 and dash["forecast"]["label"].startswith("ESTIMATE")


def test_bill_payment_needs_owner_and_step_up(v5env):
    with _client() as c:
        c.post("/api/finance/simulated")
        prop = wait_for(lambda: next((a for a in c.get("/api/finance/approvals?status=REQUESTED").json()["approvals"]
                                      if a["action_type"] == "payment"), None), timeout=30)
        assert prop["recipient"] == "Comcast internet"  # due in 3 days, not on autopay
        r = c.post(f"/api/finance/approvals/{prop['id']}/decide", json={"decision": "APPROVE", "payload_hash": prop["payload_hash"]})
        assert r.status_code == 401
        secret = c.post("/api/finance/stepup/enroll").json()["secret"]
        tok = step_up(c, prop["id"], secret)
        r = c.post(f"/api/finance/approvals/{prop['id']}/decide", json={"decision": "APPROVE", "payload_hash": prop["payload_hash"]},
                   headers={"X-Step-Up": tok})
        assert r.status_code == 200
        paid = wait_for(lambda: next((b for b in c.get("/api/finance/dashboard").json()["bills"] if b["payee"] == "Comcast internet"), "gone") == "gone",
                        timeout=60)
        assert paid
        a = next(a for a in c.get("/api/finance/approvals").json()["approvals"] if a["id"] == prop["id"])
        assert a["status"] == "EXECUTED" and a["execution_mode"] == "simulated"


def test_tax_workflow_estimates_exports_and_never_files(v5env):
    with _client() as c:
        c.post("/api/finance/simulated")
        assert c.post("/api/finance/tax/estimate", json={}).status_code == 201
        t = c.get("/api/finance/tax").json()
        assert t["estimate"]["data_mode"] == "simulated" and t["filing"]["available"] is False
        assert any(d["label"].startswith("Q4") for d in t["deadlines"]) and t["checklist"]
        assert c.post("/api/finance/tax/file").status_code == 409
        assert c.get(f"/api/finance/tax/export?tax_year={t['tax_year']}").status_code == 401  # step-up first
        secret = c.post("/api/finance/stepup/enroll").json()["secret"]
        tok = step_up(c, f"export:{t['tax_year']}", secret)
        z = c.get(f"/api/finance/tax/export?tax_year={t['tax_year']}", headers={"X-Step-Up": tok})
        assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
        doc = c.put(f"/api/finance/tax/documents?tax_year={t['tax_year']}&doc_type=1099-K", content=b"%PDF-1.4 test")
        assert doc.status_code == 200
        assert any(d["doc_type"] == "1099-K" and d["status"] == "RECEIVED" for d in c.get("/api/finance/tax").json()["documents"])
        pk = wait_for(lambda: any(e["event_type"] == "package.dispatched" and e["payload"]["package_type"] == "tax_review_package"
                                  for e in all_events(c)))
        assert pk


def test_csv_upload_connection_flow(v5env):
    with _client() as c:
        cid = c.post("/api/finance/connections", json={"provider": "csv_upload"}).json()["id"]
        assert c.put(f"/api/finance/connections/{cid}/upload", content=b"Date,Description,Amount\n2026-09-01,X,-1\n").status_code == 409
        assert c.post(f"/api/finance/connections/{cid}/authorize", json={"confirm_read_only": True}).status_code == 200
        csv = b"Date,Description,Amount\n2026-09-01,Stripe payout,500.00\n2026-09-03,Monthly maintenance fee,-15.00\nbad,row,1\n"
        r = c.put(f"/api/finance/connections/{cid}/upload", content=csv).json()
        assert r["inserted"] == 2 and r["rejected"] == 1 and r["status"] == "PARTIAL"
        again = c.put(f"/api/finance/connections/{cid}/upload", content=csv).json()
        assert again["inserted"] == 0 and again["duplicates"] == 2
        listed = c.get("/api/finance/connections").json()
        assert all("secret_ciphertext" not in x for x in listed["connections"])
        stripe = c.post("/api/finance/connections", json={"provider": "stripe"}).json()["id"]
        r = c.post(f"/api/finance/connections/{stripe}/authorize", json={"confirm_read_only": True, "credential": "rk_live_x"})
        assert r.status_code == 401  # real credentials need step-up
        assert c.post("/api/finance/connections", json={"provider": "quickbooks"}).status_code == 409
