"""Durable package routing.

The database decides where every package is. `tick()` (run by the scheduler) advances packages using
the stored route, route_started_at and belt speed: a package is ARRIVED only when the backend says its
ETA has passed and every belt it needed was up. The 3D conveyor only draws what these rows and their
`package.*` events say; an animation finishing never delivers anything.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection

from services.core import db
from services.core.events import emit
from services.core.state import assert_v4_transition

from .graph import shortest_path

PACKAGE_TYPES = {"research_brief", "product_proposal", "design_spec", "code_artifact", "test_report",
                 "revision_request", "approval_request", "release_package",
                 # V5 AI Central Bank. Each references its authoritative record via subject_type/subject_id.
                 "revenue_report", "expense_alert", "bill_reminder", "fee_research_request", "savings_recommendation",
                 "purchase_request", "payment_proposal", "tax_review_package", "financial_forecast", "owner_approval_request",
                 "savings_investigation"}
FINANCE_PACKAGE_TYPES = {"revenue_report", "expense_alert", "bill_reminder", "fee_research_request", "savings_recommendation",
                         "purchase_request", "payment_proposal", "tax_review_package", "financial_forecast", "owner_approval_request",
                         "savings_investigation"}


def belt_speed() -> float:
    """World units per second. Tests raise it so packages arrive within one tick."""
    return float(os.environ.get("AICIV_BELT_SPEED", "8"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat()


def _parse(s: str) -> datetime:
    return datetime.fromisoformat(s)


def segments(conn: Connection) -> list[dict]:
    return [dict(r._mapping) for r in conn.execute(select(db.logistics_routes))]


def load_by_segment(conn: Connection) -> dict[str, int]:
    """Packages currently on each segment (congestion)."""
    counts: dict[str, int] = {}
    for p in conn.execute(select(db.logistics_packages.c.route).where(db.logistics_packages.c.status == "IN_TRANSIT")):
        for sid in p.route or []:
            counts[sid] = counts.get(sid, 0) + 1
    return counts


def plan_route(conn: Connection, start_node: str, goal_node: str) -> list[dict] | None:
    load = load_by_segment(conn)
    return shortest_path(segments(conn), start_node, goal_node, cost=lambda s: s["length"] * (1 + 0.5 * load.get(s["id"], 0)))


def _transition(conn: Connection, pkg, target: str, event: str | None, detail: dict, **values) -> None:
    assert_v4_transition("package", pkg.status, target)
    conn.execute(update(db.logistics_packages).where(db.logistics_packages.c.id == pkg.id).values(status=target, **values))
    conn.execute(insert(db.package_transitions).values(package_id=pkg.id, from_status=pkg.status, to_status=target, detail=detail))
    if event:
        emit(conn, event, mission_id=pkg.mission_id, agent_id=detail.get("agent_id"),
             payload={"package_id": pkg.id, "package_type": pkg.package_type, "origin": pkg.origin_district,
                      "destination": pkg.destination_district, "opportunity_id": pkg.opportunity_id, "priority": pkg.priority,
                      "artifact_references": pkg.artifact_references, "subject_type": pkg.subject_type, "subject_id": pkg.subject_id, **detail, **{k: v for k, v in values.items() if k in ("route", "route_started_at", "eta")}})


def create_package(conn: Connection, *, org_id: str, package_type: str, origin: str, destination: str,
                   opportunity_id: str | None = None, mission_id: str | None = None, task_id: str | None = None,
                   artifact_references: list | None = None, priority: int = 5, carrier_agent_id: str | None = None,
                   subject_type: str | None = None, subject_id: str | None = None) -> str:
    if package_type not in PACKAGE_TYPES:
        raise ValueError(f"unknown package type {package_type}")
    if package_type in FINANCE_PACKAGE_TYPES and not (subject_type and subject_id):
        raise ValueError("financial packages must reference their authoritative record")
    pid = db.new_id()
    conn.execute(insert(db.logistics_packages).values(
        id=pid, organization_id=org_id, opportunity_id=opportunity_id, mission_id=mission_id, task_id=task_id,
        package_type=package_type, priority=priority, origin_district=origin, destination_district=destination,
        status="QUEUED", route=[], current_node=f"{origin}:dispatch", artifact_references=artifact_references or [],
        subject_type=subject_type, subject_id=subject_id))
    conn.execute(insert(db.package_transitions).values(package_id=pid, from_status=None, to_status="QUEUED", detail={}))
    dispatch(conn, pid, carrier_agent_id=carrier_agent_id)
    return pid


def _package(conn: Connection, pid: str):
    return conn.execute(select(db.logistics_packages).where(db.logistics_packages.c.id == pid)).first()


def dispatch(conn: Connection, pid: str, carrier_agent_id: str | None = None) -> bool:
    p = _package(conn, pid)
    start = p.current_node or f"{p.origin_district}:dispatch"
    goal = f"{p.destination_district}:receiving"
    path = plan_route(conn, start, goal)
    if not path:
        backoff = min(60, 2 ** (p.attempts + 1))
        _transition(conn, p, "DELIVERY_FAILED", "package.delivery_failed", {"reason": "no available route", "retry_in_s": backoff},
                    attempts=p.attempts + 1, next_attempt_at=_iso(_now() + timedelta(seconds=backoff)))
        return False
    now = _now()
    length = sum(s["length"] for s in path)
    eta = now + timedelta(seconds=length / belt_speed())
    route = [s["id"] for s in path]
    first = p.dispatched_at is None
    _transition(conn, p, "IN_TRANSIT", "package.dispatched" if first else "package.rerouted",
                {"route_length": round(length, 2), "belt_speed": belt_speed(), "agent_id": carrier_agent_id, "from_node": start},
                route=route, route_started_at=_iso(now), eta=_iso(eta), attempts=p.attempts + (0 if first else 1),
                dispatched_at=p.dispatched_at or _iso(now))
    emit(conn, "package.in_transit", mission_id=p.mission_id,
         payload={"package_id": pid, "package_type": p.package_type, "origin": p.origin_district, "destination": p.destination_district,
                  "route": route, "route_started_at": _iso(now), "eta": _iso(eta), "belt_speed": belt_speed(),
                  "opportunity_id": p.opportunity_id, "subject_type": p.subject_type, "subject_id": p.subject_id})
    return True


def _position_on_route(conn: Connection, p) -> tuple[int, float]:
    """Index of the segment the package is on now, and seconds elapsed."""
    lengths = {s["id"]: s["length"] for s in segments(conn)}
    elapsed = (_now() - _parse(p.route_started_at)).total_seconds()
    travelled = elapsed * belt_speed()
    for i, sid in enumerate(p.route):
        travelled -= lengths.get(sid, 0)
        if travelled < 0:
            return i, elapsed
    return len(p.route), elapsed


def tick(conn: Connection) -> dict:
    """Advance every package one step. Idempotent; safe to run from any number of scheduler wakeups."""
    moved = {"arrived": 0, "rerouted": 0, "failed": 0, "retried": 0}
    status_of = {s["id"]: s for s in segments(conn)}
    now = _now()
    for p in conn.execute(select(db.logistics_packages).where(db.logistics_packages.c.status == "IN_TRANSIT")).fetchall():
        idx, _ = _position_on_route(conn, p)
        ahead = p.route[idx + 1:] if idx < len(p.route) else []
        if any(status_of.get(sid, {}).get("status") != "UP" for sid in ahead):
            # finish the belt it is on, then find another way from that node
            node = status_of[p.route[idx]]["to_node"] if idx < len(p.route) else p.current_node
            conn.execute(update(db.logistics_packages).where(db.logistics_packages.c.id == p.id).values(current_node=node))
            if dispatch(conn, p.id):
                moved["rerouted"] += 1
            else:
                moved["failed"] += 1
            continue
        if p.eta and _parse(p.eta) <= now:
            _transition(conn, p, "ARRIVED", "package.arrived", {"district": p.destination_district},
                        delivered_at=_iso(now), current_node=f"{p.destination_district}:receiving")
            moved["arrived"] += 1
    for p in conn.execute(select(db.logistics_packages).where(db.logistics_packages.c.status == "DELIVERY_FAILED",
                                                              db.logistics_packages.c.next_attempt_at <= _iso(now))).fetchall():
        if dispatch(conn, p.id):
            moved["retried"] += 1
    return moved


def receive(conn: Connection, pid: str, agent_id: str | None = None) -> None:
    """The consuming department/manager takes the package off the belt."""
    p = _package(conn, pid)
    if p.status == "RECEIVED":
        return
    _transition(conn, p, "RECEIVED", "package.received", {"district": p.destination_district, "agent_id": agent_id})


def set_route_status(conn: Connection, route_id: str, status: str) -> None:
    if status not in ("UP", "DOWN"):
        raise ValueError("status must be UP or DOWN")
    conn.execute(update(db.logistics_routes).where(db.logistics_routes.c.id == route_id).values(status=status))
    emit(conn, "logistics.route_status_changed", payload={"route_id": route_id, "status": status})


def queue_depths(conn: Connection) -> dict[str, int]:
    rows = conn.execute(select(db.logistics_packages.c.destination_district, func.count())
                        .where(db.logistics_packages.c.status == "ARRIVED")
                        .group_by(db.logistics_packages.c.destination_district)).fetchall()
    return {r[0]: r[1] for r in rows}
