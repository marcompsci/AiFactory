"""V4 endpoints: research, opportunities, hierarchy, logistics, Owner's Tower."""
from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from services.core import db
from services.core.auth import Principal, authenticate, mutation_limiter
from services.core.config import get_settings
from services.core.events import emit, transaction
from services.logistics import service as logistics
from services.management.hierarchy import general_manager
from services.management.manager import record_decision, set_opportunity_status
from services.management.pipeline import create_mission
from services.management.release import ReleaseDenied, current_review, latest_bundle, owner_decide
from services.studio import bundle as bundles

router = APIRouter(prefix="/api")


def principal(request: Request) -> Principal:
    return authenticate(request)


def operator(request: Request) -> Principal:
    p = authenticate(request)
    p.require("operator")
    mutation_limiter.check(p.user_id)
    return p


def _admin(request: Request) -> Principal:
    p = authenticate(request)
    p.require("admin")
    mutation_limiter.check(p.user_id)
    return p


def owner(request: Request) -> Principal:
    p = authenticate(request)
    p.require("owner")  # release and strategic decisions are the owner's alone
    mutation_limiter.check(p.user_id)
    return p


def _state():
    from services.api.main import state
    return state


def _rows(rows) -> list[dict]:
    return [dict(r._mapping) for r in rows]


# ------------------------------------------------------------------ research
class ResearchIn(BaseModel):
    source: str = Field(pattern="^(apple_charts|etsy|depop|app_store_connect)$")
    query: str = Field(min_length=2, max_length=80)
    region: str = Field(default="US", pattern="^[A-Za-z]{2}$")


@router.post("/research", status_code=201)
def start_research(body: ResearchIn, p: Principal = Depends(operator)):
    agent_key = "research_apps" if body.source in ("apple_charts", "app_store_connect") else "research_marketplaces"
    with transaction() as conn:
        if conn.execute(select(db.organizations.c.emergency_stopped).where(db.organizations.c.id == p.organization_id)).scalar():
            raise HTTPException(409, "emergency stop is engaged")
        gm = general_manager(conn)
        mid = create_mission(conn, org_id=p.organization_id, kind="market_research", title=f"Research '{body.query}' on {body.source.replace('_', ' ')}",
                             prompt=f"Find a validated app opportunity for '{body.query}' using permitted {body.source} data ({body.region}).",
                             params={"source": body.source, "query": body.query, "region": body.region.upper(), "agent_key": agent_key},
                             opportunity_id=None, created_by=p.user_id)
        record_decision(conn, decision_type="goal_assignment", subject_type="mission", subject_id=mid, outcome=f"assigned:{agent_key}",
                        rationale=f"Owner objective → measurable goal: cited findings from {body.source} and a scored packet if the score clears 0.45.",
                        manager_agent_id=gm.id, event="manager.goal_assigned")
    _state().worker.enqueue(mid)
    return {"mission_id": mid, "agent": agent_key}


@router.get("/opportunities")
def list_opportunities(p: Principal = Depends(principal)):
    with db.get_engine().connect() as conn:
        return {"opportunities": _rows(conn.execute(select(db.opportunities).where(db.opportunities.c.organization_id == p.organization_id)
                                                    .order_by(db.opportunities.c.created_at.desc()).limit(50)))}


@router.get("/opportunities/{oid}")
def opportunity_dossier(oid: str, p: Principal = Depends(principal)):
    """Everything the owner needs in the Owner's Tower, in one read."""
    with db.get_engine().connect() as conn:
        o = conn.execute(select(db.opportunities).where(db.opportunities.c.id == oid)).first()
        if o is None or o.organization_id != p.organization_id:
            raise HTTPException(404, "opportunity not found")
        scores = _rows(conn.execute(select(db.opportunity_scores).where(db.opportunity_scores.c.opportunity_id == oid)))
        finding_ids = [e["finding_id"] for e in o.evidence or []]
        findings = _rows(conn.execute(select(db.research_findings).where(db.research_findings.c.id.in_(finding_ids)))) if finding_ids else []
        decisions = _rows(conn.execute(select(db.manager_decisions).where(db.manager_decisions.c.subject_id.in_(
            [oid] + [m for m in (o.production_mission_id, o.qa_mission_id, o.release_mission_id) if m])).order_by(db.manager_decisions.c.created_at)))
        review = current_review(conn, oid)
        checklist = _rows(conn.execute(select(db.review_checklists).where(db.review_checklists.c.review_id == review.id))) if review else []
        art = latest_bundle(conn, oid)
        artifacts = _rows(conn.execute(select(db.artifacts.c.id, db.artifacts.c.kind, db.artifacts.c.title, db.artifacts.c.digest,
                                              db.artifacts.c.created_at).where(db.artifacts.c.opportunity_id == oid)))
        mission_ids = [m for m in (o.research_mission_id, o.production_mission_id, o.qa_mission_id, o.release_mission_id) if m]
        test_report = None
        if o.qa_mission_id:
            out = conn.execute(select(db.tasks.c.outputs).where(db.tasks.c.mission_id == o.qa_mission_id, db.tasks.c.key == "qa_verify")).scalar()
            test_report = out
        spend = conn.execute(select(func.coalesce(func.sum(db.missions.c.spent_usd_estimated), 0.0)).where(db.missions.c.id.in_(mission_ids))).scalar() if mission_ids else 0.0
        packages = _rows(conn.execute(select(db.logistics_packages).where(db.logistics_packages.c.opportunity_id == oid).order_by(db.logistics_packages.c.created_at)))
        owner_decisions = _rows(conn.execute(select(db.owner_decisions).where(db.owner_decisions.c.opportunity_id == oid).order_by(db.owner_decisions.c.created_at)))
        auths = _rows(conn.execute(select(db.release_authorizations).where(db.release_authorizations.c.opportunity_id == oid)))
        for a in auths:
            a["invalidated"] = bool(conn.execute(select(db.release_invalidations.c.id).where(db.release_invalidations.c.authorization_id == a["id"])).first())
        executions = _rows(conn.execute(select(db.release_executions).where(db.release_executions.c.authorization_id.in_([a["id"] for a in auths])))) if auths else []
    release_pkg = next((x for x in reversed(packages) if x["package_type"] == "release_package"), None)
    return {
        "opportunity": dict(o._mapping), "scores": scores, "findings": findings, "decisions": decisions,
        "manager_review": dict(review._mapping) if review else None, "checklist": checklist,
        "bundle": {"artifact_id": art.id, "digest": art.digest, "title": art.title} if art else None,
        "artifacts": artifacts, "test_report": test_report, "estimated_spend_usd": round(float(spend or 0), 6),
        "packages": packages, "owner_decisions": owner_decisions, "authorizations": auths, "releases": executions,
        "awaiting_owner": o.status == "OWNER_APPROVAL" and bool(release_pkg and release_pkg["status"] in ("ARRIVED", "RECEIVED")),
        "risks": list(o.risk_flags or []) + [c["evidence"] for c in checklist if c["status"] in ("warn", "fail")],
    }


class OwnerDecisionIn(BaseModel):
    decision: str = Field(pattern="^(APPROVE|REQUEST_CHANGES|REJECT|DEFER)$")
    artifact_digest: str = Field(min_length=64, max_length=64)
    note: str | None = Field(default=None, max_length=1000)


@router.post("/opportunities/{oid}/owner-decision")
def decide(oid: str, body: OwnerDecisionIn, p: Principal = Depends(owner)):
    try:
        with transaction() as conn:
            out = owner_decide(conn, opp_id=oid, decision=body.decision, artifact_digest=body.artifact_digest, note=body.note, owner_id=p.user_id)
    except ReleaseDenied as exc:
        raise HTTPException(409, str(exc)) from exc
    _state().scheduler.poke()
    return out


class CommitIn(BaseModel):
    approve: bool


@router.post("/opportunities/{oid}/owner-commit")
def owner_commit(oid: str, body: CommitIn, p: Principal = Depends(owner)):
    """Owner's answer to a GM escalation for spending beyond the GM's delegated limit."""
    with transaction() as conn:
        o = conn.execute(select(db.opportunities).where(db.opportunities.c.id == oid)).first()
        if o is None or o.status != "MANAGER_REVIEW":
            raise HTTPException(409, "nothing is escalated for this opportunity")
        record_decision(conn, decision_type="milestone_approval", subject_type="opportunity", subject_id=oid,
                        outcome="owner_committed" if body.approve else "owner_declined",
                        rationale="Owner decision on an escalated commitment.", inputs={"by": p.user_id})
        if not body.approve:
            set_opportunity_status(conn, oid, "REJECTED", "owner declined the commitment")
    _state().scheduler.poke()
    return {"ok": True}


@router.post("/opportunities/{oid}/cancel")
def cancel_opportunity(oid: str, p: Principal = Depends(operator)):
    with transaction() as conn:
        o = conn.execute(select(db.opportunities).where(db.opportunities.c.id == oid)).first()
        if o is None:
            raise HTTPException(404, "opportunity not found")
        set_opportunity_status(conn, oid, "CANCELLED", "cancelled by operator")
    return {"ok": True}


@router.post("/opportunities/{oid}/reopen")
def reopen(oid: str, p: Principal = Depends(owner)):
    """Retry path: a rejected packet goes back to manager review; a deferred one back to the owner."""
    with transaction() as conn:
        o = conn.execute(select(db.opportunities).where(db.opportunities.c.id == oid)).first()
        if o is None or o.status not in ("REJECTED", "DEFERRED"):
            raise HTTPException(409, "only rejected or deferred items can be reopened")
        set_opportunity_status(conn, oid, "MANAGER_REVIEW" if o.status == "REJECTED" else "OWNER_APPROVAL", "reopened by the owner")
    _state().scheduler.poke()
    return {"ok": True}


# ------------------------------------------------------------------ artifacts: bundle preview and download
@router.get("/artifacts/{aid}/files/{path:path}")
def bundle_file(aid: str, path: str, p: Principal = Depends(principal)):
    with db.get_engine().connect() as conn:
        a = conn.execute(select(db.artifacts).where(db.artifacts.c.id == aid, db.artifacts.c.kind == "release_bundle")).first()
    if a is None or a.organization_id != p.organization_id:
        raise HTTPException(404, "bundle not found")
    try:
        data = bundles.read_member(Path(a.storage_path), path)
    except KeyError as exc:
        raise HTTPException(404, "no such file in bundle") from exc
    ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    # Previews render sandboxed: scripts may run inside the frame but cannot reach the network or the parent.
    return Response(data, media_type=ctype, headers={
        "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; manifest-src 'self'; sandbox allow-scripts",
        "X-Content-Type-Options": "nosniff"})


@router.get("/artifacts/{aid}/download")
def bundle_download(aid: str, p: Principal = Depends(principal)):
    with db.get_engine().connect() as conn:
        a = conn.execute(select(db.artifacts).where(db.artifacts.c.id == aid, db.artifacts.c.kind == "release_bundle")).first()
    if a is None or a.organization_id != p.organization_id:
        raise HTTPException(404, "bundle not found")
    return Response(Path(a.storage_path).read_bytes(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="bundle-{a.digest[:12]}.zip"', "X-Bundle-SHA256": a.digest})


# ------------------------------------------------------------------ hierarchy and logistics
@router.get("/hierarchy")
def hierarchy(p: Principal = Depends(principal)):
    with db.get_engine().connect() as conn:
        return {
            "departments": _rows(conn.execute(select(db.departments).where(db.departments.c.organization_id == p.organization_id))),
            "reporting_lines": _rows(conn.execute(select(db.agent_reporting_lines))),
            "reports": _rows(conn.execute(select(db.agent_reports).order_by(db.agent_reports.c.created_at.desc()).limit(60))),
            "decisions": _rows(conn.execute(select(db.manager_decisions).order_by(db.manager_decisions.c.created_at.desc()).limit(60))),
            "checkpoints": _rows(conn.execute(select(db.goal_checkpoints).order_by(db.goal_checkpoints.c.created_at.desc()).limit(20))),
            "jobs": _rows(conn.execute(select(db.scheduled_jobs))),
        }


@router.get("/logistics")
def logistics_state(p: Principal = Depends(principal)):
    with db.get_engine().connect() as conn:
        load = logistics.load_by_segment(conn)
        routes = _rows(conn.execute(select(db.logistics_routes)))
        for r in routes:
            r["load"] = load.get(r["id"], 0)
        return {"nodes": _rows(conn.execute(select(db.logistics_nodes))), "routes": routes,
                "packages": _rows(conn.execute(select(db.logistics_packages).where(db.logistics_packages.c.status.in_(
                    ["QUEUED", "IN_TRANSIT", "ARRIVED", "DELIVERY_FAILED"])).order_by(db.logistics_packages.c.created_at.desc()).limit(100))),
                "queues": logistics.queue_depths(conn), "belt_speed": logistics.belt_speed(), "server_time": db.utcnow()}


class RouteStatusIn(BaseModel):
    status: str = Field(pattern="^(UP|DOWN)$")


@router.post("/logistics/routes/{rid:path}/status")
def route_status(rid: str, body: RouteStatusIn, p: Principal = Depends(_admin)):
    with transaction() as conn:
        if not conn.execute(select(db.logistics_routes.c.id).where(db.logistics_routes.c.id == rid)).first():
            raise HTTPException(404, "no such belt")
        logistics.set_route_status(conn, rid, body.status)
    _state().scheduler.poke()
    return {"ok": True}
