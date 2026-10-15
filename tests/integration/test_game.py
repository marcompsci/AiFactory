"""The money game scores only verified money, from authoritative records, idempotently."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from services.core import config, db
from services.finance import stepup
from services.game import scoring
from tests.conftest import wait_for
from tests.integration.test_v5_acceptance import at_tower, request_tool, step_up


@pytest.fixture
def genv(monkeypatch):
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


def test_executed_cheaper_purchase_scores_simulated_savings_once(genv):
    with _client() as c:
        c.post("/api/finance/simulated")
        before = c.get("/api/game").json()
        assert before["totals"] == {"verified_minor": 0, "simulated_minor": 0} and before["season"]["key"]
        pid = request_tool(c)
        d = at_tower(c, pid)
        rec = next(a for a in d["approvals"] if a["details"]["option"] == "recommended")
        secret = c.post("/api/finance/stepup/enroll").json()["secret"]
        r = c.post(f"/api/finance/packets/{pid}/decide", json={"decision": "APPROVE", "approval_id": rec["id"], "payload_hash": rec["payload_hash"]},
                   headers={"X-Step-Up": step_up(c, rec["id"], secret)})
        assert r.status_code == 200, r.text
        wait_for(lambda: c.get(f"/api/finance/packets/{pid}").json()["packet"]["status"] == "EXECUTED", timeout=60)
        g = wait_for(lambda: (x := c.get("/api/game").json())["plays"] and x, timeout=30)
        packet = c.get(f"/api/finance/packets/{pid}").json()["packet"]
        yearly = packet["amount_minor"] * 12
        saved = yearly - rec["amount_minor"] * (12 if rec["details"]["interval"] == "month" else 1)
        assert saved > 0
        plays = [p for p in g["plays"] if p["source_id"] == rec["id"]]
        assert plays and all(p["kind"] == "realized_savings" and p["data_mode"] == "simulated" and not p["verified"] for p in plays)
        assert sum(p["amount_minor"] for p in plays) == saved
        # simulated money never counts as verified
        assert g["totals"]["verified_minor"] == 0 and g["totals"]["simulated_minor"] == saved
        credited = {p["agent_id"] for p in plays}
        with db.get_engine().connect() as conn:
            workers = {t.agent_id for t in conn.execute(select(db.tasks.c.agent_id, db.tasks.c.mission_id, db.tasks.c.status))
                       if t.status == "COMPLETED"}
        assert credited <= workers
        top = g["leaderboard"][0]
        assert top["agent_id"] in credited and top["rank"] == 1
        # idempotent: re-running the scorer adds nothing
        assert scoring.tick() == {"savings": 0, "avoided": 0, "revenue": 0}
        # scores are append-only
        with pytest.raises(Exception):
            from services.core.events import transaction
            with transaction() as conn:
                conn.execute(db.game_scores.update().values(amount_minor=1))


def test_revenue_counts_only_after_an_owner_link(genv):
    from services.core.events import transaction

    org = config.load_seed()["organization_id"]
    with _client() as c:
        c.post("/api/finance/simulated")
        # revenue exists, but no link: nothing is attributed
        assert scoring.tick()["revenue"] == 0
        with transaction() as conn:
            dev = conn.execute(select(db.agents).where(db.agents.c.key == "developer")).first()
            oid = db.new_id()
            conn.execute(db.opportunities.insert().values(
                id=oid, organization_id=org, source_platform="fixture", research_agent_id=dev.id, title="Habit app", description="x",
                evidence=[], confidence="medium", opportunity_score=0.5, proposed_department="app_studio", estimated_effort="S",
                estimated_cost_usd=0, risk_flags=[], artifact_references=[], spec={}, status="RELEASE_AUTHORIZED", data_mode="fixture"))
            mid = db.new_id()
            conn.execute(db.missions.insert().values(id=mid, organization_id=org, project_id=config.load_seed()["project_id"], title="build",
                                                     prompt="x", status="COMPLETED", execution_mode="simulation", kind="build_prototype",
                                                     opportunity_id=oid, params={}))
            conn.execute(db.tasks.insert().values(id=db.new_id(), organization_id=org, mission_id=mid, agent_id=dev.id, key="scaffold",
                                                  title="t", district="code-forge", status="COMPLETED", ordinal=0))
        assert c.post("/api/game/revenue-links", json={"merchant": "Stripe", "opportunity_id": oid}).status_code == 201
        # only revenue posted on/after the link date can be attributed; simulated history is in the past
        with transaction() as conn:
            conn_id = conn.execute(select(db.financial_connections.c.id)).scalar()
            conn.execute(db.financial_transactions.insert().values(
                id=db.new_id(), organization_id=org, connection_id=conn_id, dedupe_key="t-new", posted_at=db.utcnow(), amount_minor=4200,
                currency="USD", description="Stripe payout", merchant="Stripe", kind="revenue", data_mode="simulated"))
        out = scoring.tick()
        assert out["revenue"] == 1
        g = c.get("/api/game").json()
        rev = [p for p in g["plays"] if p["kind"] == "attributed_revenue"]
        assert len(rev) == 1 and rev[0]["amount_minor"] == 4200 and rev[0]["agent_id"] == dev.id and rev[0]["evidence"]["merchant"] == "Stripe"
