"""Durable background worker.

Runs missions on a bounded pool (AICIV_MAX_CONCURRENT_MISSIONS). The queue itself is the database:
on start, `recover()` finds every mission that was mid-flight when the process died, marks the
interrupted task runs FAILED("worker interrupted"), returns those tasks to PENDING and re-enqueues the
missions. In a multi-instance deployment, swap the in-process queue for Redis (see docs/operations).
"""
from __future__ import annotations

import heapq
import itertools
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select, update

from services.core import db
from services.core.config import get_settings
from services.core.events import emit, transaction
from services.orchestrator import ops
from services.orchestrator.runner import MissionRunner

log = logging.getLogger("aiciv.worker")
ACTIVE = ["CREATED", "VALIDATING", "PLANNING", "QUEUED", "RUNNING"]


RANK = {"urgent": 0, "normal": 1, "low": 2}


def priority_of(mission_id: str) -> str:
    with db.get_engine().connect() as conn:
        return conn.execute(select(db.mission_priorities.c.priority).where(db.mission_priorities.c.mission_id == mission_id)).scalar() or "normal"


class MissionWorker:
    def __init__(self, gateway=None, on_finish=None, max_concurrent: int | None = None) -> None:
        self.on_finish = on_finish  # pokes the scheduler so the pipeline reacts to finished missions at once
        self.max = max_concurrent or get_settings().max_concurrent_missions
        self.pool = ThreadPoolExecutor(max_workers=self.max, thread_name_prefix="mission")
        self._inflight: set[str] = set()
        self._rerun: set[str] = set()
        self._running = 0
        self._waiting: list[tuple[int, int, str]] = []  # (rank, arrival, mission): urgent first, then first come
        self._seq = itertools.count()
        self._lock = threading.Lock()
        self.gateway = gateway

    def enqueue(self, mission_id: str) -> None:
        rank = RANK.get(priority_of(mission_id), 1)
        with self._lock:
            if mission_id in self._inflight:
                self._rerun.add(mission_id)  # e.g. approval granted while the runner is finishing up
                return
            self._inflight.add(mission_id)
            if self._running >= self.max:  # every slot busy: wait in line by priority
                heapq.heappush(self._waiting, (rank, next(self._seq), mission_id))
                return
            self._running += 1
        self.pool.submit(self._run, mission_id)

    def reprioritize(self, mission_id: str, priority: str) -> None:
        """Move a waiting mission up or down the line (no effect once it's running)."""
        with self._lock:
            for i, (_, seq, mid) in enumerate(self._waiting):
                if mid == mission_id:
                    self._waiting[i] = (RANK.get(priority, 1), seq, mid)
                    heapq.heapify(self._waiting)
                    break

    def waiting(self) -> list[str]:
        with self._lock:
            return [mid for _, _, mid in sorted(self._waiting)]

    def _next(self) -> str | None:
        """Called with the lock held when a slot frees up: the next mission in line, or None (slot released)."""
        if self._waiting:
            return heapq.heappop(self._waiting)[2]
        self._running -= 1
        return None

    def _run(self, mission_id: str) -> None:
        while True:
            try:
                status = MissionRunner(mission_id, self.gateway).run()
                log.info("mission %s -> %s", mission_id, status)
                if self.on_finish:
                    self.on_finish()
            except Exception:
                log.exception("mission %s crashed", mission_id)
                try:
                    MissionRunner(mission_id, self.gateway)._fail("internal error in mission runner")
                except Exception:
                    log.exception("could not mark mission failed")
            with self._lock:
                if mission_id in self._rerun:
                    self._rerun.discard(mission_id)
                    continue
                self._inflight.discard(mission_id)
                nxt = self._next()
            if nxt:
                mission_id = nxt  # keep this slot: run the next mission in line on it
                continue
            return

    def recover(self) -> list[str]:
        with transaction() as conn:
            interrupted = conn.execute(select(db.task_runs).where(db.task_runs.c.status == "RUNNING")).fetchall()
            for run in interrupted:
                conn.execute(update(db.task_runs).where(db.task_runs.c.id == run.id).values(
                    status="FAILED", error="worker interrupted", finished_at=db.utcnow()))
            for t in conn.execute(select(db.tasks).where(db.tasks.c.status == "RUNNING")).fetchall():
                ops.set_task_status(conn, t.id, "PENDING", error="re-queued after worker restart")
            for a in conn.execute(select(db.agents).where(db.agents.c.execution_state.notin_(["IDLE", "WAITING_FOR_APPROVAL"]))).fetchall():
                ops.reset_agent(conn, a.id, "worker restart")
            for p in conn.execute(select(db.agent_positions).where(db.agent_positions.c.movement_state == "MOVING")).fetchall():
                conn.execute(update(db.agent_positions).where(db.agent_positions.c.agent_id == p.agent_id).values(movement_state="STATIONARY"))
            missions = conn.execute(select(db.missions.c.id).where(db.missions.c.status.in_(ACTIVE), db.missions.c.paused == 0)).fetchall()
            if interrupted or missions:
                emit(conn, "agent.message", payload={"kind": "status", "body": f"Worker recovered {len(missions)} mission(s) after restart."})
        ids = [m.id for m in missions]
        for mid in ids:
            self.enqueue(mid)
        return ids

    def shutdown(self) -> None:
        # Graceful: let in-flight steps reach a checkpoint. A hard kill is also safe (see recover()).
        self.pool.shutdown(wait=True, cancel_futures=True)
