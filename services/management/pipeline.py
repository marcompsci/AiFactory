"""The OpportunityPacket workflow, advanced by durable scheduled ticks and event pokes.

RESEARCHED -> MANAGER_REVIEW -> ROUTED -> DEPARTMENT_ACCEPTED -> IN_PRODUCTION -> QUALITY_REVIEW
           -> MANAGER_APPROVAL -> OWNER_APPROVAL -> RELEASE_AUTHORIZED
(+ REVISION_REQUESTED, REJECTED, DEFERRED, CANCELLED)

Every step reads the database, does at most one thing, and writes its result, so a tick can be repeated or
interrupted at any point. Handoffs between buildings are physical: a stage only starts when the backend has
marked the right package ARRIVED at that building's receiving terminal.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from sqlalchemy import insert, select, update

from services.core import db
from services.core.config import get_settings
from services.core.events import emit, transaction
from services.logistics import service as logistics
from services.orchestrator import ops
from services.studio import bundle as bundles

from .hierarchy import agent_by_key, general_manager, submit_report
from .manager import model_review_opportunity, record_decision, review_opportunity, set_opportunity_status
from .release import current_review, latest_bundle, manager_release_review

log = logging.getLogger("aiciv.pipeline")
MAX_REVISIONS = 2
ACTIVE = ("RESEARCHED", "MANAGER_REVIEW", "ROUTED", "DEPARTMENT_ACCEPTED", "IN_PRODUCTION", "QUALITY_REVIEW",
          "MANAGER_APPROVAL", "OWNER_APPROVAL", "RELEASE_AUTHORIZED", "REVISION_REQUESTED")


def create_mission(conn, *, org_id: str, kind: str, title: str, prompt: str, params: dict, opportunity_id: str, created_by: str) -> str:
    seed_project = conn.execute(select(db.projects.c.id)).scalar()
    mid = db.new_id()
    mode = "live" if get_settings().model_available else "simulation"
    conn.execute(insert(db.missions).values(id=mid, organization_id=org_id, project_id=seed_project, repository_id=None, title=title[:120],
                                            prompt=prompt, status="CREATED", execution_mode=mode, budget_usd=get_settings().default_mission_budget_usd,
                                            spent_usd_estimated=0.0, created_by=created_by, paused=0, kind=kind, opportunity_id=opportunity_id,
                                            params=params))
    emit(conn, "mission.created", mission_id=mid, execution_mode=mode,
         payload={"title": title, "prompt": prompt, "kind": kind, "opportunity_id": opportunity_id, "execution_mode": mode})
    return mid


def _pkg(conn, opp_id: str, ptype: str, mission_id: str | None = None):
    q = select(db.logistics_packages).where(db.logistics_packages.c.opportunity_id == opp_id, db.logistics_packages.c.package_type == ptype)
    if mission_id:
        q = q.where(db.logistics_packages.c.mission_id == mission_id)
    return conn.execute(q.order_by(db.logistics_packages.c.created_at.desc())).first()


def _mission(conn, mid: str | None):
    return conn.execute(select(db.missions).where(db.missions.c.id == mid)).first() if mid else None


def _greet(conn, agent, district: str) -> None:
    """The receiving agent walks to its building's receiving terminal (animation only; state is already decided)."""
    if ops.request_move(conn, agent.id, district, f"{district}:receiving", None, "live"):
        ops.arrive(conn, agent.id, district, f"{district}:receiving", None, "live")


class Pipeline:
    def __init__(self, enqueue: Callable[[str], None], gateway=None) -> None:
        self.enqueue = enqueue
        self.gateway = gateway

    def tick(self) -> int:
        with db.get_engine().connect() as conn:
            ids = [r.id for r in conn.execute(select(db.opportunities.c.id).where(db.opportunities.c.status.in_(ACTIVE)))]
        steps = 0
        for oid in ids:
            try:
                steps += self.step(oid)
            except Exception:  # one bad packet never stalls the others; it will be retried next tick
                log.exception("pipeline step failed for %s", oid)
        return steps

    def step(self, oid: str) -> int:
        to_enqueue: list[str] = []
        acted = 0
        with transaction() as conn:
            o = conn.execute(select(db.opportunities).where(db.opportunities.c.id == oid)).first()
            gm = general_manager(conn)
            fn = getattr(self, f"_{o.status.lower()}", None)
            if fn:
                acted = fn(conn, o, gm, to_enqueue) or 0
        for item in to_enqueue:
            if item.startswith("review:"):
                manager_release_review(transaction, item.split(":", 1)[1], self.gateway)  # may call Opus: outside the txn
            elif item.startswith("oppreview:"):
                self.opportunity_review(item.split(":", 1)[1])
            else:
                self.enqueue(item)
        return acted

    # ------------------------------------------------------------------ stages
    def _researched(self, conn, o, gm, q) -> int:
        pkg = _pkg(conn, o.id, "research_brief")
        if pkg is None:
            m = _mission(conn, o.research_mission_id)
            if m is not None and m.status not in ("COMPLETED", "FAILED", "CANCELLED"):
                return 0  # the researcher is still carrying the brief to the dispatch terminal
            # recovery: the research mission ended without dispatching the brief
            logistics.create_package(conn, org_id=o.organization_id, package_type="research_brief", origin="data-observatory",
                                     destination="nexus-spire", opportunity_id=o.id, artifact_references=o.artifact_references)
            return 1
        if pkg.status != "ARRIVED":
            return 0
        _greet(conn, gm, "nexus-spire")
        logistics.receive(conn, pkg.id, gm.id)
        set_opportunity_status(conn, o.id, "MANAGER_REVIEW", "research brief received by the General Manager", gm.id)
        emit(conn, "manager.review_started", agent_id=gm.id, payload={"opportunity_id": o.id, "subject": "research_brief"})
        q.append(f"oppreview:{o.id}")
        return 1

    def _manager_review(self, conn, o, gm, q) -> int:
        prior = conn.execute(select(db.manager_decisions).where(db.manager_decisions.c.subject_id == o.id,
                                                                db.manager_decisions.c.decision_type == "opportunity_review")
                             .order_by(db.manager_decisions.c.created_at.desc())).first()
        if prior and prior.outcome == "escalate":
            committed = conn.execute(select(db.manager_decisions.c.id).where(db.manager_decisions.c.subject_id == o.id,
                                                                             db.manager_decisions.c.outcome == "owner_committed")).first()
            return self._route(conn, o, gm, "owner committed the spend") if committed else 0
        if prior and prior.created_at >= (o.updated_at or ""):
            return 0
        q.append(f"oppreview:{o.id}")  # first review, or a reopened packet
        return 1

    def opportunity_review(self, oid: str) -> None:
        """Rules first (read-only), optional Opus second opinion with no transaction open, then one write."""
        with db.get_engine().connect() as conn:
            o = conn.execute(select(db.opportunities).where(db.opportunities.c.id == oid)).first()
            if o is None or o.status != "MANAGER_REVIEW":
                return
            prior = conn.execute(select(db.manager_decisions.c.created_at).where(db.manager_decisions.c.subject_id == oid,
                                                                                 db.manager_decisions.c.decision_type == "opportunity_review")
                                 .order_by(db.manager_decisions.c.created_at.desc())).first()
            if prior and prior.created_at >= (o.updated_at or ""):
                return
            outcome, rationale, method, model = review_opportunity(conn, o, self.gateway)
        if outcome == "route":
            veto, note, m = model_review_opportunity(o, self.gateway)
            if m:
                method, model = "model", m
                rationale += f" Opus: {note}" if note else ""
                if veto:
                    outcome = "reject"
        with transaction() as conn:
            o = conn.execute(select(db.opportunities).where(db.opportunities.c.id == oid)).first()
            if o.status != "MANAGER_REVIEW":
                return
            gm = general_manager(conn)
            record_decision(conn, decision_type="opportunity_review", subject_type="opportunity", subject_id=o.id, outcome=outcome,
                            rationale=rationale, method=method, model=model,
                            inputs={"score": o.opportunity_score, "confidence": o.confidence, "risk_flags": o.risk_flags},
                            event="manager.review_completed")
            if outcome == "reject":
                set_opportunity_status(conn, o.id, "REJECTED", rationale, gm.id)
            elif outcome == "escalate":
                emit(conn, "manager.escalation_created", agent_id=gm.id, payload={"opportunity_id": o.id, "reason": rationale, "needs": "owner"})
            else:
                self._route(conn, o, gm, rationale)

    def _route(self, conn, o, gm, why: str) -> int:
        dept = conn.execute(select(db.departments).where(db.departments.c.key == o.proposed_department)).first()
        record_decision(conn, decision_type="routing", subject_type="opportunity", subject_id=o.id, outcome=f"route:{dept.key}",
                        rationale=f"Routed to {dept.name} in {dept.district}. {why}"[:1000])
        set_opportunity_status(conn, o.id, "ROUTED", f"routed to {dept.name}", gm.id)
        logistics.create_package(conn, org_id=o.organization_id, package_type="product_proposal", origin="nexus-spire", destination=dept.district,
                                 opportunity_id=o.id, artifact_references=o.artifact_references, priority=4, carrier_agent_id=gm.id)
        return 1

    def _routed(self, conn, o, gm, q) -> int:
        pkg = _pkg(conn, o.id, "product_proposal")
        if not pkg or pkg.status != "ARRIVED":
            return 0
        dept = conn.execute(select(db.departments).where(db.departments.c.key == o.proposed_department)).first()
        sup = conn.execute(select(db.agents).where(db.agents.c.id == dept.supervisor_agent_id)).first()
        busy = conn.execute(select(db.opportunities.c.id).where(db.opportunities.c.proposed_department == dept.key,
                                                                db.opportunities.c.status.in_(["DEPARTMENT_ACCEPTED", "IN_PRODUCTION"]),
                                                                db.opportunities.c.id != o.id)).fetchall()
        if len(busy) >= dept.max_concurrent_missions:
            return 0  # waits on the belt; supervisor accepts when capacity frees up
        _greet(conn, sup, dept.district)
        logistics.receive(conn, pkg.id, sup.id)
        record_decision(conn, decision_type="acceptance", subject_type="opportunity", subject_id=o.id, outcome="accepted",
                        rationale=f"{sup.name} accepted for {dept.name}: capacity available, template exists for the spec.",
                        manager_agent_id=sup.id)
        set_opportunity_status(conn, o.id, "DEPARTMENT_ACCEPTED", f"{dept.name} accepted", sup.id)
        return 1 + self._start_production(conn, o, gm, q)

    def _department_accepted(self, conn, o, gm, q) -> int:
        return self._start_production(conn, o, gm, q)

    def _start_production(self, conn, o, gm, q) -> int:
        spec = o.spec or {}
        mid = create_mission(conn, org_id=o.organization_id, kind="build_prototype", title=f"Build {spec.get('app_name', o.title)}",
                             prompt=f"Build the prototype for '{o.title}' exactly as specified: {spec.get('acceptance')}",
                             params={"revision": o.revision_count}, opportunity_id=o.id, created_by=gm.id)
        conn.execute(update(db.opportunities).where(db.opportunities.c.id == o.id).values(production_mission_id=mid))
        emit(conn, "manager.goal_assigned", agent_id=gm.id, mission_id=mid,
             payload={"opportunity_id": o.id, "department": o.proposed_department, "goal": spec.get("acceptance", []),
                      "measurable": ["all spec features present", "QA tests pass on the exact bundle", "manager checklist has no failures"]})
        set_opportunity_status(conn, o.id, "IN_PRODUCTION", "production mission started", gm.id)
        q.append(mid)
        return 1

    def _in_production(self, conn, o, gm, q) -> int:
        m = _mission(conn, o.production_mission_id)
        if m is None or m.status not in ("COMPLETED", "FAILED", "CANCELLED"):
            return 0
        if m.status != "COMPLETED":
            return self._revise(conn, o, gm, q, f"production mission {m.status.lower()}: {m.failure_reason or ''}", origin="code-forge", ship=False)
        pkg = _pkg(conn, o.id, "code_artifact", mission_id=m.id)
        if pkg is None:
            art = latest_bundle(conn, o.id)
            dev = agent_by_key(conn, "developer")
            logistics.create_package(conn, org_id=o.organization_id, package_type="code_artifact", origin="code-forge",
                                     destination="sentinel-citadel", opportunity_id=o.id, mission_id=m.id,
                                     artifact_references=[art.id] if art else [], priority=3, carrier_agent_id=dev.id)
            return 1
        if pkg.status != "ARRIVED":
            return 0
        qa = agent_by_key(conn, "qa")
        _greet(conn, qa, "sentinel-citadel")
        logistics.receive(conn, pkg.id, qa.id)
        art = latest_bundle(conn, o.id)
        mid = create_mission(conn, org_id=o.organization_id, kind="qa_prototype", title=f"QA {(o.spec or {}).get('app_name', o.title)}",
                             prompt="Run the automated tests against the exact release bundle.", params={"artifact_id": art.id},
                             opportunity_id=o.id, created_by=gm.id)
        conn.execute(update(db.opportunities).where(db.opportunities.c.id == o.id).values(qa_mission_id=mid))
        set_opportunity_status(conn, o.id, "QUALITY_REVIEW", "QA received the code artifact", qa.id)
        q.append(mid)
        return 1

    def _quality_review(self, conn, o, gm, q) -> int:
        m = _mission(conn, o.qa_mission_id)
        if m is None or m.status not in ("COMPLETED", "FAILED", "CANCELLED"):
            return 0
        out = conn.execute(select(db.tasks.c.outputs).where(db.tasks.c.mission_id == m.id, db.tasks.c.key == "qa_verify")).scalar() or {}
        if m.status != "COMPLETED" or out.get("failed", 1) or out.get("errors", 1) or not out.get("passed"):
            return self._revise(conn, o, gm, q, f"QA: {out.get('summary_line') or m.failure_reason or 'did not complete'}", origin="sentinel-citadel")
        pkg = _pkg(conn, o.id, "test_report", mission_id=m.id)
        if pkg is None:
            logistics.create_package(conn, org_id=o.organization_id, package_type="test_report", origin="sentinel-citadel", destination="nexus-spire",
                                     opportunity_id=o.id, mission_id=m.id, artifact_references=[out.get("report_artifact_id"), out.get("artifact_id")],
                                     priority=3, carrier_agent_id=agent_by_key(conn, "qa").id)
            return 1
        if pkg.status != "ARRIVED":
            return 0
        _greet(conn, gm, "nexus-spire")
        logistics.receive(conn, pkg.id, gm.id)
        set_opportunity_status(conn, o.id, "MANAGER_APPROVAL", "verified results received for manager review", gm.id)
        return 1  # the review itself runs in _manager_approval (outside this transaction, it may call Opus)

    def _manager_approval(self, conn, o, gm, q) -> int:
        art = latest_bundle(conn, o.id)
        if art is None or bundles.digest(Path(art.storage_path)) != art.digest:
            # the bytes on disk are not what was built and tested: never re-approve them, rebuild instead
            return self._revise(conn, o, gm, q, "stored bundle does not match its recorded digest; rebuilding", origin="nexus-spire")
        review = current_review(conn, o.id)
        if review is None or review.artifact_id != art.id or review.artifact_digest != art.digest:
            q.append(f"review:{o.id}")  # a rebuilt bundle always gets a renewed review, even if its bytes are identical  # run after commit
            return 1
        if review.verdict == "APPROVED_FOR_OWNER_REVIEW":
            if _pkg(conn, o.id, "release_package") and _pkg(conn, o.id, "release_package").artifact_references == [art.id]:
                set_opportunity_status(conn, o.id, "OWNER_APPROVAL", "release package already with the owner", gm.id)
                return 1
            emit(conn, "release.manager_approved", agent_id=gm.id,
                 payload={"opportunity_id": o.id, "review_id": review.id, "artifact_id": art.id, "artifact_digest": art.digest})
            logistics.create_package(conn, org_id=o.organization_id, package_type="release_package", origin="nexus-spire", destination="owners-tower",
                                     opportunity_id=o.id, artifact_references=[art.id], priority=2, carrier_agent_id=gm.id)
            set_opportunity_status(conn, o.id, "OWNER_APPROVAL", "manager approved for owner review; release package dispatched", gm.id)
            return 1
        if review.verdict == "CHANGES_REQUESTED":
            return self._revise(conn, o, gm, q, f"manager review requested changes: {review.summary}", origin="nexus-spire")
        if review.verdict == "REJECTED":
            set_opportunity_status(conn, o.id, "REJECTED", review.summary, gm.id)
            return 1
        # BLOCKED: escalate once and wait for the owner
        if not conn.execute(select(db.manager_decisions.c.id).where(db.manager_decisions.c.subject_id == o.id,
                                                                    db.manager_decisions.c.decision_type == "escalation",
                                                                    db.manager_decisions.c.inputs["review_id"].as_string() == review.id)).first():
            record_decision(conn, decision_type="escalation", subject_type="opportunity", subject_id=o.id, outcome="blocked",
                            rationale=f"Release blocked by security/privacy findings: {review.summary}", inputs={"review_id": review.id},
                            event="manager.escalation_created")
            return 1
        return 0

    def _owner_approval(self, conn, o, gm, q) -> int:
        pkg = _pkg(conn, o.id, "release_package")
        if pkg and pkg.status == "ARRIVED":
            logistics.receive(conn, pkg.id, None)
            art = latest_bundle(conn, o.id)
            emit(conn, "release.owner_approval_requested",
                 payload={"opportunity_id": o.id, "artifact_id": art.id, "artifact_digest": art.digest, "title": o.title})
            return 1
        return 0

    def _release_authorized(self, conn, o, gm, q) -> int:
        if o.release_mission_id:
            return 0
        auth = conn.execute(select(db.release_authorizations).where(db.release_authorizations.c.opportunity_id == o.id)
                            .order_by(db.release_authorizations.c.created_at.desc())).first()
        mid = create_mission(conn, org_id=o.organization_id, kind="release", title=f"Release {(o.spec or {}).get('app_name', o.title)}",
                             prompt="Release the owner-approved bundle to the local release channel.",
                             params={"authorization_id": auth.id}, opportunity_id=o.id, created_by=gm.id)
        conn.execute(update(db.opportunities).where(db.opportunities.c.id == o.id).values(release_mission_id=mid))
        q.append(mid)
        return 1

    def _revision_requested(self, conn, o, gm, q) -> int:
        pkg = _pkg(conn, o.id, "revision_request")
        if pkg and pkg.status not in ("ARRIVED", "RECEIVED"):
            return 0
        if pkg and pkg.status == "ARRIVED":
            logistics.receive(conn, pkg.id, agent_by_key(conn, "architect").id)
        if o.revision_count > MAX_REVISIONS:
            set_opportunity_status(conn, o.id, "REJECTED", f"still failing after {MAX_REVISIONS} revisions", gm.id)
            return 1
        return self._start_production(conn, o, gm, q)

    def _revise(self, conn, o, gm, q, why: str, origin: str, ship: bool = True) -> int:
        conn.execute(update(db.opportunities).where(db.opportunities.c.id == o.id).values(revision_count=o.revision_count + 1))
        record_decision(conn, decision_type="revision_request", subject_type="opportunity", subject_id=o.id, outcome="revise",
                        rationale=f"Sent back to App Studio (revision {o.revision_count + 1}): {why}"[:1000],
                        event="manager.revision_requested")
        set_opportunity_status(conn, o.id, "REVISION_REQUESTED", why[:300], gm.id)
        if ship and origin != "code-forge":
            logistics.create_package(conn, org_id=o.organization_id, package_type="revision_request", origin=origin, destination="code-forge",
                                     opportunity_id=o.id, priority=3, carrier_agent_id=gm.id)
        submit_report(conn, org_id=o.organization_id, agent_id=gm.id, kind="quality_concern", body=f"Revision requested for {o.title}: {why}"[:500])
        return 1

