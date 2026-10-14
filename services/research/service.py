"""Research runs: limits, dedupe/caching and evidence storage. Called only through the
`query_market_source` tool so permissions, budgets and audit apply like any other tool."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection

from services.core import db
from services.core.events import emit

from .connectors import CONNECTORS, RawResult, Unavailable

CACHE_HOURS = 6


class ResearchLimit(Exception):
    pass


def query_hash(query: str) -> str:
    return hashlib.sha256(query.strip().lower().encode()).hexdigest()[:24]


def _source(conn: Connection, org_id: str, key: str):
    s = conn.execute(select(db.market_sources).where(db.market_sources.c.organization_id == org_id, db.market_sources.c.key == key)).first()
    if s is None:
        raise ResearchLimit(f"unknown market source {key}")
    return s


def check_limits(conn: Connection, source) -> None:
    now = datetime.now(timezone.utc)
    hour = conn.execute(select(func.count()).select_from(db.research_runs).where(
        db.research_runs.c.source_id == source.id, db.research_runs.c.started_at >= (now - timedelta(hours=1)).isoformat(),
        db.research_runs.c.data_mode == "live")).scalar()
    if hour >= source.rate_limit_per_hour:
        raise ResearchLimit(f"{source.name}: hourly limit {source.rate_limit_per_hour} reached")
    day = conn.execute(select(func.count()).select_from(db.research_runs).where(
        db.research_runs.c.source_id == source.id, db.research_runs.c.started_at >= now.date().isoformat())).scalar()
    if day >= source.daily_query_limit:
        raise ResearchLimit(f"{source.name}: daily query limit {source.daily_query_limit} reached")


def run(conn_factory, *, org_id: str, agent_id: str, mission_id: str | None, source_key: str, query: str, region: str = "US") -> dict:
    """conn_factory is `transaction`; the network call happens outside any open transaction."""
    qh = query_hash(query)
    cache_key = f"{source_key}:{qh}:{region}"
    with conn_factory() as conn:
        source = _source(conn, org_id, source_key)
        cached = conn.execute(select(db.research_cache).where(db.research_cache.c.key == cache_key,
                                                              db.research_cache.c.expires_at > db.utcnow())).first()
        if not cached:
            check_limits(conn, source)
        run_id = db.new_id()
        conn.execute(insert(db.research_runs).values(id=run_id, organization_id=org_id, source_id=source.id, research_agent_id=agent_id,
                                                     mission_id=mission_id, query=query, query_hash=qh, region=region, status="RUNNING",
                                                     data_mode="cache" if cached else "live"))
        emit(conn, "research.started", mission_id=mission_id, agent_id=agent_id,
             payload={"run_id": run_id, "source": source_key, "query": query, "region": region, "cached": bool(cached)})
    if cached:
        raw = RawResult(**cached.payload)
        mode = "cache"
    else:
        try:
            raw = CONNECTORS[source_key]().fetch(query, region)
        except Unavailable as exc:
            with conn_factory() as conn:
                conn.execute(update(db.research_runs).where(db.research_runs.c.id == run_id).values(
                    status="FAILED", error=str(exc), finished_at=db.utcnow(), data_mode="live"))
                emit(conn, "research.completed", mission_id=mission_id, agent_id=agent_id,
                     payload={"run_id": run_id, "source": source_key, "status": "unavailable", "reason": str(exc)})
            return {"run_id": run_id, "status": "unavailable", "reason": str(exc), "findings": []}
        mode = raw.data_mode
    findings = []
    with conn_factory() as conn:
        if not cached:
            payload = raw.__dict__
            conn.execute(db.research_cache.delete().where(db.research_cache.c.key == cache_key))
            conn.execute(insert(db.research_cache).values(key=cache_key, payload=payload, data_mode=raw.data_mode,
                                                          expires_at=(datetime.now(timezone.utc) + timedelta(hours=CACHE_HOURS)).isoformat()))
        conn.execute(update(db.research_runs).where(db.research_runs.c.id == run_id).values(
            status="COMPLETED", finished_at=db.utcnow(), data_mode=mode))
        f = _finding(conn, org_id, run_id, raw, query)
        if f:
            findings.append(f)
            emit(conn, "research.finding_created", mission_id=mission_id, agent_id=agent_id,
                 payload={"finding_id": f["id"], "title": f["title"], "source_url": f["source_url"], "data_mode": f["data_mode"],
                          "measurement_type": f["measurement_type"], "confidence": f["confidence"]})
    return {"run_id": run_id, "status": "completed", "data_mode": raw.data_mode, "from_cache": bool(cached),
            "notice": raw.notice, "findings": findings}


def _finding(conn: Connection, org_id: str, run_id: str, raw: RawResult, query: str) -> dict | None:
    if not raw.items and raw.measurement_type != "ranking":
        return None
    if raw.measurement_type == "ranking":
        title = f"'{query}' in {raw.source_platform.replace('_', ' ')} top charts ({raw.region})"
        summary = (f"{len(raw.items)} matching apps in the top {raw.extra.get('chart_size', 50)} free chart"
                   + (f"; best rank {min(i['rank'] for i in raw.items)}" if raw.items else ""))
        metrics = {"entries": raw.items, "chart_size": raw.extra.get("chart_size", 50)}
    elif raw.measurement_type == "listing_count":
        title = f"'{query}' listings on {raw.source_platform}"
        summary = f"{raw.extra.get('count', len(raw.items))} active listings; favorites shown are a popularity proxy, not sales"
        metrics = {"listings": raw.items, "count": raw.extra.get("count")}
    else:
        title = f"'{query}' on {raw.source_platform}"
        summary = f"{len(raw.items)} items ({raw.measurement_type.replace('_', ' ')})"
        metrics = {"items": raw.items}
    row = dict(id=db.new_id(), organization_id=org_id, run_id=run_id, source_platform=raw.source_platform, title=title,
               summary=summary, source_url=raw.source_url, collected_at=raw.collected_at, geographic_scope=raw.region,
               data_coverage=raw.coverage, measurement_type=raw.measurement_type, metrics=metrics,
               confidence="medium" if len(raw.items) >= 2 else "low", data_mode=raw.data_mode)
    conn.execute(insert(db.research_findings).values(**row))
    return row
