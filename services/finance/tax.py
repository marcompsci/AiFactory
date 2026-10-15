"""Tax preparation workflows (spec §9). The bank collects documents, categorizes and reconciles, tracks deadlines,
and drafts **labeled estimates** for a qualified tax professional. It never files. No filing integration is
authorized, so `execute_financial_action` refuses `tax_filing` (THREAT_MODEL F15).

The reserve rate (AICIV_TAX_RESERVE_RATE, default 0.30) is a planning assumption, not a tax computation. Deadline
dates follow the usual US schedule (moved to Monday when they fall on a weekend; holidays are NOT accounted for).
Confirm every date with the IRS or your state, or with your tax professional.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import zipfile
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection

from services.core import db
from services.core.config import get_settings
from services.logistics import service as logistics
from services.management.hierarchy import agent_by_key

from . import audit
from .events import femit

DOC_TYPES = ("1099-K", "1099-NEC", "1099-MISC", "receipt", "bank_statement", "card_statement", "prior_return", "invoice", "other")


def jurisdictions() -> list[str]:
    return [j.strip() for j in os.environ.get("AICIV_FINANCE_JURISDICTIONS", "US-FED").split(",") if j.strip()]


def reserve_rate() -> float:
    return float(os.environ.get("AICIV_TAX_RESERVE_RATE", "0.30"))


def _weekday_shift(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def deadlines(tax_year: int, jurisdiction: str) -> list[dict]:
    if jurisdiction == "US-FED":
        raw = [("Q1 estimated tax", date(tax_year, 4, 15)), ("Q2 estimated tax", date(tax_year, 6, 15)),
               ("Q3 estimated tax", date(tax_year, 9, 15)), ("Q4 estimated tax", date(tax_year + 1, 1, 15)),
               ("Annual return (Form 1040 with Schedule C)", date(tax_year + 1, 4, 15))]
    elif jurisdiction == "US-CA":
        raw = [("CA Q1 estimated tax (30%)", date(tax_year, 4, 15)), ("CA Q2 estimated tax (40%)", date(tax_year, 6, 15)),
               ("CA Q4 estimated tax (30%)", date(tax_year + 1, 1, 15)), ("CA annual return (Form 540)", date(tax_year + 1, 4, 15))]
    else:
        return [{"label": "No deadline schedule configured for this jurisdiction", "due": None, "jurisdiction": jurisdiction}]
    today = datetime.now(timezone.utc).date()
    out = []
    for label, d in raw:
        due = _weekday_shift(d)
        out.append({"label": label, "due": due.isoformat(), "days_left": (due - today).days, "jurisdiction": jurisdiction,
                    "note": "weekend-adjusted; holidays not accounted for; confirm with the tax authority"})
    return out


def _rows(conn: Connection, org: str, tax_year: int):
    start, end = datetime(tax_year, 1, 1, tzinfo=timezone.utc).isoformat(), datetime(tax_year + 1, 1, 1, tzinfo=timezone.utc).isoformat()
    return conn.execute(select(db.financial_transactions).where(db.financial_transactions.c.organization_id == org,
                                                                db.financial_transactions.c.posted_at >= start,
                                                                db.financial_transactions.c.posted_at < end)).fetchall()


def expected_documents(conn: Connection, org: str, tax_year: int, rows) -> list[dict]:
    """A checklist of likely documents, from what the ledger shows. 'Likely' because only a professional can say for sure."""
    exp = [{"doc_type": "prior_return", "why": "last year's return, for carryovers and safe-harbor estimates"},
           {"doc_type": "bank_statement", "why": "monthly statements to back the ledger"}]
    if any(r.merchant == "Stripe" and r.kind == "revenue" for r in rows):
        exp.append({"doc_type": "1099-K", "why": "payment processor revenue (issued if you crossed the reporting threshold)"})
    contractor = -sum(r.amount_minor for r in rows if r.category_key == "contractors")
    if contractor >= 60_000:
        exp.append({"doc_type": "1099-NEC", "why": "contract labor paid this year may require issuing 1099-NEC forms; confirm with your professional"})
    if any(r.amount_minor <= -7_500 and r.kind == "expense" for r in rows):
        exp.append({"doc_type": "receipt", "why": "receipts for larger expenses (keep receipts for business expenses generally)"})
    have = {d.doc_type for d in conn.execute(select(db.tax_documents).where(db.tax_documents.c.organization_id == org,
                                                                            db.tax_documents.c.tax_year == tax_year,
                                                                            db.tax_documents.c.status != "MISSING"))}
    return [{**e, "status": "received" if e["doc_type"] in have else "missing"} for e in exp]


def estimate(conn: Connection, org: str, tax_year: int | None = None, jurisdiction: str = "US-FED", ship: bool = True) -> str:
    tax_year = tax_year or datetime.now(timezone.utc).year
    rows = _rows(conn, org, tax_year)
    cats = {c.key: c for c in conn.execute(select(db.expense_categories).where(db.expense_categories.c.organization_id == org))}
    revenue = sum(r.amount_minor for r in rows if r.kind == "revenue") + sum(r.amount_minor for r in rows if r.kind == "refund")
    deductible = 0
    partial = 0
    for r in rows:
        if r.amount_minor >= 0 or r.kind in ("transfer", "tax"):
            continue
        t = cats.get(r.category_key or "uncategorized")
        if t is None:
            continue
        if t.tax_treatment == "deductible":
            deductible += -r.amount_minor
        elif t.tax_treatment == "partially_deductible":
            deductible += -r.amount_minor // 2
            partial += -r.amount_minor
    net = revenue - deductible
    est_tax = max(0, round(net * reserve_rate()))
    paid = -sum(r.amount_minor for r in rows if r.kind == "tax")
    uncertainty = []
    unc = sum(1 for r in rows if r.category_key == "uncategorized")
    if unc:
        uncertainty.append(f"{unc} uncategorized transaction(s) are excluded from deductions until reviewed")
    if partial:
        uncertainty.append("phone/internet counted at an assumed 50% business use; set the real share with your professional")
    needs = sum(1 for r in rows if r.reconciliation_status != "MATCHED")
    if needs:
        uncertainty.append(f"{needs} transaction(s) not yet reconciled")
    modes = {r.data_mode for r in rows}
    if "simulated" in modes:
        uncertainty.append("SIMULATED data: these figures describe test data, not your business")
    uncertainty.append(f"planning reserve rate {reserve_rate():.0%} is an assumption, not your tax rate")
    missing = [e for e in expected_documents(conn, org, tax_year, rows) if e["status"] == "missing"]
    eid = db.new_id()
    conn.execute(insert(db.tax_estimates).values(
        id=eid, organization_id=org, tax_year=tax_year, jurisdiction=jurisdiction, period="year-to-date", gross_revenue_minor=revenue,
        deductible_expenses_minor=deductible, net_profit_minor=net, estimated_tax_minor=est_tax, reserve_minor=max(0, est_tax - paid),
        assumptions={"reserve_rate": reserve_rate(), "partial_business_use": 0.5, "method": "net profit x planning rate",
                     "estimated_payments_made_minor": paid},
        uncertainty=uncertainty, missing_evidence=missing, data_mode="simulated" if "simulated" in modes else ("live" if modes else "none")))
    agent = agent_by_key(conn, "tax_agent")
    audit.record(conn, org_id=org, actor_type="agent", actor_id=agent.id, action="tax.estimated", subject_type="tax_estimate", subject_id=eid,
                 detail={"tax_year": tax_year, "jurisdiction": jurisdiction, "missing_documents": len(missing)})
    femit(conn, "finance.tax_estimate_updated", {"estimate_id": eid, "tax_year": tax_year, "jurisdiction": jurisdiction,
                                                 "data_mode": "simulated" if "simulated" in modes else "live", "label": "tax estimate (labeled)"},
          agent_id=agent.id, simulated="simulated" in modes)
    if ship:
        logistics.create_package(conn, org_id=org, package_type="tax_review_package", origin="central-bank", destination="owners-tower",
                                 priority=4, carrier_agent_id=agent.id, subject_type="tax_estimate", subject_id=eid)
    return eid


def store_document(conn: Connection, *, org: str, tax_year: int, jurisdiction: str, doc_type: str, data: bytes, actor_id: str,
                   note: str | None) -> str:
    if doc_type not in DOC_TYPES:
        raise ValueError(f"doc_type must be one of {', '.join(DOC_TYPES)}")
    if len(data) > 10_000_000:
        raise ValueError("document larger than 10 MB")
    sha = hashlib.sha256(data).hexdigest()
    folder = get_settings().data_dir / "finance" / "documents" / org
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{sha}.bin"
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
    did = db.new_id()
    conn.execute(insert(db.tax_documents).values(id=did, organization_id=org, tax_year=tax_year, jurisdiction=jurisdiction, doc_type=doc_type,
                                                 status="RECEIVED", sha256=sha, storage_path=str(path), source="owner upload",
                                                 note=(note or "")[:300], data_mode="upload"))
    audit.record(conn, org_id=org, actor_type="owner", actor_id=actor_id, action="tax.document_received", subject_type="tax_document",
                 subject_id=did, detail={"doc_type": doc_type, "tax_year": tax_year, "sha256": sha})
    return did


def verify_document(conn: Connection, *, org: str, doc_id: str, actor_id: str) -> None:
    conn.execute(update(db.tax_documents).where(db.tax_documents.c.id == doc_id, db.tax_documents.c.organization_id == org).values(status="VERIFIED"))
    audit.record(conn, org_id=org, actor_type="owner", actor_id=actor_id, action="tax.document_verified", subject_type="tax_document", subject_id=doc_id)


def export_package(conn: Connection, org: str, tax_year: int, actor_id: str) -> bytes:
    """A zip for a qualified tax professional: categorized transactions with mapping hints, the latest estimate with its
    assumptions and uncertainty, the document checklist and deadlines. Labeled throughout."""
    rows = _rows(conn, org, tax_year)
    cats = {c.key: c for c in conn.execute(select(db.expense_categories).where(db.expense_categories.c.organization_id == org))}
    est = conn.execute(select(db.tax_estimates).where(db.tax_estimates.c.organization_id == org, db.tax_estimates.c.tax_year == tax_year)
                       .order_by(db.tax_estimates.c.created_at.desc())).first()
    simulated = any(r.data_mode == "simulated" for r in rows)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        t = io.StringIO()
        w = csv.writer(t)
        w.writerow(["date", "amount", "currency", "description", "merchant", "kind", "category", "tax_treatment", "mapping_hint",
                    "reconciliation", "data_mode"])
        for r in sorted(rows, key=lambda r: r.posted_at):
            c = cats.get(r.category_key or "uncategorized")
            w.writerow([r.posted_at[:10], f"{r.amount_minor / 100:.2f}", r.currency, r.description, r.merchant or "", r.kind, r.category_key,
                        c.tax_treatment if c else "", c.tax_line if c else "", r.reconciliation_status, r.data_mode])
        z.writestr("transactions.csv", t.getvalue())
        z.writestr("estimate.json", json.dumps(None if est is None else {
            "label": "ESTIMATE for planning only; not a tax return or tax advice",
            "tax_year": est.tax_year, "jurisdiction": est.jurisdiction, "gross_revenue": est.gross_revenue_minor / 100,
            "deductible_expenses": est.deductible_expenses_minor / 100, "net_profit": est.net_profit_minor / 100,
            "estimated_tax": est.estimated_tax_minor / 100, "remaining_reserve": est.reserve_minor / 100, "assumptions": est.assumptions,
            "uncertainty": est.uncertainty, "missing_evidence": est.missing_evidence, "data_mode": est.data_mode}, indent=2))
        z.writestr("documents.json", json.dumps({"checklist": expected_documents(conn, org, tax_year, rows), "received": [
            {"doc_type": d.doc_type, "status": d.status, "sha256": d.sha256, "jurisdiction": d.jurisdiction}
            for d in conn.execute(select(db.tax_documents).where(db.tax_documents.c.organization_id == org, db.tax_documents.c.tax_year == tax_year))]},
            indent=2))
        z.writestr("deadlines.json", json.dumps([d for j in jurisdictions() for d in deadlines(tax_year, j)], indent=2))
        z.writestr("README.txt", (
            f"AI Civilization tax review package, tax year {tax_year}.\n\n"
            + ("*** SIMULATED DATA: this package describes test data, not a real business. ***\n\n" if simulated else "")
            + "Prepared for review by a qualified tax professional. Figures are ESTIMATES; categories carry mapping hints, "
              "not determinations. Nothing in this package has been filed with any tax authority.\n"))
    audit.record(conn, org_id=org, actor_type="owner", actor_id=actor_id, action="tax.exported", subject_type="tax_year", subject_id=None,
                 detail={"tax_year": tax_year, "transactions": len(rows), "simulated": simulated})
    return buf.getvalue()
