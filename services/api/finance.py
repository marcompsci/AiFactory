"""V5 endpoints: AI Central Bank. Owners and admins can read; only the owner can decide, authorize or export.
Approving and authorizing need step-up (header `X-Step-Up`). See docs/finance/THREAT_MODEL.md."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, insert, select, update

from services.core import db
from services.core.auth import Principal, authenticate, mutation_limiter
from services.core.events import transaction
from services.finance import approvals as A
from services.finance import audit, crypto, dashboard, retention, stepup, sync, tax
from services.finance import connectors as C
from services.finance import packets as P
from services.finance.events import femit
from services.finance.permissions import require_finance, require_owner
from services.finance.pipeline import finance_mode, owner_decision, reopen
from services.management.hierarchy import agent_by_key
from services.management.pipeline import create_mission

router = APIRouter(prefix="/api/finance")


def reader(request: Request) -> Principal:
    p = authenticate(request)
    require_finance(p)
    return p


def owner(request: Request) -> Principal:
    p = authenticate(request)
    require_owner(p)
    mutation_limiter.check(p.user_id)
    return p


def operator(request: Request) -> Principal:
    p = authenticate(request)
    p.require("operator")
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


def _refused(exc: Exception) -> HTTPException:
    msg = str(exc)
    if "step-up" in msg or isinstance(exc, stepup.StepUpRequired):
        return HTTPException(status_code=401, detail={"code": "step_up_required", "message": msg})
    return HTTPException(status_code=409, detail=msg)


def _row(r) -> dict:
    return dict(r._mapping)


# ------------------------------------------------------------------ dashboard
@router.get("/dashboard")
def get_dashboard(p: Principal = Depends(reader)):
    with db.get_engine().connect() as conn:
        out = dashboard.build(conn, p.organization_id)
        out["open_reviews"] = conn.execute(select(func.count()).select_from(db.cost_review_packets).where(
            db.cost_review_packets.c.organization_id == p.organization_id,
            db.cost_review_packets.c.status.notin_(["EXECUTED", "REJECTED", "CLOSED"]))).scalar()
        out["waiting_for_owner"] = conn.execute(select(func.count()).select_from(db.financial_approvals).where(
            db.financial_approvals.c.organization_id == p.organization_id, db.financial_approvals.c.status == "REQUESTED")).scalar()
    return out


# ------------------------------------------------------------------ step-up
class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)
    purpose: str = Field(min_length=3, max_length=80)


@router.get("/stepup")
def stepup_status(p: Principal = Depends(owner)):
    with db.get_engine().connect() as conn:
        return {"enrolled": stepup.enrolled(conn, p.user_id), "mfa_fresh": p.mfa_fresh, "token_ttl_seconds": stepup.TOKEN_TTL}


@router.post("/stepup/enroll", status_code=201)
def stepup_enroll(p: Principal = Depends(owner)):
    """Shown once. Scan the otpauth URI into an authenticator app."""
    with transaction() as conn:
        try:
            out = stepup.enroll(conn, user_id=p.user_id, org_id=p.organization_id)
        except stepup.StepUpRequired as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        audit.record(conn, org_id=p.organization_id, actor_type="owner", actor_id=p.user_id, action="stepup.enrolled",
                     subject_type="user", subject_id=p.user_id)
    return out


@router.post("/stepup/verify")
def stepup_verify(body: CodeIn, p: Principal = Depends(owner)):
    with transaction() as conn:
        try:
            stepup.check_code(conn, p.user_id, body.code)
        except stepup.StepUpRequired as exc:
            audit.record(conn, org_id=p.organization_id, actor_type="owner", actor_id=p.user_id, action="stepup.failed",
                         subject_type="user", subject_id=p.user_id, detail={"purpose": body.purpose})
            raise HTTPException(status_code=401, detail={"code": "step_up_failed", "message": str(exc)}) from exc
    return {"step_up_token": stepup.issue_token(p.user_id, body.purpose, "totp"), "expires_in": stepup.TOKEN_TTL, "purpose": body.purpose}


def _require_step_up(p: Principal, token: str | None, purpose: str) -> str:
    if p.mfa_fresh:
        return "supabase_aal2"
    try:
        return stepup.check_token(token, user_id=p.user_id, purpose=purpose)
    except stepup.StepUpRequired as exc:
        raise HTTPException(status_code=401, detail={"code": "step_up_required", "message": str(exc), "purpose": purpose}) from exc


# ------------------------------------------------------------------ cost reviews
class ToolRequestIn(BaseModel):
    vendor: str = Field(min_length=1, max_length=80)
    item: str = Field(min_length=1, max_length=120)
    amount: float = Field(ge=0, le=100_000)
    currency: str = Field(default="USD", pattern="^[A-Z]{3}$")
    interval: str = Field(pattern="^(one_time|month|year)$")
    justification: str = Field(default="", max_length=1000)


@router.post("/tool-requests", status_code=201)
def tool_request(body: ToolRequestIn, p: Principal = Depends(operator)):
    """A development agent asks for a paid tool: a Developer mission files it with the bank. Buys nothing."""
    with transaction() as conn:
        dev = agent_by_key(conn, "developer")
        mid = create_mission(conn, org_id=p.organization_id, kind="request_tool", title="Request a paid tool from the bank",
                             prompt="File a paid-tool request with the AI Central Bank.",
                             params={"vendor": body.vendor, "item": body.item, "amount_minor": round(body.amount * 100), "currency": body.currency,
                                     "interval": body.interval, "justification": body.justification,
                                     "data_mode": finance_mode(conn, p.organization_id) if finance_mode(conn, p.organization_id) == "live" else "simulated"},
                             opportunity_id=None, created_by=dev.id)
    _state().worker.enqueue(mid)
    return {"mission_id": mid}


@router.get("/packets")
def list_packets(p: Principal = Depends(reader)):
    with db.get_engine().connect() as conn:
        rows = conn.execute(select(db.cost_review_packets).where(db.cost_review_packets.c.organization_id == p.organization_id)
                            .order_by(db.cost_review_packets.c.created_at.desc()).limit(100)).fetchall()
    return {"packets": [_row(r) for r in rows]}


@router.get("/packets/{packet_id}")
def packet_detail(packet_id: str, p: Principal = Depends(reader)):
    with db.get_engine().connect() as conn:
        pk = P.get(conn, packet_id)
        if pk is None or pk.organization_id != p.organization_id:
            raise HTTPException(status_code=404, detail="not found")
        apps = conn.execute(select(db.financial_approvals).where(db.financial_approvals.c.packet_id == packet_id)
                            .order_by(db.financial_approvals.c.created_at)).fetchall()
        savings = conn.execute(select(db.savings_opportunities).where(db.savings_opportunities.c.packet_id == packet_id)).fetchall()
        pkgs = conn.execute(select(db.logistics_packages).where(db.logistics_packages.c.subject_id == packet_id)
                            .order_by(db.logistics_packages.c.created_at)).fetchall()
        trail = conn.execute(select(db.financial_audit_events).where(db.financial_audit_events.c.subject_id.in_([packet_id] + [a.id for a in apps]))
                             .order_by(db.financial_audit_events.c.seq)).fetchall()
    return {"packet": _row(pk), "approvals": [_row(a) for a in apps], "savings": [_row(s) for s in savings],
            "packages": [{"id": x.id, "type": x.package_type, "status": x.status, "origin": x.origin_district, "destination": x.destination_district,
                          "created_at": x.created_at} for x in pkgs],
            "audit": [{"seq": t.seq, "action": t.action, "actor_type": t.actor_type, "detail": t.detail, "at": t.created_at} for t in trail]}


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(APPROVE|REJECT|DEFER|MORE_RESEARCH|ACKNOWLEDGE)$")
    approval_id: str | None = None
    payload_hash: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    note: str | None = Field(default=None, max_length=500)
    defer_days: int | None = Field(default=None, ge=1, le=90)


@router.post("/packets/{packet_id}/decide")
def decide_packet(packet_id: str, body: DecisionIn, p: Principal = Depends(owner), x_step_up: str | None = Header(default=None)):
    with transaction() as conn:
        try:
            out = owner_decision(conn, packet_id=packet_id, approval_id=body.approval_id, decision=body.decision,
                                 presented_hash=body.payload_hash, owner_id=p.user_id, owner_role=p.role, step_up_token=x_step_up,
                                 mfa_fresh=p.mfa_fresh, note=body.note, defer_days=body.defer_days)
        except (A.ApprovalRefused, stepup.StepUpRequired) as exc:
            audit.record(conn, org_id=p.organization_id, actor_type="owner", actor_id=p.user_id, action="decision.refused",
                         subject_type="cost_review_packet", subject_id=packet_id, detail={"decision": body.decision, "reason": str(exc)[:200]})
            femit(conn, "finance.action_refused", {"packet_id": packet_id, "decision": body.decision, "reason_code": "refused"})
            refused = exc
        else:
            refused = None
    if refused is not None:
        raise _refused(refused)
    _poke()
    return out


@router.post("/packets/{packet_id}/reopen")
def reopen_packet(packet_id: str, p: Principal = Depends(owner)):
    with transaction() as conn:
        try:
            reopen(conn, packet_id, actor_type="owner", actor_id=p.user_id, reason="owner reopened it")
        except A.ApprovalRefused as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    _poke()
    return {"packet_id": packet_id, "status": "OWNER_DECISION"}


# ------------------------------------------------------------------ approvals (all kinds, including bill payments)
@router.get("/approvals")
def list_approvals(p: Principal = Depends(reader), status: str | None = None):
    with db.get_engine().connect() as conn:
        q = select(db.financial_approvals).where(db.financial_approvals.c.organization_id == p.organization_id)
        if status:
            q = q.where(db.financial_approvals.c.status == status.upper())
        rows = conn.execute(q.order_by(db.financial_approvals.c.created_at.desc()).limit(100)).fetchall()
    return {"approvals": [_row(r) for r in rows]}


class ApprovalDecisionIn(BaseModel):
    decision: str = Field(pattern="^(APPROVE|REJECT|DEFER)$")
    payload_hash: str = Field(pattern="^[0-9a-f]{64}$")
    note: str | None = Field(default=None, max_length=500)


@router.post("/approvals/{approval_id}/decide")
def decide_approval(approval_id: str, body: ApprovalDecisionIn, p: Principal = Depends(owner), x_step_up: str | None = Header(default=None)):
    """For approvals that are not part of a cost review (bill payments)."""
    with transaction() as conn:
        a = A.get(conn, approval_id)
        if a is None or a.organization_id != p.organization_id:
            raise HTTPException(status_code=404, detail="not found")
        if a.packet_id:
            raise HTTPException(status_code=409, detail="decide this from its cost review")
        try:
            out = A.decide(conn, approval_id=approval_id, decision=body.decision, presented_hash=body.payload_hash, owner_id=p.user_id,
                           owner_role=p.role, step_up_token=x_step_up, mfa_fresh=p.mfa_fresh, note=body.note)
            refused = None
        except A.ApprovalRefused as exc:
            audit.record(conn, org_id=p.organization_id, actor_type="owner", actor_id=p.user_id, action="decision.refused",
                         subject_type="financial_approval", subject_id=approval_id, detail={"reason": str(exc)[:200]})
            refused = exc
    if refused is not None:
        raise _refused(refused)
    _poke()
    return out


@router.post("/approvals/{approval_id}/complete")
def complete_manually(approval_id: str, p: Principal = Depends(owner), x_step_up: str | None = Header(default=None)):
    """The owner did an approved purchase/payment themselves (no payment integration): record it once."""
    method = _require_step_up(p, x_step_up, f"complete:{approval_id}")
    with transaction() as conn:
        a = A.get(conn, approval_id)
        if a is None or a.organization_id != p.organization_id:
            raise HTTPException(status_code=404, detail="not found")
        if a.status != "APPROVED":
            raise HTTPException(status_code=409, detail=f"approval is {a.status.lower()}")
        if not A.mark_executed(conn, a, execution_ref=f"manual by owner ({method})", execution_mode="manual", actor_type="owner", actor_id=p.user_id):
            raise HTTPException(status_code=409, detail="already recorded")
        femit(conn, "finance.action_executed", {"approval_id": a.id, "packet_id": a.packet_id, "action_type": a.action_type,
                                                "data_mode": a.data_mode, "label": "completed by the owner"})
    _poke()
    return {"approval_id": approval_id, "status": "EXECUTED", "execution_mode": "manual"}


# ------------------------------------------------------------------ connections
@router.get("/providers")
def providers(p: Principal = Depends(reader)):
    return {"providers": [{"key": x.key, "kind": x.kind, "label": x.label, "scopes": list(x.scopes), "read_only": x.read_only, "built": x.built,
                           "credential_hint": x.credential_hint} for x in C.PROVIDERS.values()]}


@router.get("/connections")
def list_connections(p: Principal = Depends(reader)):
    with db.get_engine().connect() as conn:
        rows = conn.execute(select(db.financial_connections).where(db.financial_connections.c.organization_id == p.organization_id)
                            .order_by(db.financial_connections.c.created_at)).fetchall()
        runs = conn.execute(select(db.financial_sync_runs).where(db.financial_sync_runs.c.organization_id == p.organization_id)
                            .order_by(db.financial_sync_runs.c.started_at.desc()).limit(30)).fetchall()
        cov = sync.coverage(conn, p.organization_id)
    hide = {"secret_ciphertext"}
    return {"connections": [{k: v for k, v in _row(r).items() if k not in hide} | {"has_credential": bool(r.secret_ciphertext)} for r in rows],
            "sync_runs": [_row(r) for r in runs], "coverage": cov}


class ConnectionIn(BaseModel):
    provider: str = Field(min_length=2, max_length=40)
    display_name: str = Field(default="", max_length=80)


@router.post("/connections", status_code=201)
def create_connection(body: ConnectionIn, p: Principal = Depends(owner)):
    prov = C.PROVIDERS.get(body.provider)
    if prov is None:
        raise HTTPException(status_code=422, detail="unknown provider")
    if not prov.built:
        raise HTTPException(status_code=409, detail=f"{prov.label} integration is not built yet")
    try:
        C.check_read_only(prov)
    except C.AdapterError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    cid = db.new_id()
    with transaction() as conn:
        conn.execute(insert(db.financial_connections).values(
            id=cid, organization_id=p.organization_id, kind=prov.kind, provider=prov.key, display_name=body.display_name or prov.label,
            access_mode="read_only", scopes=list(prov.scopes), status="PENDING_AUTHORIZATION",
            data_mode="simulated" if prov.key == "simulated" else ("upload" if prov.key == "csv_upload" else "live")))
        audit.record(conn, org_id=p.organization_id, actor_type="owner", actor_id=p.user_id, action="connection.created",
                     subject_type="financial_connection", subject_id=cid, detail={"provider": prov.key, "scopes": list(prov.scopes)})
        femit(conn, "finance.connection_status_changed", {"connection_id": cid, "provider": prov.key, "status": "PENDING_AUTHORIZATION"})
    return {"id": cid, "status": "PENDING_AUTHORIZATION", "scopes": list(prov.scopes), "credential_hint": prov.credential_hint}


class AuthorizeIn(BaseModel):
    credential: str | None = Field(default=None, max_length=8000)
    confirm_read_only: bool = False


@router.post("/connections/{connection_id}/authorize")
def authorize_connection(connection_id: str, body: AuthorizeIn, p: Principal = Depends(owner), x_step_up: str | None = Header(default=None)):
    """The only way a connection becomes ACTIVE: the owner, explicitly, in this app (THREAT_MODEL F10)."""
    if not body.confirm_read_only:
        raise HTTPException(status_code=422, detail="confirm that you are granting read-only access")
    with db.get_engine().connect() as conn:
        c = conn.execute(select(db.financial_connections).where(db.financial_connections.c.id == connection_id,
                                                                db.financial_connections.c.organization_id == p.organization_id)).first()
    if c is None:
        raise HTTPException(status_code=404, detail="not found")
    method = "owner" if c.provider in ("simulated", "csv_upload") else _require_step_up(p, x_step_up, f"connection:{connection_id}")
    secret = body.credential
    if c.provider == "simulated":
        secret = json.dumps({"anchor": datetime.now(timezone.utc).date().replace(day=1).isoformat()})
    elif c.provider == "stripe" and not (secret or "").strip().startswith("rk_"):
        raise HTTPException(status_code=422, detail="use a restricted key (rk_…) with read-only Balance access")
    elif c.provider not in ("csv_upload",) and not secret:
        raise HTTPException(status_code=422, detail="this provider needs a credential")
    with transaction() as conn:
        conn.execute(update(db.financial_connections).where(db.financial_connections.c.id == connection_id).values(
            status="ACTIVE", secret_ciphertext=crypto.encrypt(secret) if secret else None, authorized_by=p.user_id, authorized_at=db.utcnow(),
            last_error=None))
        audit.record(conn, org_id=p.organization_id, actor_type="owner", actor_id=p.user_id, action="connection.authorized",
                     subject_type="financial_connection", subject_id=connection_id, detail={"provider": c.provider, "method": method,
                                                                                            "scopes": c.scopes, "access_mode": "read_only"})
        femit(conn, "finance.connection_status_changed", {"connection_id": connection_id, "provider": c.provider, "status": "ACTIVE"},
              simulated=c.provider == "simulated")
    return {"id": connection_id, "status": "ACTIVE"}


@router.post("/connections/{connection_id}/sync")
def sync_connection(connection_id: str, p: Principal = Depends(owner)):
    try:
        out = sync.run(connection_id, actor_id=p.user_id)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _poke()
    return out


@router.put("/connections/{connection_id}/upload")
async def upload_statement(connection_id: str, request: Request, p: Principal = Depends(owner)):
    """Body: the CSV file itself (Content-Type text/csv). Parsed in memory; the raw file is not stored."""
    data = await request.body()
    with db.get_engine().connect() as conn:
        c = conn.execute(select(db.financial_connections).where(db.financial_connections.c.id == connection_id,
                                                                db.financial_connections.c.organization_id == p.organization_id)).first()
    if c is None or c.provider != "csv_upload":
        raise HTTPException(status_code=404, detail="not a CSV upload connection")
    try:
        out = sync.run(connection_id, actor_id=p.user_id, upload=data)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _poke()
    return out


@router.post("/connections/{connection_id}/revoke")
def revoke_connection(connection_id: str, p: Principal = Depends(owner)):
    with transaction() as conn:
        n = conn.execute(update(db.financial_connections).where(db.financial_connections.c.id == connection_id,
                                                                db.financial_connections.c.organization_id == p.organization_id)
                         .values(status="REVOKED", secret_ciphertext=None)).rowcount
        if not n:
            raise HTTPException(status_code=404, detail="not found")
        audit.record(conn, org_id=p.organization_id, actor_type="owner", actor_id=p.user_id, action="connection.revoked",
                     subject_type="financial_connection", subject_id=connection_id)
        femit(conn, "finance.connection_status_changed", {"connection_id": connection_id, "status": "REVOKED"})
    return {"id": connection_id, "status": "REVOKED"}


@router.delete("/connections/{connection_id}/data")
def delete_connection_data(connection_id: str, p: Principal = Depends(owner), x_step_up: str | None = Header(default=None)):
    _require_step_up(p, x_step_up, f"delete:{connection_id}")
    with transaction() as conn:
        try:
            counts = retention.delete_connection_data(conn, org=p.organization_id, connection_id=connection_id, actor_id=p.user_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": counts}


@router.post("/simulated", status_code=201)
def load_simulated(p: Principal = Depends(owner)):
    """Convenience for testing: create, authorize and sync a SIMULATED ledger (labeled everywhere)."""
    with db.get_engine().connect() as conn:
        existing = conn.execute(select(db.financial_connections.c.id).where(db.financial_connections.c.organization_id == p.organization_id,
                                                                            db.financial_connections.c.provider == "simulated",
                                                                            db.financial_connections.c.status == "ACTIVE")).first()
    if existing:
        cid = existing.id
    else:
        cid = create_connection(ConnectionIn(provider="simulated", display_name="Simulated business ledger"), p)["id"]
        authorize_connection(cid, AuthorizeIn(confirm_read_only=True), p, None)
    out = sync.run(cid, actor_id=p.user_id)
    _poke()
    return {"connection_id": cid, **out}


# ------------------------------------------------------------------ ledger
@router.get("/transactions")
def transactions(p: Principal = Depends(reader), limit: int = 100, category: str | None = None, kind: str | None = None):
    with db.get_engine().connect() as conn:
        q = select(db.financial_transactions).where(db.financial_transactions.c.organization_id == p.organization_id)
        if category:
            q = q.where(db.financial_transactions.c.category_key == category)
        if kind:
            q = q.where(db.financial_transactions.c.kind == kind)
        rows = conn.execute(q.order_by(db.financial_transactions.c.posted_at.desc()).limit(max(1, min(limit, 500)))).fetchall()
    return {"transactions": [{k: v for k, v in _row(r).items() if k not in ("dedupe_key",)} for r in rows]}


# ------------------------------------------------------------------ tax
@router.get("/tax")
def tax_overview(p: Principal = Depends(reader), tax_year: int | None = None):
    year = tax_year or datetime.now(timezone.utc).year
    with db.get_engine().connect() as conn:
        rows = tax._rows(conn, p.organization_id, year)
        est = conn.execute(select(db.tax_estimates).where(db.tax_estimates.c.organization_id == p.organization_id, db.tax_estimates.c.tax_year == year)
                           .order_by(db.tax_estimates.c.created_at.desc())).first()
        docs = conn.execute(select(db.tax_documents).where(db.tax_documents.c.organization_id == p.organization_id,
                                                           db.tax_documents.c.tax_year == year)).fetchall()
        checklist = tax.expected_documents(conn, p.organization_id, year, rows)
    return {"tax_year": year, "jurisdictions": tax.jurisdictions(), "deadlines": [d for j in tax.jurisdictions() for d in tax.deadlines(year, j)],
            "estimate": _row(est) if est else None, "documents": [{k: v for k, v in _row(d).items() if k != "storage_path"} for d in docs],
            "checklist": checklist, "filing": {"available": False, "reason": "No authorized filing integration. Export the package for your tax professional."}}


class EstimateIn(BaseModel):
    tax_year: int | None = Field(default=None, ge=2000, le=2100)
    jurisdiction: str = Field(default="US-FED", pattern="^[A-Z]{2}-[A-Z]{2,3}$")


@router.post("/tax/estimate", status_code=201)
def tax_estimate(body: EstimateIn, p: Principal = Depends(owner)):
    with transaction() as conn:
        eid = tax.estimate(conn, p.organization_id, body.tax_year, body.jurisdiction)
    _poke()
    return {"estimate_id": eid}


@router.put("/tax/documents")
async def tax_document(request: Request, tax_year: int, doc_type: str, jurisdiction: str = "US-FED", note: str | None = None,
                       p: Principal = Depends(owner)):
    data = await request.body()
    with transaction() as conn:
        try:
            did = tax.store_document(conn, org=p.organization_id, tax_year=tax_year, jurisdiction=jurisdiction, doc_type=doc_type, data=data,
                                     actor_id=p.user_id, note=note)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"document_id": did}


@router.post("/tax/documents/{doc_id}/verify")
def tax_document_verify(doc_id: str, p: Principal = Depends(owner)):
    with transaction() as conn:
        tax.verify_document(conn, org=p.organization_id, doc_id=doc_id, actor_id=p.user_id)
    return {"document_id": doc_id, "status": "VERIFIED"}


@router.delete("/tax/documents/{doc_id}")
def tax_document_delete(doc_id: str, p: Principal = Depends(owner)):
    with transaction() as conn:
        try:
            retention.delete_tax_document(conn, org=p.organization_id, doc_id=doc_id, actor_id=p.user_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": doc_id}


@router.get("/tax/export")
def tax_export(tax_year: int, p: Principal = Depends(owner), x_step_up: str | None = Header(default=None)):
    _require_step_up(p, x_step_up, f"export:{tax_year}")
    with transaction() as conn:
        data = tax.export_package(conn, p.organization_id, tax_year, p.user_id)
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="tax-review-{tax_year}.zip"', "Cache-Control": "no-store"})


@router.post("/tax/file")
def tax_file(p: Principal = Depends(owner)):
    """Always refused: there is no authorized filing integration (THREAT_MODEL F15)."""
    with transaction() as conn:
        audit.record(conn, org_id=p.organization_id, actor_type="owner", actor_id=p.user_id, action="tax.filing_refused",
                     subject_type="tax_year", subject_id=None, detail={"reason": "no authorized filing integration"})
        femit(conn, "finance.action_refused", {"action_type": "tax_filing", "reason_code": "no_filing_integration"})
    raise HTTPException(status_code=409, detail="Tax filings are never submitted from here: no authorized filing integration exists. "
                                                "Export the review package for a qualified tax professional.")


# ------------------------------------------------------------------ audit
@router.get("/audit")
def audit_log(p: Principal = Depends(reader), limit: int = 200):
    with db.get_engine().connect() as conn:
        rows = conn.execute(select(db.financial_audit_events).where(db.financial_audit_events.c.organization_id == p.organization_id)
                            .order_by(db.financial_audit_events.c.seq.desc()).limit(max(1, min(limit, 1000)))).fetchall()
        chain = audit.verify(conn, p.organization_id)
    return {"chain": chain, "events": [_row(r) for r in rows]}
