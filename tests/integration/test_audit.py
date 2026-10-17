"""V6.9 tamper-evident log: every event is chained; changing, deleting or skipping one is reported at the right place;
the chain can't be edited; a mission's audit file carries its events, links and a bundle hash."""
import hashlib
import json

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError

from services.core import audit, db
from services.core.events import ORG_ID, transaction
from tests.conftest import mission_status, wait_for
from tests.integration.test_missions import pending_approval, start


def _verify(client):
    r = client.get("/api/insights/audit/verify")
    assert r.status_code == 200, r.text
    return r.json()


def test_a_clean_log_verifies(client):
    mid = start(client)
    pending_approval(client, mid)
    v = _verify(client)
    assert v["ok"] is True and v["checked"] > 10 and v["from_sequence"] == 1 and len(v["latest_hash"]) == 64
    with db.get_engine().connect() as conn:
        n = conn.execute(select(db.events.c.sequence).order_by(db.events.c.sequence.desc()).limit(1)).scalar()
        links = conn.execute(select(db.event_chain).order_by(db.event_chain.c.sequence)).fetchall()
    assert links[0].prev_hash == audit.GENESIS and links[-1].sequence >= n - 5  # background ticks may add a few more
    assert all(b.prev_hash == a.hash for a, b in zip(links, links[1:]))


def test_editing_an_event_is_caught_where_it_happened(client):
    mid = start(client)
    pending_approval(client, mid)
    with transaction() as conn:
        target = conn.execute(select(db.events.c.sequence).where(db.events.c.event_type == "task.completed")
                              .order_by(db.events.c.sequence)).scalar()
        conn.execute(update(db.events).where(db.events.c.sequence == target).values(payload={"title": "rewritten"}))
    v = _verify(client)
    assert v["ok"] is False and v["problem"]["sequence"] == target and "changed" in v["problem"]["reason"]


def test_deleting_an_event_is_caught(client):
    mid = start(client)
    pending_approval(client, mid)
    with transaction() as conn:
        target = conn.execute(select(db.events.c.sequence).where(db.events.c.event_type == "tool.started")
                              .order_by(db.events.c.sequence)).scalar()
        conn.execute(delete(db.event_outbox).where(db.event_outbox.c.event_id.in_(
            select(db.events.c.id).where(db.events.c.sequence == target))))
        conn.execute(delete(db.events).where(db.events.c.sequence == target))
    v = _verify(client)
    assert v["ok"] is False and v["problem"]["sequence"] == target and "deleted" in v["problem"]["reason"]


def test_the_chain_itself_is_append_only(client):
    start(client)
    with pytest.raises(DBAPIError):
        with transaction() as conn:
            conn.execute(update(db.event_chain).where(db.event_chain.c.sequence == 1).values(hash="f" * 64))
    with pytest.raises(DBAPIError):
        with transaction() as conn:
            conn.execute(delete(db.event_chain))


def test_mission_audit_file(client):
    mid = start(client)
    a = pending_approval(client, mid)
    client.post(f"/api/approvals/{a['id']}/grant")
    wait_for(lambda: mission_status(client, mid)["status"] == "COMPLETED")
    r = client.get(f"/api/insights/audit/missions/{mid}")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    b = r.json()
    assert b["format"] == "aiciv.mission-audit.v1" and b["mission"]["id"] == mid and b["chain"]["ok"] is True
    assert b["events"] and all(e["mission_id"] == mid and len(e["chain_hash"]) == 64 for e in b["events"])
    assert b["objective"]["met"] is True and b["trace"]["items"]
    claimed = b.pop("bundle_sha256")
    assert hashlib.sha256(json.dumps(b, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False).encode()).hexdigest() == claimed
    assert client.get("/api/insights/audit/missions/00000000-0000-4000-8000-000000000999").status_code == 404


def test_unchained_events_are_reported(client):
    start(client)
    with transaction() as conn:
        seq = conn.execute(select(db.events.c.sequence).order_by(db.events.c.sequence.desc()).limit(1)).scalar() + 1
        conn.execute(db.events.insert().values(id=db.new_id(), organization_id=ORG_ID, sequence=seq, event_type="agent.message",
                                               schema_version=1, correlation_id="x", execution_mode="live", payload={},
                                               occurred_at=db.utcnow()))
    v = _verify(client)
    assert v["ok"] is False and v["problem"]["sequence"] == seq and "never chained" in v["problem"]["reason"]
