"""AI Central Bank: security, approval engine, connectors, ledger and tax. Test names match docs/finance/THREAT_MODEL.md."""
import base64
import gzip
import json
import time

import httpx
import jwt
import pytest
from sqlalchemy import exc as sa_exc
from sqlalchemy import insert, select, update

from services.core import db
from services.core.config import load_seed
from services.core.events import transaction

ORG = load_seed()["organization_id"]
OWNER = "00000000-0000-4000-8000-000000000000"


@pytest.fixture
def bank():
    db.init_db()
    return db


def _agent(conn, key):
    return conn.execute(select(db.agents).where(db.agents.c.key == key)).first()


def _mission_task(conn, *, agent_key: str, tools: list[str], params: dict) -> tuple[str, str, str]:
    from services.management.pipeline import create_mission
    a = _agent(conn, agent_key)
    mid = create_mission(conn, org_id=ORG, kind="finance_execute", title="t", prompt="test mission", params=params, opportunity_id=None,
                         created_by=a.id)
    conn.execute(update(db.missions).where(db.missions.c.id == mid).values(status="RUNNING"))
    tid = db.new_id()
    conn.execute(insert(db.tasks).values(id=tid, organization_id=ORG, mission_id=mid, agent_id=a.id, key="execute_action", title="t",
                                         district="central-bank", status="RUNNING", permitted_tools=tools, ordinal=0))
    return mid, tid, a.id


def _ctx(mid, tid, aid):
    from services.tools.registry import ToolContext
    return ToolContext(mission_id=mid, task_id=tid, agent_id=aid, org_id=ORG, execution_mode="simulation")


def _packet_with_option(conn, amount=1500, recipient="Figma", data_mode="simulated"):
    from services.finance import approvals as A
    from services.finance import packets as P
    pid = P.create(conn, org_id=ORG, origin="purchase_request", vendor=recipient, item="Professional", amount_minor=amount, currency="USD",
                   interval="month", justification="design work for the app", requested_by_agent_id=None, request_mission_id=None,
                   subject_type="tool_request", subject_id=None, data_mode=data_mode)
    opt = {"vendor": recipient, "item": "Professional", "amount_minor": amount, "currency": "USD", "interval": "month", "recipient": recipient,
           "account_ref": "acct:test", "account_label": "card", "three_year_minor": amount * 36}
    conn.execute(update(db.cost_review_packets).where(db.cost_review_packets.c.id == pid).values(
        status="OWNER_DECISION", recommendation={"action": "buy_requested", "options": {"recommended": opt}}))
    aid = A.request(conn, org_id=ORG, packet_id=pid, action_type="purchase", amount_minor=amount, currency="USD", recipient=recipient,
                    account_ref="acct:test", details={"option": "recommended", "item": "Professional", "interval": "month"},
                    requested_by_agent_id=None, data_mode=data_mode)
    return pid, aid


def _approve(conn, aid):
    from services.finance import approvals as A
    from services.finance import stepup
    a = A.get(conn, aid)
    tok = stepup.issue_token(OWNER, aid, "totp")
    return A.decide(conn, approval_id=aid, decision="APPROVE", presented_hash=a.payload_hash, owner_id=OWNER, owner_role="owner", step_up_token=tok)


def _terms(a, **over):
    return {"approval_id": a.id, "action_type": a.action_type, "amount_minor": a.amount_minor, "currency": a.currency,
            "recipient": a.recipient, "account_ref": a.account_ref, **over}


# ------------------------------------------------------------------ F1-F4 approval engine at the tool boundary
def test_execution_refused_without_owner_approval(bank):
    from services.finance import approvals as A
    from services.tools.registry import ToolDenied, execute_tool
    with transaction() as conn:
        pid, aid = _packet_with_option(conn)
        mid, tid, agent = _mission_task(conn, agent_key="bill_manager", tools=["execute_financial_action"], params={"approval_id": aid})
        a = A.get(conn, aid)
    with pytest.raises(ToolDenied, match="not approved by the owner"):
        execute_tool(_ctx(mid, tid, agent), "execute_financial_action", _terms(a))
    with db.get_engine().connect() as conn:
        row = conn.execute(select(db.tool_executions).where(db.tool_executions.c.task_id == tid)).first()
    assert row.status == "DENIED" and "amount_minor" not in json.dumps(row.arguments)  # F9: money withheld even in the audit row


def test_modified_amount_or_recipient_is_refused(bank):
    from services.finance import approvals as A
    from services.tools.registry import ToolDenied, execute_tool
    with transaction() as conn:
        pid, aid = _packet_with_option(conn)
        _approve(conn, aid)
        mid, tid, agent = _mission_task(conn, agent_key="bill_manager", tools=["execute_financial_action"], params={"approval_id": aid})
        a = A.get(conn, aid)
    ctx = _ctx(mid, tid, agent)
    for change in ({"amount_minor": a.amount_minor + 1}, {"recipient": "Someone Else"}, {"account_ref": "acct:other"}, {"action_type": "transfer"}):
        with pytest.raises(ToolDenied, match="differs from what the owner approved"):
            execute_tool(ctx, "execute_financial_action", _terms(a, **change))
    # the packet's terms changing after approval also invalidates it
    with transaction() as conn:
        pk = conn.execute(select(db.cost_review_packets).where(db.cost_review_packets.c.id == pid)).first()
        rec = dict(pk.recommendation)
        rec["options"]["recommended"]["amount_minor"] = 99_999
        conn.execute(update(db.cost_review_packets).where(db.cost_review_packets.c.id == pid).values(recommendation=rec))
    with pytest.raises(ToolDenied, match="changed after the owner approved"):
        execute_tool(ctx, "execute_financial_action", _terms(a))


def test_stale_or_modified_request_refused_at_decision(bank):
    from services.finance import approvals as A
    with transaction() as conn:
        pid, aid = _packet_with_option(conn)
        with pytest.raises(A.ApprovalRefused, match="not what is on record"):
            A.decide(conn, approval_id=aid, decision="REJECT", presented_hash="0" * 64, owner_id=OWNER, owner_role="owner")
        pk = conn.execute(select(db.cost_review_packets).where(db.cost_review_packets.c.id == pid)).first()
        rec = dict(pk.recommendation)
        rec["options"]["recommended"]["recipient"] = "Attacker LLC"
        conn.execute(update(db.cost_review_packets).where(db.cost_review_packets.c.id == pid).values(recommendation=rec))
        a = A.get(conn, aid)
        with pytest.raises(A.ApprovalRefused, match="changed after it was sent"):
            A.decide(conn, approval_id=aid, decision="REJECT", presented_hash=a.payload_hash, owner_id=OWNER, owner_role="owner")
    with db.get_engine().connect() as conn:
        assert A.get(conn, aid).status == "INVALIDATED"


def test_expired_approval_refused(bank):
    from services.finance import approvals as A
    from services.tools.registry import ToolDenied, execute_tool
    with transaction() as conn:
        pid, aid = _packet_with_option(conn)
        _approve(conn, aid)
        mid, tid, agent = _mission_task(conn, agent_key="bill_manager", tools=["execute_financial_action"], params={"approval_id": aid})
        conn.execute(update(db.financial_approvals).where(db.financial_approvals.c.id == aid).values(expires_at="2000-01-01T00:00:00+00:00"))
        a = A.get(conn, aid)
    with pytest.raises(ToolDenied, match="expired"):
        execute_tool(_ctx(mid, tid, agent), "execute_financial_action", _terms(a))
    with transaction() as conn:
        _, aid2 = _packet_with_option(conn)
        conn.execute(update(db.financial_approvals).where(db.financial_approvals.c.id == aid2).values(expires_at="2000-01-01T00:00:00+00:00"))
        a2 = A.get(conn, aid2)
        with pytest.raises(A.ApprovalRefused, match="expired"):
            A.decide(conn, approval_id=aid2, decision="APPROVE", presented_hash=a2.payload_hash, owner_id=OWNER, owner_role="owner")


def test_replay_refused(bank):
    from services.finance import approvals as A
    from services.tools.registry import ToolDenied, execute_tool
    with transaction() as conn:
        pid, aid = _packet_with_option(conn)
        _approve(conn, aid)
        mid, tid, agent = _mission_task(conn, agent_key="bill_manager", tools=["execute_financial_action"], params={"approval_id": aid})
        a = A.get(conn, aid)
    ctx = _ctx(mid, tid, agent)
    assert execute_tool(ctx, "execute_financial_action", _terms(a))["status"] == "executed_simulated"
    with pytest.raises(ToolDenied, match="already used"):
        execute_tool(ctx, "execute_financial_action", _terms(a))
    with db.get_engine().connect() as conn:
        assert A.get(conn, aid).status == "EXECUTED"


def test_emergency_stop_blocks_financial_execution(bank):
    from services.finance import approvals as A
    from services.tools.registry import ToolDenied, execute_tool
    with transaction() as conn:
        pid, aid = _packet_with_option(conn)
        _approve(conn, aid)
        mid, tid, agent = _mission_task(conn, agent_key="bill_manager", tools=["execute_financial_action"], params={"approval_id": aid})
        a = A.get(conn, aid)
        conn.execute(update(db.organizations).where(db.organizations.c.id == ORG).values(emergency_stopped=1))
    with pytest.raises(ToolDenied, match="emergency stop"):
        execute_tool(_ctx(mid, tid, agent), "execute_financial_action", _terms(a))


def test_tax_filing_always_refused_without_integration(bank):
    from services.finance import approvals as A
    with transaction() as conn:
        aid = A.request(conn, org_id=ORG, packet_id=None, action_type="tax_filing", amount_minor=0, currency="USD", recipient="IRS",
                        account_ref="none", details={}, requested_by_agent_id=None, data_mode="simulated")
        _approve(conn, aid)
        a = A.get(conn, aid)
        with pytest.raises(A.ApprovalRefused, match="no authorized tax-filing integration"):
            A.authorize_execution(conn, org_id=ORG, approval_id=aid, action_type="tax_filing", amount_minor=0, currency="USD", recipient="IRS",
                                  account_ref="none")
    assert a.status == "APPROVED"


# ------------------------------------------------------------------ F5 step-up
def test_approve_requires_step_up(bank):
    from services.finance import approvals as A
    with transaction() as conn:
        pid, aid = _packet_with_option(conn)
        a = A.get(conn, aid)
        with pytest.raises(A.ApprovalRefused, match="step-up"):
            A.decide(conn, approval_id=aid, decision="APPROVE", presented_hash=a.payload_hash, owner_id=OWNER, owner_role="owner")
        with pytest.raises(A.ApprovalRefused, match="only the owner"):
            A.decide(conn, approval_id=aid, decision="APPROVE", presented_hash=a.payload_hash, owner_id=OWNER, owner_role="admin")
        # rejecting is the safe direction: no step-up needed
        assert A.decide(conn, approval_id=aid, decision="REJECT", presented_hash=a.payload_hash, owner_id=OWNER, owner_role="owner")["status"] == "REJECTED"


def test_step_up_token_bound_to_user_and_expires(bank, monkeypatch):
    from services.finance import stepup
    tok = stepup.issue_token(OWNER, "approval-1", "totp")
    assert stepup.check_token(tok, user_id=OWNER, purpose="approval-1") == "totp"
    with pytest.raises(stepup.StepUpRequired, match="another user"):
        stepup.check_token(tok, user_id="someone-else", purpose="approval-1")
    with pytest.raises(stepup.StepUpRequired, match="different action"):
        stepup.check_token(tok, user_id=OWNER, purpose="approval-2")
    forged = base64.urlsafe_b64encode(base64.urlsafe_b64decode(tok).replace(b"approval-1", b"approval-9")).decode()
    with pytest.raises(stepup.StepUpRequired):
        stepup.check_token(forged, user_id=OWNER, purpose="approval-9")
    real = time.time
    monkeypatch.setattr(stepup.time, "time", lambda: real() + stepup.TOKEN_TTL + 5)
    with pytest.raises(stepup.StepUpRequired, match="expired"):
        stepup.check_token(tok, user_id=OWNER, purpose="approval-1")


def test_totp_codes_are_single_use(bank):
    from services.finance import stepup
    with transaction() as conn:
        secret = stepup.enroll(conn, user_id=OWNER, org_id=ORG)["secret"]
        code = stepup.totp(secret)
        stepup.check_code(conn, OWNER, code)
        with pytest.raises(stepup.StepUpRequired, match="already used"):
            stepup.check_code(conn, OWNER, code)
        with pytest.raises(stepup.StepUpRequired):
            stepup.check_code(conn, OWNER, "000000" if code != "000000" else "111111")
        row = conn.execute(select(db.stepup_secrets).where(db.stepup_secrets.c.user_id == OWNER)).first()
    assert secret not in row.secret_ciphertext


def test_supabase_aal2_counts_only_when_fresh():
    from services.finance.stepup import aal2_fresh
    now = time.time()
    assert aal2_fresh({"aal": "aal2", "amr": [{"method": "totp", "timestamp": now - 60}]})
    assert not aal2_fresh({"aal": "aal2", "amr": [{"method": "totp", "timestamp": now - 3600}]})
    assert not aal2_fresh({"aal": "aal1", "amr": [{"method": "password", "timestamp": now}]})


# ------------------------------------------------------------------ F6, F7 who can see and do what
def test_viewer_and_operator_cannot_read_finance(monkeypatch):
    from fastapi.testclient import TestClient

    from services.core import config
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "x" * 40)
    config.get_settings.cache_clear()
    from services.api.main import app
    app.state.gateway = None

    def tok(role):
        return jwt.encode({"sub": "11111111-1111-4111-8111-111111111111", "aud": "authenticated", "app_metadata": {"role": role},
                           "exp": int(time.time()) + 600}, "x" * 40, algorithm="HS256")
    with TestClient(app) as c:
        for role in ("viewer", "operator"):
            h = {"Authorization": f"Bearer {tok(role)}"}
            for path in ("/api/finance/dashboard", "/api/finance/packets", "/api/finance/transactions", "/api/finance/audit", "/api/finance/tax"):
                assert c.get(path, headers=h).status_code == 403, (role, path)
        h = {"Authorization": f"Bearer {tok('admin')}"}
        assert c.get("/api/finance/dashboard", headers=h).status_code == 200
        assert c.post("/api/finance/simulated", headers=h).status_code == 403          # admins read; only the owner acts
        assert c.post("/api/finance/stepup/enroll", headers=h).status_code == 403


def test_non_finance_agent_cannot_read_ledger(bank):
    from services.tools.registry import ToolDenied, execute_tool
    with transaction() as conn:
        # even if someone granted the capability and the task permitted it, the department check refuses
        dev = _agent(conn, "developer")
        conn.execute(insert(db.agent_capabilities).values(agent_id=dev.id, tool_name="read_ledger_summary"))
        mid, tid, agent = _mission_task(conn, agent_key="developer", tools=["read_ledger_summary"], params={})
    with pytest.raises(ToolDenied, match="restricted to the finance department"):
        execute_tool(_ctx(mid, tid, agent), "read_ledger_summary", {})


def test_tools_are_scoped_to_the_missions_packet(bank):
    from services.tools.registry import ToolDenied, execute_tool
    with transaction() as conn:
        pid, _ = _packet_with_option(conn)
        other, _ = _packet_with_option(conn)
        mid, tid, agent = _mission_task(conn, agent_key="savings_strategist", tools=["record_cost_findings"], params={"packet_id": pid})
    with pytest.raises(ToolDenied, match="not working on that cost review"):
        execute_tool(_ctx(mid, tid, agent), "record_cost_findings", {"packet_id": other})


# ------------------------------------------------------------------ F8, F9 minimal exposure
def test_model_prompts_never_contain_account_data():
    from services.finance.redaction import for_model, scrub
    s = scrub("ACH to acct 123456789012 card 4111 1111 1111 1111 routing 021000021 ssn 123-45-6789 me@x.com")
    for secret in ("123456789012", "4111 1111 1111 1111", "021000021", "123-45-6789", "me@x.com"):
        assert secret not in s
    v = for_model(vendor="Figma acct 9876543210", item="Pro", category="software", amount_minor=1537, interval="month")
    assert "9876543210" not in json.dumps(v) and v["approximate_cost"] == "about $15" and "1537" not in json.dumps(v)


def test_finance_events_carry_no_amounts_or_accounts():
    from services.finance.redaction import event_safe
    out = event_safe({"packet_id": "p", "amount_minor": 1, "recipient": "x", "account_ref": "acct:1", "balance": 5, "status": "S"})
    assert out == {"packet_id": "p", "status": "S"}


# ------------------------------------------------------------------ F10, F11 connections and secrets
def test_connection_requires_explicit_owner_authorization(bank, monkeypatch):
    from services.finance import sync
    monkeypatch.setenv("STRIPE_API_KEY", "rk_live_from_env_must_be_ignored")
    with transaction() as conn:
        cid = db.new_id()
        conn.execute(insert(db.financial_connections).values(id=cid, organization_id=ORG, kind="payment_processor", provider="stripe",
                                                             display_name="Stripe", scopes=["balance:read"], data_mode="live"))
    with pytest.raises(PermissionError, match="not authorized"):
        sync.run(cid)


def test_write_scopes_refused():
    from services.finance import connectors as C
    for p in C.PROVIDERS.values():
        C.check_read_only(p)  # every shipped provider is read-only
    with pytest.raises(C.AdapterError, match="writes"):
        C.check_read_only(C.PROVIDERS["stripe"], ["payouts:write"])
    with pytest.raises(C.AdapterError, match="restricted key"):
        C.stripe_batch("sk_live_abc", None)


def test_credentials_encrypted_at_rest(bank):
    from services.finance import crypto
    ct = crypto.encrypt("rk_live_supersecret")
    assert "supersecret" not in ct and crypto.decrypt(ct) == "rk_live_supersecret"
    assert crypto.ref_hmac("acct-1") == crypto.ref_hmac("acct-1") != crypto.ref_hmac("acct-2")


def test_finance_key_required_outside_dev(monkeypatch):
    from services.core import config
    from services.finance import crypto
    monkeypatch.setenv("AICIV_API_TOKEN", "t" * 32)
    config.get_settings.cache_clear()
    with pytest.raises(crypto.FinanceKeyMissing):
        crypto.encrypt("x")


# ------------------------------------------------------------------ F12 audit
def test_audit_chain_detects_tampering(bank):
    from services.finance import audit
    with transaction() as conn:
        for i in range(3):
            audit.record(conn, org_id=ORG, actor_type="system", actor_id=None, action=f"t{i}", subject_type="x", subject_id=None, detail={"i": i})
        assert audit.verify(conn, ORG)["ok"]
    # bypass the trigger the way a direct database edit would, then verify
    with db.get_engine().begin() as conn:
        if conn.dialect.name == "sqlite":
            conn.exec_driver_sql("DROP TRIGGER financial_audit_events_no_update")
        else:
            conn.exec_driver_sql("set local session_replication_role = replica")
        conn.execute(update(db.financial_audit_events).where(db.financial_audit_events.c.seq == 2).values(detail={"i": 99}))
    with db.get_engine().connect() as conn:
        v = audit.verify(conn, ORG)
    assert v == {"ok": False, "entries": 3, "broken_at_seq": 2}


def test_audit_is_append_only(bank):
    from services.finance import audit
    with transaction() as conn:
        audit.record(conn, org_id=ORG, actor_type="system", actor_id=None, action="t", subject_type="x", subject_id=None)
    for stmt in (db.financial_audit_events.update().values(action="changed"), db.financial_audit_events.delete()):
        with pytest.raises(sa_exc.DatabaseError):
            with transaction() as conn:
                conn.execute(stmt)


# ------------------------------------------------------------------ F13, F17 data integrity
def _simulated(conn_id=None):
    from services.finance import crypto
    with transaction() as conn:
        cid = conn_id or db.new_id()
        conn.execute(insert(db.financial_connections).values(id=cid, organization_id=ORG, kind="bank_feed", provider="simulated", display_name="sim",
                                                             scopes=["read:simulated"], status="ACTIVE", data_mode="simulated",
                                                             secret_ciphertext=crypto.encrypt(json.dumps({"anchor": "2026-10-01"}))))
    return cid


def test_resync_is_idempotent(bank):
    from services.finance import sync
    cid = _simulated()
    first = sync.run(cid)
    second = sync.run(cid)
    assert first["inserted"] > 100 and second["inserted"] == 0 and second["duplicates"] == first["inserted"]
    assert second["fee_reviews_opened"] == 0


def test_dashboard_reports_gaps_not_zeros(bank):
    from services.finance import dashboard
    with db.get_engine().connect() as conn:
        d = dashboard.build(conn, ORG)
    assert d["has_data"] is False and d["last_30_days"] is None and d["available_cash_minor"] is None and d["forecast"] is None
    assert set(d["coverage"]["gaps"]) >= {"bank_feed", "payment_processor", "accounting"}


def test_simulated_data_is_labeled_everywhere(bank):
    from services.finance import dashboard, sync, tax
    cid = _simulated()
    sync.run(cid)
    with db.get_engine().connect() as conn:
        modes = {r[0] for r in conn.execute(select(db.financial_transactions.c.data_mode))}
        descs = [r[0] for r in conn.execute(select(db.financial_transactions.c.description))]
        d = dashboard.build(conn, ORG)
        acct_names = [a["name"] for a in d["accounts"]]
    assert modes == {"simulated"} and all(x.startswith("SIM ") for x in descs) and all(n.startswith("SIM ") for n in acct_names)
    assert d["simulated"] is True and d["data_modes"] == ["simulated"]
    with transaction() as conn:
        eid = tax.estimate(conn, ORG, ship=False)
        est = conn.execute(select(db.tax_estimates).where(db.tax_estimates.c.id == eid)).first()
        z = tax.export_package(conn, ORG, est.tax_year, OWNER)
    assert est.data_mode == "simulated" and any("SIMULATED" in u for u in est.uncertainty)
    import io
    import zipfile
    assert "SIMULATED DATA" in zipfile.ZipFile(io.BytesIO(z)).read("README.txt").decode()


def test_unknown_deposits_are_not_revenue(bank):
    from services.finance import categories
    assert categories.categorize("ZELLE FROM J SMITH", None, 50_000) == ("uncategorized", "other", False)
    assert categories.categorize("SIM Monthly maintenance fee", "SIM Bank", -1500) == ("bank_fees", "fee", True)


# ------------------------------------------------------------------ F14 bills, F16 retention
def test_due_bills_always_raise_reminders(bank):
    from services.finance import bills
    from datetime import datetime, timedelta, timezone
    with transaction() as conn:
        for days, autopay in ((2, 0), (5, 1), (-1, 0), (30, 0)):
            conn.execute(insert(db.bills).values(id=db.new_id(), organization_id=ORG, payee=f"Payee {days}", amount_minor=1000, currency="USD",
                                                 due_at=(datetime.now(timezone.utc) + timedelta(days=days)).isoformat(), autopay=autopay,
                                                 status="UPCOMING", data_mode="simulated"))
    queued = []
    bills.tick(queued.append)
    bills.tick(queued.append)  # a second tick never duplicates reminders
    with db.get_engine().connect() as conn:
        rows = {b.payee: b for b in conn.execute(select(db.bills))}
        reminders = conn.execute(select(db.logistics_packages).where(db.logistics_packages.c.package_type == "bill_reminder")).fetchall()
        proposals = conn.execute(select(db.financial_approvals).where(db.financial_approvals.c.action_type == "payment")).fetchall()
    assert len(reminders) == 3 and all(rows[f"Payee {d}"].reminded_at for d in (2, 5, -1)) and rows["Payee 30"].reminded_at is None
    assert rows["Payee -1"].status == "OVERDUE"
    assert {p.recipient for p in proposals} == {"Payee 2", "Payee -1"}  # autopay bills get a reminder but no payment proposal
    assert all(p.status == "REQUESTED" for p in proposals)            # never paid without the owner


def test_delete_connection_data_keeps_audit(bank):
    from services.finance import audit, retention, sync
    cid = _simulated()
    sync.run(cid)
    with transaction() as conn:
        before = audit.count(conn, ORG)
        counts = retention.delete_connection_data(conn, org=ORG, connection_id=cid, actor_id=OWNER)
    with db.get_engine().connect() as conn:
        assert conn.execute(select(db.financial_transactions)).first() is None
        c = conn.execute(select(db.financial_connections).where(db.financial_connections.c.id == cid)).first()
        assert c.status == "REVOKED" and c.secret_ciphertext is None
        assert audit.count(conn, ORG) == before + 1 and audit.verify(conn, ORG)["ok"]
    assert counts["financial_transactions"] > 100


# ------------------------------------------------------------------ classification and research
def test_classification_rules():
    from services.finance.packets import classify
    assert classify(vendor="IRS", item="Q3 estimated tax", interval="one_time", amount_minor=80_000)["classification"] == "legally_required"
    c = classify(vendor="Google Workspace", item="Business", interval="month", amount_minor=1400, contract_terms="annual commitment")
    assert c["classification"] == "contractual" and c["significant"] and c["risk"] == "high"
    assert classify(vendor="SIM Bank", item="Monthly maintenance fee", interval="month", amount_minor=1500)["classification"] == "optional"
    small = classify(vendor="Notion", item="Plus", interval="month", amount_minor=500)
    assert small["classification"] == "recurring" and not small["significant"]


def test_legal_obligations_are_never_shopped_around():
    from types import SimpleNamespace

    from services.finance import research
    r = research.research(vendor="Franchise Tax Board", item="annual fee", amount_minor=80_000, interval="year", classification="legally_required")
    assert r["findings"] == [] and "Pay it on time" in r["note"]
    rec = research.recommend(SimpleNamespace(classification="legally_required", origin="fee_detected"), [])
    assert rec["action"] == "pay_on_time"


def test_unknown_vendor_research_admits_no_sources():
    from services.finance import research
    r = research.research(vendor="Obscure Tool Inc", item="Seat", amount_minor=900, interval="month", classification="recurring")
    assert [f["source"] for f in r["findings"]] == ["request"] and "Nothing was guessed" in r["note"]


def test_research_cites_fixture_sources_and_ranks_by_three_year_cost():
    from types import SimpleNamespace

    from services.finance import research
    r = research.research(vendor="Figma", item="Professional", amount_minor=1500, interval="month", classification="recurring")
    assert all(f["source"].startswith(("fixture://", "request")) for f in r["findings"])
    req = next(f for f in r["findings"] if f["is_requested"])
    assert req["three_year_minor"] == 1500 * 36
    rec = research.recommend(SimpleNamespace(classification="recurring", origin="purchase_request"), r["findings"])
    assert rec["action"] == "choose_alternative" and rec["saving_three_year_minor"] > 0
    usage = research.research(vendor="Stripe", item="Stripe processing fee", amount_minor=11_000, interval="month", classification="recurring")
    assert all(f["three_year_minor"] is None for f in usage["findings"] if not f["is_requested"])  # usage-priced: never ranked on a made-up price


# ------------------------------------------------------------------ connectors
def test_csv_upload_rejects_bad_rows_and_never_guesses():
    from services.finance import connectors as C
    data = b"Date,Description,Amount\n2026-09-01,Coffee,-4.50\nnot-a-date,X,1\n2026-09-02,Client payment,\"1,200.00\"\n09/03/2026,Refund,(12.00)\n"
    b = C.csv_batch(data)
    assert [t.amount_minor for t in b.transactions] == [-450, 120_000, -1200] and b.rejected == 1 and "row 3" in b.errors[0]
    debit_credit = C.csv_batch(b"Posted Date,Payee,Debit,Credit\n2026-09-01,Rent,1000.00,\n2026-09-02,Sale,,50.00\n")
    assert [t.amount_minor for t in debit_credit.transactions] == [-100_000, 5_000]
    with pytest.raises(C.AdapterError, match="columns"):
        C.csv_batch(b"foo,bar\n1,2\n")


def test_stripe_adapter_maps_fees_and_paginates():
    from services.finance import connectors as C
    pages = [{"data": [{"id": "txn_1", "type": "charge", "amount": 2000, "fee": 88, "created": 1_790_000_000, "currency": "usd"}], "has_more": True},
             {"data": [{"id": "txn_2", "type": "payout", "amount": -1912, "fee": 0, "created": 1_790_000_100, "currency": "usd"}], "has_more": False}]

    def handler(req: httpx.Request):
        assert req.method == "GET" and req.headers["authorization"] == "Bearer rk_test_1"  # read-only calls only
        if req.url.path == "/v1/balance":
            return httpx.Response(200, json={"available": [{"amount": 500, "currency": "usd"}], "pending": [{"amount": 100, "currency": "usd"}]})
        return httpx.Response(200, json=pages.pop(0))
    b = C.stripe_batch("rk_test_1", None, client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://x"))
    assert [(t.amount_minor, t.kind_hint) for t in b.transactions] == [(2000, "revenue"), (-88, "fee"), (-1912, "transfer")]
    assert b.accounts[0].current_balance_minor == 600 and b.accounts[0].available_balance_minor == 500

    def denied(req):
        return httpx.Response(401, json={})
    with pytest.raises(C.AdapterError) as e:
        C.stripe_batch("rk_test_1", None, client=httpx.Client(transport=httpx.MockTransport(denied), base_url="https://x"))
    assert e.value.kind == "auth"


def test_plaid_adapter_flips_signs_and_skips_pending():
    from services.finance import connectors as C

    def handler(req: httpx.Request):
        if req.url.path == "/accounts/balance/get":
            return httpx.Response(200, json={"accounts": [{"account_id": "a1", "name": "Checking", "type": "depository", "subtype": "checking",
                                                           "mask": "0000", "balances": {"current": 100.5, "available": 90, "iso_currency_code": "USD"}}]})
        return httpx.Response(200, json={"added": [{"transaction_id": "t1", "account_id": "a1", "date": "2026-09-01", "amount": 12.34, "name": "Store"},
                                                   {"transaction_id": "t2", "account_id": "a1", "date": "2026-09-02", "amount": -500, "name": "Deposit"},
                                                   {"transaction_id": "t3", "account_id": "a1", "date": "2026-09-03", "amount": 1, "name": "P",
                                                    "pending": True}],
                                         "modified": [], "next_cursor": "c2", "has_more": False})
    cred = json.dumps({"client_id": "c", "secret": "s", "access_token": "a", "env": "sandbox"})
    b = C.plaid_batch(cred, None, client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://x"))
    assert [t.amount_minor for t in b.transactions] == [-1234, 50_000] and b.cursor == "c2"
    assert b.accounts[0].current_balance_minor == 10_050 and b.data_mode == "simulated"  # Plaid sandbox data is not real money


def test_app_store_adapter_reads_usd_proceeds_and_reports_other_currencies():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from services.finance import connectors as C
    key = ec.generate_private_key(ec.SECP256R1()).private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                                 serialization.NoEncryption()).decode()
    tsv = "Units\tDeveloper Proceeds\tCurrency of Proceeds\n3\t0.85\tUSD\n2\t0.70\tEUR\n"

    def handler(req: httpx.Request):
        assert req.headers["authorization"].startswith("Bearer ")
        return httpx.Response(200, content=gzip.compress(tsv.encode()))
    cred = json.dumps({"issuer_id": "i", "key_id": "k", "private_key": key, "vendor_number": "1"})
    b = C.app_store_batch(cred, days=1, client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://x"))
    assert [t.amount_minor for t in b.transactions] == [255] and any("not converted" in e for e in b.errors)


def test_unbuilt_integrations_cannot_be_used():
    from services.finance import connectors as C
    with pytest.raises(C.AdapterError, match="not built"):
        C.fetch("quickbooks", "x")
