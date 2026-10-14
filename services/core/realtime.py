"""Outbox publisher and realtime fan-out.

Delivery path:  events/outbox rows (Postgres, authoritative)
             -> OutboxPublisher (polls unpublished outbox rows in id order)
             -> in-process Broadcaster (Server-Sent Events to connected clients)
             -> optional SupabaseBroadcastAdapter (Supabase Realtime Broadcast) when configured

Clients never treat a realtime message as the record of work: they hydrate from /api/snapshot and
replay gaps via /api/events?after=<sequence>.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

import httpx
from sqlalchemy import select, update

from . import db
from .config import get_settings
from .events import to_envelope

log = logging.getLogger("aiciv.realtime")


class Broadcaster:
    def __init__(self) -> None:
        self._subs: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> tuple[asyncio.AbstractEventLoop, asyncio.Queue]:
        sub = (asyncio.get_running_loop(), asyncio.Queue(maxsize=1000))
        with self._lock:
            self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: tuple[asyncio.AbstractEventLoop, asyncio.Queue]) -> None:
        with self._lock:
            self._subs.discard(sub)

    def publish(self, envelope: dict) -> None:
        with self._lock:
            subs = list(self._subs)
        for loop, q in subs:
            def _put(q: asyncio.Queue = q) -> None:
                if q.full():  # slow client: drop; it will reconcile from the sequence gap
                    return
                q.put_nowait(envelope)
            try:
                loop.call_soon_threadsafe(_put)
            except RuntimeError:
                self.unsubscribe((loop, q))

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)


class SupabaseBroadcastAdapter:
    """Sends each envelope to Supabase Realtime Broadcast (channel per organization). Optional."""

    def __init__(self, url: str, service_key: str) -> None:
        self.endpoint = url.rstrip("/") + "/realtime/v1/api/broadcast"
        self.headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}

    def send(self, envelope: dict) -> None:
        body = {"messages": [{"topic": f"org:{envelope['organization_id']}", "event": envelope["event_type"], "payload": envelope}]}
        r = httpx.post(self.endpoint, json=body, headers=self.headers, timeout=5)
        r.raise_for_status()


class OutboxPublisher(threading.Thread):
    def __init__(self, broadcaster: Broadcaster, interval: float = 0.15) -> None:
        super().__init__(daemon=True, name="outbox-publisher")
        self.broadcaster = broadcaster
        self.interval = interval
        self._halt = threading.Event()
        s = get_settings()
        self.supabase = SupabaseBroadcastAdapter(s.supabase_url, s.supabase_service_role_key) if s.supabase_url and s.supabase_service_role_key else None

    def stop(self) -> None:
        self._halt.set()

    def run(self) -> None:
        while not self._halt.is_set():
            try:
                self.drain()
            except Exception:  # keep publishing; errors are recorded per row
                log.exception("outbox drain failed")
            self._halt.wait(self.interval)

    def drain(self) -> int:
        engine = db.get_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                select(db.event_outbox.c.id.label("outbox_id"), *db.events.c)
                .join(db.events, db.events.c.id == db.event_outbox.c.event_id)
                .where(db.event_outbox.c.published_at.is_(None))
                .order_by(db.event_outbox.c.id)
                .limit(200)
            ).fetchall()
        sent = 0
        for row in rows:
            m: dict[str, Any] = dict(row._mapping)
            outbox_id = m.pop("outbox_id")
            envelope = to_envelope(m)
            error = None
            self.broadcaster.publish(envelope)
            if self.supabase:
                try:
                    self.supabase.send(envelope)
                except Exception as exc:  # local SSE still delivered; record and move on
                    error = str(exc)[:500]
            with db.write_lock, engine.begin() as conn:
                conn.execute(
                    update(db.event_outbox)
                    .where(db.event_outbox.c.id == outbox_id)
                    .values(published_at=db.utcnow(), attempts=db.event_outbox.c.attempts + 1, last_error=error)
                )
            sent += 1
        return sent
