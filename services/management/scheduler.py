"""Durable scheduled jobs (supervisor, logistics, pipeline).

Due times live in the `scheduled_jobs` table, so a restart resumes the schedule. Jobs also run early when
poked by events (a mission finishing, an owner decision), which keeps the city responsive without polling a
model. AICIV_TICK_SCALE shrinks every interval (tests use 0.05).
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select, update

from services.core import db
from services.core.events import transaction
from services.logistics import service as logistics

from .pipeline import Pipeline
from .supervisor import supervise

log = logging.getLogger("aiciv.scheduler")


class Scheduler(threading.Thread):
    def __init__(self, enqueue: Callable[[str], None], gateway=None) -> None:
        super().__init__(daemon=True, name="scheduler")
        self.pipeline = Pipeline(enqueue, gateway)
        self._poke = threading.Event()
        self._halt = threading.Event()
        self.scale = float(os.environ.get("AICIV_TICK_SCALE", "1"))
        self.jobs: dict[str, Callable[[], dict | int]] = {
            "logistics": self._logistics,
            "pipeline": self.pipeline.tick,
            "supervisor": self._supervisor,
        }

    def poke(self) -> None:
        self._poke.set()

    def stop(self) -> None:
        self._halt.set()
        self._poke.set()

    def _logistics(self) -> dict:
        with transaction() as conn:
            return logistics.tick(conn)

    def _supervisor(self) -> dict:
        with transaction() as conn:
            return supervise(conn)

    def run_due(self, force: bool = False) -> dict:
        now = datetime.now(timezone.utc)
        with db.get_engine().connect() as conn:
            rows = {r.key: r for r in conn.execute(select(db.scheduled_jobs))}
        results = {}
        for key, fn in self.jobs.items():
            row = rows.get(key)
            if row is None:
                continue
            due = datetime.fromisoformat(row.next_run_at) <= now
            if not (due or (force and key != "supervisor")):
                continue
            try:
                res = fn()
            except Exception as exc:  # recorded on the job row; the next run retries
                log.exception("job %s failed", key)
                res = {"error": str(exc)[:300]}
            results[key] = res
            with transaction() as conn:
                conn.execute(update(db.scheduled_jobs).where(db.scheduled_jobs.c.key == key).values(
                    last_run_at=now.isoformat(), last_result=res if isinstance(res, dict) else {"steps": res},
                    next_run_at=(now + timedelta(seconds=row.interval_seconds * self.scale)).isoformat()))
        return results

    def run(self) -> None:
        while not self._halt.is_set():
            poked = self._poke.wait(timeout=max(0.05, 0.25 * self.scale))
            self._poke.clear()
            if self._halt.is_set():
                break
            try:
                self.run_due(force=poked)
            except Exception:
                log.exception("scheduler loop error")
