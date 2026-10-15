"""App Lab endpoints. Members can read; only the owner can connect a repository, start or cancel cycles, and decide
proposals. Connecting a repository and approving a change both need step-up (header `X-Step-Up`, from
/api/finance/stepup/verify with purpose `lab-connect` or `lab:<proposal id>`). See docs/APP_LAB.md."""
from __future__ import annotations

import os
import re

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from services.applab import lab as L
from services.applab import pipeline as LP
from services.core import db
from services.core.auth import Principal, authenticate, mutation_limiter
from services.core.events import transaction
from services.finance import crypto, stepup
from services.finance.permissions import require_owner
from services.management.hierarchy import agent_by_key
from services.management.pipeline import create_mission

router = APIRouter(prefix="/api/applab")
REPO_RX = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def member(request: Request) -> Principal:
    return authenticate(request)


def owner(request: Request) -> Principal:
    p = authenticate(request)
    require_owner(p)
    mutation_limiter.check(p.user_id)
    return p


def _state():
    from services.api.main import state
    return state


def _poke() -> None:
    try:
        _state().scheduler.poke()
    except Exception:  # noqa: BLE001
        pass


def _step_up(p: Principal, token: str | None, purpose: str) -> str:
    if p.mfa_fresh:
        return "supabase_aal2"
    with db.get_engine().connect() as conn:
        if not stepup.enrolled(conn, p.user_id):
            raise HTTPException(status_code=401, detail={"code": "step_up_enroll", "message": "set up an authenticator first", "purpose": purpose})
    try:
        return stepup.check_token(token, user_id=p.user_id, purpose=purpose)
    except stepup.StepUpRequired as exc:
        raise HTTPException(status_code=401, detail={"code": "step_up_required", "message": str(exc), "purpose": purpose}) from exc


def _repo_view(r) -> dict:
    d = dict(r._mapping)
    d.pop("secret_ciphertext", None)
    d["has_credentials"] = bool(r.secret_ciphertext) or r.auth_mode == "ambient"
    return d


def _proposal_view(r, full: bool = False) -> dict:
    d = dict(r._mapping)
    if not full:
        d.pop("patch", None)
        d["has_patch"] = bool(r.patch)
        d["patch_lines"] = len(r.patch.splitlines()) if r.patch else 0
    return d


# ------------------------------------------------------------------ overview
@router.get("")
def overview(p: Principal = Depends(member)):
    with db.get_engine().connect() as conn:
        org = p.organization_id
        repos = conn.execute(select(db.lab_repositories).where(db.lab_repositories.c.organization_id == org)
                             .order_by(db.lab_repositories.c.created_at)).fetchall()
        cycles = conn.execute(select(db.lab_cycles).where(db.lab_cycles.c.organization_id == org)
                              .order_by(db.lab_cycles.c.created_at.desc()).limit(20)).fetchall()
        props = conn.execute(select(db.lab_proposals).where(db.lab_proposals.c.organization_id == org)
                             .order_by(db.lab_proposals.c.created_at.desc()).limit(60)).fetchall()
    return {"repositories": [_repo_view(r) for r in repos], "cycles": [dict(c._mapping) for c in cycles],
            "proposals": [_proposal_view(x) for x in props],
            "awaiting_owner": sum(1 for x in props if x.status == "AWAITING_OWNER"),
            "ambient_allowed": _ambient_allowed(), "workflow_path": L.WORKFLOW_PATH}


# ------------------------------------------------------------------ repositories
class ConnectIn(BaseModel):
    full_name: str = Field(min_length=3, max_length=140)
    default_branch: str | None = Field(default=None, max_length=100)
    auth_mode: str = Field(default="token", pattern="^(token|github_signin|ambient)$")
    token: str | None = Field(default=None, min_length=20, max_length=400)   # never logged, encrypted at rest


def _ambient_allowed() -> bool:
    return os.environ.get("AICIV_GITHUB_AUTH") == "ambient" or os.environ.get("AICIV_APPLAB_ALLOW_AMBIENT") == "1"


def _verify_access(full_name: str, token: str | None) -> dict:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with L.github_http() as client:
            r = client.get(f"/repos/{full_name}", headers=headers)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"could not reach GitHub: {type(exc).__name__}") from exc
    if r.status_code in (401, 403, 404):
        raise HTTPException(status_code=400, detail="GitHub did not grant access to that repository with these credentials")
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"GitHub returned {r.status_code}")
    j = r.json()
    perms = j.get("permissions") or {}
    if token and perms and not perms.get("push"):
        raise HTTPException(status_code=400, detail="these credentials can read but not write; the App Lab needs Contents, Pull requests "
                                                    "and Issues write access to open draft pull requests and issues")
    return {"default_branch": j.get("default_branch") or "main", "private": bool(j.get("private"))}


@router.post("/repositories", status_code=201)
def connect_repository(body: ConnectIn, p: Principal = Depends(owner), x_step_up: str | None = Header(default=None)):
    """The owner explicitly authorizes one repository. A token comes from the owner's form or their GitHub sign-in
    (Supabase provider token); it is verified against GitHub, encrypted, and never shown again."""
    full = body.full_name.strip()
    if not REPO_RX.fullmatch(full):
        raise HTTPException(status_code=422, detail="repository must look like owner/name")
    method = _step_up(p, x_step_up, "lab-connect")
    if body.auth_mode == "ambient":
        if not _ambient_allowed():
            raise HTTPException(status_code=400, detail="ambient credentials are not enabled on this server")
        if body.token:
            raise HTTPException(status_code=422, detail="ambient mode takes no token")
    elif not body.token:
        raise HTTPException(status_code=422, detail="a GitHub token is required (or sign in with GitHub)")
    info = _verify_access(full, body.token)
    branch = (body.default_branch or info["default_branch"]).strip()
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch):
        raise HTTPException(status_code=422, detail="invalid branch name")
    cipher = crypto.encrypt(body.token) if body.token else None
    with transaction() as conn:
        existing = conn.execute(select(db.lab_repositories).where(db.lab_repositories.c.organization_id == p.organization_id,
                                                                  db.lab_repositories.c.full_name == full)).first()
        values = dict(default_branch=branch, status="ACTIVE", auth_mode=body.auth_mode, secret_ciphertext=cipher, authorized_by=p.user_id,
                      authorized_at=db.utcnow(), last_error=None)
        if existing:
            rid = existing.id
            conn.execute(update(db.lab_repositories).where(db.lab_repositories.c.id == rid).values(**values))
        else:
            rid = db.new_id()
            conn.execute(db.lab_repositories.insert().values(id=rid, organization_id=p.organization_id, full_name=full, **values))
        L.record(conn, org=p.organization_id, actor_type="owner", actor_id=p.user_id, action="lab.repository_authorized", subject_id=rid,
                 detail={"repo": full, "auth_mode": body.auth_mode, "step_up": method, "default_branch": branch})
        LP.lemit(conn, "lab.repository_changed", {"repository_id": rid, "repo": full, "status": "ACTIVE", "label": "repository authorized"})
        row = L.repo_row(conn, rid)
    return _repo_view(row)


@router.post("/repositories/{repo_id}/revoke")
def revoke_repository(repo_id: str, p: Principal = Depends(owner)):
    with transaction() as conn:
        r = L.repo_row(conn, repo_id)
        if r is None or r.organization_id != p.organization_id:
            raise HTTPException(status_code=404, detail="unknown repository")
        conn.execute(update(db.lab_repositories).where(db.lab_repositories.c.id == repo_id).values(
            status="REVOKED", secret_ciphertext=None, autopilot=0))
        for c in conn.execute(select(db.lab_cycles).where(db.lab_cycles.c.repository_id == repo_id,
                                                          db.lab_cycles.c.status.in_(LP.ACTIVE + ("AWAITING_OWNER",)))).fetchall():
            LP.cancel_cycle(conn, c.id, actor_id=p.user_id)
        L.record(conn, org=p.organization_id, actor_type="owner", actor_id=p.user_id, action="lab.repository_revoked", subject_id=repo_id,
                 detail={"repo": r.full_name})
        LP.lemit(conn, "lab.repository_changed", {"repository_id": repo_id, "repo": r.full_name, "status": "REVOKED", "label": "access revoked"})
    return {"repository_id": repo_id, "status": "REVOKED"}


class AutopilotIn(BaseModel):
    enabled: bool


@router.post("/repositories/{repo_id}/autopilot")
def set_autopilot(repo_id: str, body: AutopilotIn, p: Principal = Depends(owner)):
    """Autopilot runs research and drafts proposals on a schedule. It never publishes: every change still waits for you."""
    with transaction() as conn:
        r = L.repo_row(conn, repo_id)
        if r is None or r.organization_id != p.organization_id or r.status != "ACTIVE":
            raise HTTPException(status_code=404, detail="unknown or unauthorized repository")
        conn.execute(update(db.lab_repositories).where(db.lab_repositories.c.id == repo_id).values(autopilot=1 if body.enabled else 0))
        L.record(conn, org=p.organization_id, actor_type="owner", actor_id=p.user_id, action="lab.autopilot", subject_id=repo_id,
                 detail={"enabled": body.enabled})
    _poke()
    return {"repository_id": repo_id, "autopilot": body.enabled}


@router.post("/repositories/{repo_id}/cycles", status_code=201)
def start_cycle(repo_id: str, p: Principal = Depends(owner)):
    with transaction() as conn:
        r = L.repo_row(conn, repo_id)
        if r is None or r.organization_id != p.organization_id:
            raise HTTPException(status_code=404, detail="unknown repository")
        try:
            cid = LP.start_cycle(conn, repo_id=repo_id, trigger="owner", actor_id=p.user_id)
        except L.LabRefused as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    _poke()
    return {"cycle_id": cid, "status": "RESEARCHING", "authorizes": "research and proposals only; nothing is pushed without your approval"}


@router.get("/cycles/{cycle_id}")
def cycle_detail(cycle_id: str, p: Principal = Depends(member)):
    with db.get_engine().connect() as conn:
        c = LP.cycle(conn, cycle_id)
        if c is None or c.organization_id != p.organization_id:
            raise HTTPException(status_code=404, detail="unknown cycle")
        insights = conn.execute(select(db.design_insights).where(db.design_insights.c.cycle_id == cycle_id)).fetchall()
        pkgs = conn.execute(select(db.logistics_packages).where(db.logistics_packages.c.subject_id == cycle_id)
                            .order_by(db.logistics_packages.c.created_at)).fetchall()
        repo = L.repo_row(conn, c.repository_id)
        return {"cycle": dict(c._mapping), "repository": _repo_view(repo), "insights": [dict(i._mapping) for i in insights],
                "proposals": [_proposal_view(x) for x in LP.proposals(conn, cycle_id)],
                "packages": [{"id": k.id, "package_type": k.package_type, "origin": k.origin_district, "destination": k.destination_district,
                              "status": k.status} for k in pkgs]}


@router.post("/cycles/{cycle_id}/cancel")
def cancel_cycle(cycle_id: str, p: Principal = Depends(owner)):
    with transaction() as conn:
        c = LP.cycle(conn, cycle_id)
        if c is None or c.organization_id != p.organization_id:
            raise HTTPException(status_code=404, detail="unknown cycle")
        try:
            LP.cancel_cycle(conn, cycle_id, actor_id=p.user_id)
        except L.LabRefused as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"cycle_id": cycle_id, "status": "CANCELLED"}


# ------------------------------------------------------------------ proposals
@router.get("/proposals/{proposal_id}")
def proposal_detail(proposal_id: str, p: Principal = Depends(member)):
    with db.get_engine().connect() as conn:
        r = conn.execute(select(db.lab_proposals).where(db.lab_proposals.c.id == proposal_id)).first()
        if r is None or r.organization_id != p.organization_id:
            raise HTTPException(status_code=404, detail="unknown proposal")
        repo = L.repo_row(conn, r.repository_id)
        insights = conn.execute(select(db.design_insights).where(db.design_insights.c.id.in_(r.insight_ids or []))).fetchall()
        return {"proposal": _proposal_view(r, full=True), "repository": _repo_view(repo), "insights": [dict(i._mapping) for i in insights],
                "step_up_purpose": f"lab:{proposal_id}"}


class DecideIn(BaseModel):
    decision: str = Field(pattern="^(APPROVE|REJECT|DEFER)$")
    payload_hash: str = Field(min_length=64, max_length=64)
    note: str | None = Field(default=None, max_length=500)


@router.post("/proposals/{proposal_id}/decide")
def decide_proposal(proposal_id: str, body: DecideIn, p: Principal = Depends(owner), x_step_up: str | None = Header(default=None)):
    method = _step_up(p, x_step_up, f"lab:{proposal_id}") if body.decision == "APPROVE" else None
    mission_id = None
    with transaction() as conn:
        r = conn.execute(select(db.lab_proposals).where(db.lab_proposals.c.id == proposal_id)).first()
        if r is None or r.organization_id != p.organization_id:
            raise HTTPException(status_code=404, detail="unknown proposal")
        if r.status not in ("AWAITING_OWNER", "DEFERRED"):
            raise HTTPException(status_code=409, detail=f"proposal is {r.status.lower()}")
        if body.payload_hash != r.payload_hash:
            raise HTTPException(status_code=409, detail="the change was modified after you reviewed it; reload and review again")
        repo = L.repo_row(conn, r.repository_id)
        if body.decision == "APPROVE":
            if repo is None or repo.status != "ACTIVE":
                raise HTTPException(status_code=409, detail="repository access was revoked")
            if (r.gm_review or {}).get("verdict") != "recommend":
                raise HTTPException(status_code=409, detail="the General Manager has not cleared this proposal")
            c = LP.cycle(conn, r.cycle_id)
            mission_id = create_mission(conn, org_id=r.organization_id, kind="lab_publish", title=f"Publish: {r.title}"[:120],
                                        prompt="Publish the owner-approved App Lab change. Never the default branch.",
                                        params={"proposal_id": proposal_id, "cycle_id": r.cycle_id, "repository_id": r.repository_id},
                                        opportunity_id=None, created_by=agent_by_key(conn, "developer").id)
            status = "APPROVED"
            values = dict(decided_by=p.user_id, decided_at=db.utcnow(), step_up_method=method, publish_mission_id=mission_id)
        else:
            status = "REJECTED" if body.decision == "REJECT" else "DEFERRED"
            values = dict(decided_by=p.user_id, decided_at=db.utcnow())
        n = conn.execute(update(db.lab_proposals).where(db.lab_proposals.c.id == proposal_id, db.lab_proposals.c.status == r.status,
                                                        db.lab_proposals.c.payload_hash == body.payload_hash)
                         .values(status=status, updated_at=db.utcnow(), **values)).rowcount
        if n != 1:
            raise HTTPException(status_code=409, detail="the proposal changed; reload and review again")
        L.record(conn, org=p.organization_id, actor_type="owner", actor_id=p.user_id, action="lab.proposal_decided", subject_id=proposal_id,
                 detail={"decision": body.decision, "step_up": method, "payload_hash": body.payload_hash, "note": (body.note or "")[:200]})
        LP.lemit(conn, "lab.proposal_decided", {"proposal_id": proposal_id, "cycle_id": r.cycle_id, "repository_id": r.repository_id,
                                                "decision": body.decision, "route": r.route, "title": r.title[:80], "data_mode": r.data_mode},
                 simulated=r.data_mode == "simulated")
    if mission_id:
        _state().worker.enqueue(mission_id)
    _poke()
    return {"proposal_id": proposal_id, "status": status, "publish_mission_id": mission_id}
