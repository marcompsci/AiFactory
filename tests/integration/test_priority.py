"""V6.17 mission priority: when every slot is busy, waiting missions start urgent first, then normal, then low (first
come first served within a level); moving a waiting mission changes its place in line."""
import threading
import time

from services.workers import worker as worker_mod


def test_waiting_missions_start_by_priority(monkeypatch):
    started: list[str] = []
    gate = threading.Event()
    prio = {"busy": "normal", "low1": "low", "norm1": "normal", "urg1": "urgent", "norm2": "normal"}

    class FakeRunner:
        def __init__(self, mid, gateway=None):
            self.mid = mid

        def run(self):
            started.append(self.mid)
            if self.mid == "busy":
                gate.wait(5)  # hold the only slot until everything else is queued
            return "COMPLETED"

    monkeypatch.setattr(worker_mod, "MissionRunner", FakeRunner)
    monkeypatch.setattr(worker_mod, "priority_of", lambda mid: prio[mid])
    w = worker_mod.MissionWorker(max_concurrent=1)
    w.enqueue("busy")
    time.sleep(0.1)
    for mid in ("low1", "norm1", "urg1", "norm2"):
        w.enqueue(mid)
    assert w.waiting() == ["urg1", "norm1", "norm2", "low1"]
    w.reprioritize("low1", "urgent")  # the owner bumps it
    assert w.waiting()[0] == "low1"
    gate.set()
    deadline = time.time() + 5
    while len(started) < 5 and time.time() < deadline:
        time.sleep(0.02)
    assert started == ["busy", "low1", "urg1", "norm1", "norm2"]  # low1 is urgent now and arrived before urg1
    assert w.waiting() == [] and w._running == 0


def test_priority_is_set_at_creation_and_changed_later(client):
    r = client.post("/api/missions", json={"prompt": "Inspect the sample project and fix the failing test.", "priority": "urgent"})
    assert r.status_code == 201
    mid = r.json()["id"]
    assert client.get(f"/api/missions/{mid}").json()["priority"] == "urgent"
    r = client.post(f"/api/missions/{mid}/priority", json={"priority": "low"})
    assert r.status_code == 200 and r.json()["priority"] == "low"
    assert client.get(f"/api/missions/{mid}").json()["priority"] == "low"
    assert client.post(f"/api/missions/{mid}/priority", json={"priority": "asap"}).status_code == 422
    assert "mission.priority_changed" in [e["event_type"] for e in client.get("/api/events?after=0").json()["events"]]
