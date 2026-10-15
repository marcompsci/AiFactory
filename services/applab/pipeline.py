"""App Lab cycles: research → analysis → the General Manager's briefing → the owner → (only if approved) GitHub.

  RESEARCHING     Research Observatory: the researcher collects design patterns that people engage with, buy and play
                  Research Observatory ──design_insights──▶ Code Forge
  ANALYZING       Code Forge: the developer reads the repository (read-only) and drafts proposals
                  Code Forge ──lab_proposal──▶ Nexus Spire
  MANAGER_REVIEW  the General Manager checks every proposal against the rules and briefs the owner
                  Nexus Spire ──lab_proposal──▶ Owner's Tower
  AWAITING_OWNER  the owner approves (step-up, exact change), rejects or defers each proposal
  DONE            every proposal decided; approved ones were published as a draft PR or a Claude Code issue
  + FAILED, CANCELLED

The database is authoritative; a stage starts only when the backend marked the right package ARRIVED. Nothing here
writes to GitHub. Publishing is a separate `lab_publish` mission created by the owner's approval, and its tool
re-checks that approval at the tool boundary.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select, update
from sqlalchemy.engine import Connection

from services.core import db
from services.core.config import get_settings
from services.core.events import emit, transaction
from services.logistics import service as logistics
from services.management.hierarchy import agent_by_key, general_manager, submit_report
from services.management.pipeline import _greet, _mission, create_mission

from . import lab as L

log = logging.getLogger("aiciv.applab")

ACTIVE = ("RESEARCHING", "ANALYZING", "MANAGER_REVIEW")
OPEN_PROPOSAL = ("PROPOSED", "MANAGER_REVIEW", "AWAITING_OWNER", "APPROVED", "PUBLISHING")
DONE = ("COMPLETED", "FAILED", "CANCELLED")
SAFE_KEYS = {"cycle_id", "repository_id", "repo", "proposal_id", "from", "to", "label", "count", "kind", "url", "number", "state",
             "data_mode", "decision", "route", "title", "status", "merged"}
TRACK_EVERY_S = int(os.environ.get("AICIV_APPLAB_TRACK_SECONDS", "300"))


def lemit(conn: Connection, event_type: str, payload: dict, *, agent_id: str | None = None, mission_id: str | None = None,
          simulated: bool = False) -> dict:
    assert event_type.startswith("lab."), event_type
    return emit(conn, event_type, agent_id=agent_id, mission_id=mission_id, payload={k: v for k, v in payload.items() if k in SAFE_KEYS},
                execution_mode="simulation" if simulated else "live")


def data_mode() -> str:
    return "live" if get_settings().model_available else "simulated"


def cycle(conn: Connection, cid: str):
    return conn.execute(select(db.lab_cycles).where(db.lab_cycles.c.id == cid)).first()


def active_cycle(conn: Connection, repo_id: str):
    return conn.execute(select(db.lab_cycles).where(db.lab_cycles.c.repository_id == repo_id, db.lab_cycles.c.status.in_(ACTIVE))).first()


def set_status(conn: Connection, cid: str, target: str, label: str, agent_id: str | None = None, **values) -> None:
    c = cycle(conn, cid)
    if c.status == target:
        return
    if target in ("FAILED", "CANCELLED", "DONE"):
        values.setdefault("reason", label[:500])
    L.set_cycle(conn, cid, target, **values)
    L.record(conn, org=c.organization_id, actor_type="system", actor_id=None, action="lab.cycle_status_changed", subject_id=cid,
             detail={"from": c.status, "to": target, "reason": label[:300]})
    lemit(conn, "lab.cycle_status_changed", {"cycle_id": cid, "repository_id": c.repository_id, "from": c.status, "to": target,
                                             "label": label[:80], "data_mode": c.data_mode}, agent_id=agent_id, simulated=c.data_mode == "simulated")


def start_cycle(conn: Connection, *, repo_id: str, trigger: str, actor_id: str | None) -> str:
    repo = L.repo_row(conn, repo_id)
    if repo is None or repo.status != "ACTIVE":
        raise L.LabRefused("this repository is not authorized for the App Lab")
    if active_cycle(conn, repo_id):
        raise L.LabRefused("an App Lab cycle is already running for this repository")
    cid = db.new_id()
    mode = data_mode()
    conn.execute(db.lab_cycles.insert().values(id=cid, organization_id=repo.organization_id, repository_id=repo_id, status="RESEARCHING",
                                               trigger=trigger, data_mode=mode))
    L.record(conn, org=repo.organization_id, actor_type="owner" if trigger == "owner" else "system", actor_id=actor_id,
             action="lab.cycle_started", subject_id=cid, detail={"repo": repo.full_name, "trigger": trigger, "authorizes": "research and proposals only"})
    lemit(conn, "lab.cycle_status_changed", {"cycle_id": cid, "repository_id": repo_id, "repo": repo.full_name, "to": "RESEARCHING",
                                             "label": "App Lab cycle started", "data_mode": mode}, simulated=mode == "simulated")
    return cid


def cancel_cycle(conn: Connection, cid: str, *, actor_id: str) -> None:
    c = cycle(conn, cid)
    if c is None or c.status not in ACTIVE + ("AWAITING_OWNER",):
        raise L.LabRefused("cycle is not running")
    conn.execute(update(db.lab_proposals).where(db.lab_proposals.c.cycle_id == cid,
                                                db.lab_proposals.c.status.in_(("PROPOSED", "MANAGER_REVIEW", "AWAITING_OWNER")))
                 .values(status="WITHDRAWN", updated_at=db.utcnow()))
    set_status(conn, cid, "CANCELLED", "owner cancelled the cycle")


def _leg(conn: Connection, cid: str, origin: str, destination: str):
    return conn.execute(select(db.logistics_packages).where(db.logistics_packages.c.subject_id == cid,
                                                            db.logistics_packages.c.origin_district == origin,
                                                            db.logistics_packages.c.destination_district == destination)
                        .order_by(db.logistics_packages.c.created_at.desc())).first()


def _ship(conn: Connection, c, ptype: str, origin: str, destination: str, carrier) -> None:
    if _leg(conn, c.id, origin, destination) is None:
        logistics.create_package(conn, org_id=c.organization_id, package_type=ptype, origin=origin, destination=destination, priority=4,
                                 carrier_agent_id=carrier.id if carrier else None, subject_type="lab_cycle", subject_id=c.id)


def _arrived(conn: Connection, cid: str, origin: str, destination: str, receiver) -> bool:
    pkg = _leg(conn, cid, origin, destination)
    if pkg is None or pkg.status not in ("ARRIVED", "RECEIVED"):
        return False
    if pkg.status == "ARRIVED":
        if receiver is not None:
            _greet(conn, receiver, destination)
        logistics.receive(conn, pkg.id, receiver.id if receiver else None)
    return True


def _mission_for(conn: Connection, c, kind: str, title: str, created_by, **params) -> str:
    return create_mission(conn, org_id=c.organization_id, kind=kind, title=title,
                          prompt="App Lab: read the repository and propose improvements. Nothing is pushed without the owner's approval.",
                          params={"cycle_id": c.id, "repository_id": c.repository_id, **params}, opportunity_id=None, created_by=created_by.id)


def proposals(conn: Connection, cid: str):
    return conn.execute(select(db.lab_proposals).where(db.lab_proposals.c.cycle_id == cid).order_by(db.lab_proposals.c.created_at)).fetchall()


class AppLabPipeline:
    def __init__(self, enqueue: Callable[[str], None], gateway=None) -> None:
        self.enqueue = enqueue
        self.gateway = gateway

    def tick(self) -> dict:
        out = {"steps": 0, "tracked": 0, "autopilot": 0}
        with db.get_engine().connect() as conn:
            ids = [r.id for r in conn.execute(select(db.lab_cycles.c.id).where(db.lab_cycles.c.status.in_(ACTIVE + ("AWAITING_OWNER",))))]
        for cid in ids:
            try:
                out["steps"] += self.step(cid)
            except Exception:  # one cycle never stalls the others
                log.exception("App Lab step failed for %s", cid)
        try:
            out["publishing"] = self.settle_publishing()
            out["tracked"] = self.track()
            out["autopilot"] = self.autopilot()
        except Exception:
            log.exception("App Lab housekeeping failed")
        return out

    def step(self, cid: str) -> int:
        later: list[str] = []
        with transaction() as conn:
            c = cycle(conn, cid)
            fn = getattr(self, f"_{c.status.lower()}", None)
            acted = fn(conn, c, later) if fn else 0
        for item in later:
            if item.startswith("gm:"):
                self.manager_review(item[3:])
            else:
                self.enqueue(item)
        return acted or 0

    # ------------------------------------------------------------------ stages
    def _researching(self, conn, c, q) -> int:
        if c.research_mission_id is None:
            lead = agent_by_key(conn, "research_apps")
            mid = _mission_for(conn, c, "lab_research", "Research app designs people engage with, buy and play", lead)
            L.set_cycle(conn, c.id, "RESEARCHING", research_mission_id=mid)
            q.append(mid)
            return 1
        m = _mission(conn, c.research_mission_id)
        if m is None or m.status not in DONE:
            return 0
        if m.status != "COMPLETED":
            set_status(conn, c.id, "FAILED", f"research mission {m.status.lower()}: {m.failure_reason or ''}")
            return 1
        _ship(conn, c, "design_insights", "data-observatory", "code-forge", agent_by_key(conn, "research_apps"))
        dev = agent_by_key(conn, "developer")
        if not _arrived(conn, c.id, "data-observatory", "code-forge", dev):
            return 0
        mid = _mission_for(conn, c, "lab_analyze", "Read the repository and draft improvements", dev)
        set_status(conn, c.id, "ANALYZING", "design insights reached Code Forge", agent_id=dev.id, analysis_mission_id=mid)
        q.append(mid)
        return 1

    def _analyzing(self, conn, c, q) -> int:
        m = _mission(conn, c.analysis_mission_id)
        if m is None or m.status not in DONE:
            return 0
        if m.status != "COMPLETED":
            set_status(conn, c.id, "FAILED", f"analysis mission {m.status.lower()}: {m.failure_reason or ''}")
            return 1
        ps = proposals(conn, c.id)
        if not ps:
            set_status(conn, c.id, "DONE", "no applicable improvements found this cycle")
            return 1
        conn.execute(update(db.lab_proposals).where(db.lab_proposals.c.cycle_id == c.id, db.lab_proposals.c.status == "PROPOSED")
                     .values(status="MANAGER_REVIEW", updated_at=db.utcnow()))
        _ship(conn, c, "lab_proposal", "code-forge", "nexus-spire", agent_by_key(conn, "developer"))
        gm = general_manager(conn)
        if not _arrived(conn, c.id, "code-forge", "nexus-spire", gm):
            return 0
        set_status(conn, c.id, "MANAGER_REVIEW", "proposals reached the General Manager", agent_id=gm.id)
        q.append(f"gm:{c.id}")
        return 1

    def _manager_review(self, conn, c, q) -> int:
        ps = proposals(conn, c.id)
        if any(p.status == "MANAGER_REVIEW" for p in ps):
            q.append(f"gm:{c.id}")  # e.g. after a restart between receipt and review
            return 0
        _ship(conn, c, "lab_proposal", "nexus-spire", "owners-tower", general_manager(conn))
        if not _arrived(conn, c.id, "nexus-spire", "owners-tower", None):
            return 0
        waiting = sum(1 for p in ps if p.status == "AWAITING_OWNER")
        if not waiting:
            set_status(conn, c.id, "DONE", "the General Manager blocked every proposal; nothing for the owner to approve")
            return 1
        set_status(conn, c.id, "AWAITING_OWNER", "the General Manager's briefing reached the Owner's Tower")
        repo = L.repo_row(conn, c.repository_id)
        lemit(conn, "lab.proposals_ready", {"cycle_id": c.id, "repository_id": c.repository_id, "repo": repo.full_name, "count": waiting,
                                            "label": f"{waiting} App Lab proposal(s) for your review", "data_mode": c.data_mode},
              simulated=c.data_mode == "simulated")
        return 1

    def _awaiting_owner(self, conn, c, q) -> int:
        if any(p.status in OPEN_PROPOSAL for p in proposals(conn, c.id)):
            return 0
        set_status(conn, c.id, "DONE", "every proposal has been decided")
        return 1

    def manager_review(self, cid: str) -> None:
        """The General Manager checks each proposal against the rules and briefs the owner. It cannot approve."""
        with db.get_engine().connect() as conn:
            c = cycle(conn, cid)
            if c is None or c.status != "MANAGER_REVIEW":
                return
            repo = L.repo_row(conn, c.repository_id)
            pending = [p for p in proposals(conn, cid) if p.status == "MANAGER_REVIEW"]
            reviews = {p.id: L.gm_rules(p, repo) for p in pending}
            gm_model = general_manager(conn).model_name
        briefing, model = None, None
        if pending and self.gateway is not None and getattr(self.gateway, "available", False):
            from services.model_gateway.gateway import ModelRequest, ProviderError
            facts = [{"title": p.title, "route": p.route, "risk": p.risk, "review": reviews[p.id]["verdict"], "issues": reviews[p.id]["issues"]}
                     for p in pending]
            try:
                res = self.gateway.complete(ModelRequest(
                    system="You are the General Manager. You brief the owner on proposed code changes. You cannot approve or push anything.",
                    prompt="In at most four sentences, tell the owner what the App Lab wants to change and what you recommend, using only "
                           "these facts.\n<untrusted>" + str(facts) + "</untrusted>", max_tokens=220, model=gm_model), preferred_provider="anthropic")
                briefing, model = res.text.strip()[:900], res.model
            except ProviderError as exc:
                briefing = f"model unavailable ({exc.kind}); rules review stands"
        if briefing is None:
            ok = sum(1 for r in reviews.values() if r["verdict"] == "recommend")
            briefing = (("[simulation · templated text] " if c.data_mode == "simulated" else "")
                        + f"{ok} of {len(reviews)} proposal(s) passed my review for {repo.full_name}. Nothing reaches GitHub until you "
                          "approve the exact change; approved changes go to a separate branch as a draft pull request (or to Claude Code as "
                          "an issue), never to the default branch.")
        with transaction() as conn:
            c = cycle(conn, cid)
            if c.status != "MANAGER_REVIEW":
                return
            gm = general_manager(conn)
            for pid, r in reviews.items():
                p = conn.execute(select(db.lab_proposals).where(db.lab_proposals.c.id == pid)).first()
                if p.status != "MANAGER_REVIEW":
                    continue
                r = {**r, "briefing": briefing, "model": model, "reviewer": gm.key}
                conn.execute(update(db.lab_proposals).where(db.lab_proposals.c.id == pid).values(
                    gm_review=r, status="AWAITING_OWNER" if r["verdict"] == "recommend" else "FAILED", updated_at=db.utcnow()))
                L.record(conn, org=c.organization_id, actor_type="agent", actor_id=gm.id, action="lab.manager_review", subject_id=pid,
                         detail={"verdict": r["verdict"], "issues": r["issues"][:5], "authorizes_publish": False})
            submit_report(conn, org_id=c.organization_id, agent_id=gm.id, kind="completed_package",
                          body=f"App Lab briefing for {repo.full_name}: {briefing}"[:1000])

    # ------------------------------------------------------------------ after the owner's decision
    def settle_publishing(self) -> int:
        """A publish mission that ended without publishing leaves its proposal FAILED, with the reason (never retried
        silently: the owner can approve again)."""
        n = 0
        with transaction() as conn:
            rows = conn.execute(select(db.lab_proposals).where(db.lab_proposals.c.status.in_(("APPROVED", "PUBLISHING")))).fetchall()
            for p in rows:
                m = _mission(conn, p.publish_mission_id)
                if m is None or m.status not in DONE:
                    continue
                fresh = conn.execute(select(db.lab_proposals).where(db.lab_proposals.c.id == p.id)).first()
                if fresh.status in ("APPROVED", "PUBLISHING"):
                    reason = m.failure_reason or "publishing did not complete"
                    conn.execute(update(db.lab_proposals).where(db.lab_proposals.c.id == p.id).values(
                        status="FAILED", tracking={**(fresh.tracking or {}), "error": reason[:500]}, updated_at=db.utcnow()))
                    L.record(conn, org=p.organization_id, actor_type="system", actor_id=None, action="lab.publish_failed", subject_id=p.id,
                             detail={"reason": reason[:300]})
                    gm = general_manager(conn)
                    submit_report(conn, org_id=p.organization_id, agent_id=gm.id, kind="blocker",
                                  body=f"Publishing '{p.title}' failed: {reason}"[:1000])
                    n += 1
        return n

    def track(self) -> int:
        """Read-only status of the pull requests and issues the App Lab opened; the GM reports merges and closures."""
        now = datetime.now(timezone.utc)
        with db.get_engine().connect() as conn:
            rows = conn.execute(select(db.lab_proposals).where(db.lab_proposals.c.status == "PUBLISHED")).fetchall()
        n = 0
        for p in rows:
            t = p.tracking or {}
            if t.get("final") or (t.get("checked_at") and now - datetime.fromisoformat(t["checked_at"]) < timedelta(seconds=TRACK_EVERY_S)):
                continue
            pub = p.published or {}
            with db.get_engine().connect() as conn:
                repo = L.repo_row(conn, p.repository_id)
            try:
                st = L.publisher_for(repo).status(pub["kind"], int(pub["number"]))
            except Exception as exc:  # noqa: BLE001 — recorded, retried on the next window
                st = {"error": str(exc)[:200]}
            with transaction() as conn:
                final = bool(st.get("merged")) or st.get("state") == "closed"
                conn.execute(update(db.lab_proposals).where(db.lab_proposals.c.id == p.id).values(
                    tracking={**t, **st, "checked_at": now.isoformat(), "final": final}, updated_at=db.utcnow()))
                changed = (st.get("state"), st.get("merged")) != (t.get("state"), t.get("merged"))
                if changed and "error" not in st:
                    lemit(conn, "lab.change_status", {"proposal_id": p.id, "kind": pub["kind"], "number": pub["number"], "url": pub.get("url"),
                                                      "state": st.get("state"), "merged": st.get("merged"), "data_mode": p.data_mode},
                          simulated=p.data_mode == "simulated")
                    if final:
                        gm = general_manager(conn)
                        what = "was merged" if st.get("merged") else "was closed"
                        submit_report(conn, org_id=p.organization_id, agent_id=gm.id, kind="completed_package",
                                      body=f"App Lab change '{p.title}' {what} on GitHub ({pub.get('url')}).")
            n += 1
        return n

    def autopilot(self) -> int:
        """Starts research cycles on a schedule for repositories the owner put on autopilot. Publishing stays gated."""
        hours = float(os.environ.get("AICIV_APPLAB_AUTOPILOT_HOURS", "24"))
        now = datetime.now(timezone.utc)
        started = 0
        with transaction() as conn:
            for repo in conn.execute(select(db.lab_repositories).where(db.lab_repositories.c.status == "ACTIVE",
                                                                       db.lab_repositories.c.autopilot == 1)).fetchall():
                last = conn.execute(select(db.lab_cycles).where(db.lab_cycles.c.repository_id == repo.id)
                                    .order_by(db.lab_cycles.c.created_at.desc())).first()
                if last and (last.status in ACTIVE + ("AWAITING_OWNER",)
                             or now - datetime.fromisoformat(last.created_at.replace("Z", "+00:00")) < timedelta(hours=hours)):
                    continue
                start_cycle(conn, repo_id=repo.id, trigger="autopilot", actor_id=None)
                started += 1
        return started
