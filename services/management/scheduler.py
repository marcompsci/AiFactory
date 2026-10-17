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
from services.core.events import ORG_ID, transaction
from services.logistics import service as logistics

from . import charter
from .pipeline import Pipeline
from .supervisor import supervise

log = logging.getLogger("aiciv.scheduler")


class Scheduler(threading.Thread):
    def __init__(self, enqueue: Callable[[str], None], gateway=None) -> None:
        super().__init__(daemon=True, name="scheduler")
        self.pipeline = Pipeline(enqueue, gateway)
        from services.finance.pipeline import FinancePipeline

        self.finance = FinancePipeline(enqueue, gateway)
        from services.applab.pipeline import AppLabPipeline

        self.applab = AppLabPipeline(enqueue, gateway)
        self._poke = threading.Event()
        self._halt = threading.Event()
        self.scale = float(os.environ.get("AICIV_TICK_SCALE", "1"))
        self.jobs: dict[str, Callable[[], dict | int]] = {
            "logistics": self._logistics,
            "pipeline": self.pipeline.tick,
            "supervisor": self._supervisor,
            "finance": self.finance.tick,
            "applab": self.applab.tick,
            "game": self._game,
            "factories": self._factories,
            "schedules": self._schedules,
        }

    def poke(self) -> None:
        self._poke.set()

    def stop(self) -> None:
        self._halt.set()
        self._poke.set()

    def _logistics(self) -> dict:
        with transaction() as conn:
            return logistics.tick(conn)

    def _factories(self) -> dict:
        from services.factories.pipeline import tick
        return tick(self.applab.enqueue)

    def _schedules(self) -> dict:
        """Start every due schedule's mission through the regular functions (emergency stop, charter caps apply)."""
        from fastapi import HTTPException

        from services.api import main, v4
        from services.core.auth import Principal

        from . import schedules
        with transaction() as conn:
            due = schedules.claim_due(conn)
        started = 0
        for s in due:
            p = Principal(user_id=s["created_by"], organization_id=s["organization_id"], role="operator", mode="schedule")
            mid, err = None, None
            try:
                if s["kind"] == "run_tests":
                    m = main.create_mission(main.MissionIn(prompt=s["params"]["prompt"], kind="run_tests",
                                                           title=s["title"][:120], idempotency_key=f"schedule:{s['id']}:{s['slot']}"), p)
                    mid = m["id"]
                else:
                    mid = v4.start_research(v4.ResearchIn(**s["params"]), p)["mission_id"]
                started += 1
            except HTTPException as exc:
                err = str(exc.detail)[:300]
            except Exception as exc:  # recorded on the schedule; the next slot tries again
                log.exception("schedule %s failed", s["id"])
                err = str(exc)[:300]
            with transaction() as conn:
                schedules.record_run(conn, s["id"], mission_id=mid, error=err)
        return {"due": len(due), "started": started}

    def _game(self) -> dict:
        from services.game.scoring import tick
        return tick()

    def _supervisor(self) -> dict:
        with transaction() as conn:
            return supervise(conn)

    def run_due(self, force: bool = False) -> dict:
        now = datetime.now(timezone.utc)
        with db.get_engine().connect() as conn:
            rows = {r.key: r for r in conn.execute(select(db.scheduled_jobs))}
        results = {}
        with db.get_engine().connect() as conn:
            quiet = charter.quiet_now(charter.rules(conn, ORG_ID))
        for key, fn in self.jobs.items():
            row = rows.get(key)
            if row is None:
                continue
            due = datetime.fromisoformat(row.next_run_at) <= now
            if not (due or (force and key != "supervisor")):
                continue
            try:
                res = {"waiting": "quiet hours (your charter)"} if quiet and key in charter.QUIET_JOBS else fn()
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
