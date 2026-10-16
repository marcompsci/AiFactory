"""V6 playable town: NPC dialogue is grounded in backend records, and actions run only on an explicit confirm."""
from tests.conftest import mission_status, wait_for

ATLAS = "a1000000-0000-4000-8000-000000000007"   # General Manager
KADE = "a1000000-0000-4000-8000-000000000003"    # Developer
LUMEN = "a1000000-0000-4000-8000-000000000005"   # Researcher


def say(client, agent, text):
    r = client.post("/api/play/talk", json={"agent_id": agent, "text": text})
    assert r.status_code == 200, r.text
    return r.json()


def test_player_state_round_trips_and_is_validated(client):
    assert client.get("/api/play/state").json()["player"] is None
    body = {"name": "Omari", "look": {"hair_style": "spiky", "hair": "#111111", "glasses": True}, "map": "code-forge", "x": 5.5, "y": 7, "facing": "left"}
    assert client.put("/api/play/state", json=body).status_code == 200
    got = client.get("/api/play/state").json()["player"]
    assert got["map"] == "code-forge" and got["look"]["hair"] == "#111111" and got["facing"] == "left"
    assert client.put("/api/play/state", json={**body, "map": "moon"}).status_code == 422
    assert client.put("/api/play/state", json={**body, "look": {"hair": "red"}}).status_code == 422


def test_greeting_and_status_come_from_records(client):
    hi = say(client, ATLAS, "hello")
    assert "Atlas" in hi["reply"] and hi["proposal"] is None and hi["suggestions"]
    st = say(client, KADE, "what are you working on?")
    assert "No task is assigned to me" in st["reply"] and st["proposal"] is None
    assert say(client, ATLAS, "what needs my approval?")["reply"].startswith("Nothing is waiting")
    assert "no missions yet" in say(client, ATLAS, "show everything in progress")["reply"].lower()


def test_research_request_needs_explicit_confirm(client):
    r = say(client, LUMEN, "Please research budgeting apps on the App Store")
    prop = r["proposal"]
    assert prop and prop["kind"] == "start_research" and prop["params"] == {"source": "apple_charts", "query": "budgeting apps", "region": "US"}
    # talking about it, or reading the conversation, starts nothing
    assert client.get("/api/missions").json()["missions"] == []
    convo = client.get(f"/api/play/conversations/{LUMEN}").json()
    assert [m["speaker"] for m in convo["messages"]] == ["owner", "npc"] and convo["proposals"][prop["id"]]["status"] == "PENDING"
    done = client.post(f"/api/play/proposals/{prop['id']}/confirm").json()
    assert done["status"] == "CONFIRMED" and done["result"]["mission_id"]
    assert len(client.get("/api/missions").json()["missions"]) == 1
    assert client.post(f"/api/play/proposals/{prop['id']}/confirm").status_code == 409  # never twice


def test_mission_request_runs_through_the_mission_pipeline(client):
    prop = say(client, KADE, "Fix the failing test in the sample repository")["proposal"]
    assert prop["kind"] == "create_mission"
    done = client.post(f"/api/play/proposals/{prop['id']}/confirm").json()
    mid = done["result"]["mission_id"]
    assert done["result"]["execution_mode"] == "simulation" and "simulation" in done["message"]["text"]
    wait_for(lambda: mission_status(client, mid)["status"] != "CREATED")
    # the NPC reports its real work, and the GM sees the mission
    assert "mission" in say(client, ATLAS, "show everything in progress")["reply"]


def test_decline_and_role_redirects(client):
    prop = say(client, KADE, "build a settings page")["proposal"]
    assert client.post(f"/api/play/proposals/{prop['id']}/decline").json()["status"] == "DECLINED"
    assert client.post(f"/api/play/proposals/{prop['id']}/confirm").status_code == 409
    assert client.get("/api/missions").json()["missions"] == []
    # a developer doesn't start research, a researcher doesn't write code
    assert say(client, KADE, "research candles on etsy")["proposal"] is None
    assert say(client, LUMEN, "fix the login bug")["proposal"] is None
    assert say(client, LUMEN, "dance for me")["proposal"] is None


def test_cancel_offer_targets_a_running_mission(client):
    m = client.post("/api/missions", json={"prompt": "Fix the failing test in the sample repo"}).json()
    prop = say(client, ATLAS, "cancel the failing test mission")["proposal"]
    assert prop["kind"] == "cancel_mission" and prop["params"]["mission_id"] == m["id"]
    client.post(f"/api/play/proposals/{prop['id']}/confirm")
    wait_for(lambda: mission_status(client, m["id"])["status"] == "CANCELLED")


def test_expired_offers_cannot_be_confirmed(client):
    from sqlalchemy import update
    from services.core import db
    prop = say(client, LUMEN, "research habit trackers")["proposal"]
    with db.get_engine().begin() as conn:
        conn.execute(update(db.play_proposals).values(expires_at="2000-01-01T00:00:00+00:00"))
    assert client.post(f"/api/play/proposals/{prop['id']}/confirm").status_code == 409
    assert client.get("/api/missions").json()["missions"] == []
