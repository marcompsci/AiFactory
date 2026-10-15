"""Syncing a connection: fetch, normalize, deduplicate, categorize, reconcile, report coverage, detect fees.

* Idempotent (THREAT_MODEL F17): `dedupe_key = sha256(connection | external id)`, unique per organization.
* Descriptions are scrubbed of account-like numbers before storage (F8). Account ids are stored as keyed HMACs (F11).
* Failures are recorded on the sync run and the connection, never papered over with made-up rows (F13).
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection

from services.core import db
from services.core.events import transaction

from . import audit, categories, crypto
from . import connectors as C
from . import packets as P
from .events import femit
from .redaction import scrub

log = logging.getLogger("aiciv.finance.sync")


def fee_review_min_minor() -> int:
    import os

    return int(float(os.environ.get("AICIV_FINANCE_FEE_REVIEW_MIN_USD", "20")) * 100)


def dedupe_key(connection_id: str, external_id: str) -> str:
    return hashlib.sha256(f"{connection_id}|{external_id}".encode()).hexdigest()


def run(connection_id: str, *, actor_id: str | None = None, upload: bytes | None = None, batch: C.SyncBatch | None = None) -> dict:
    with db.get_engine().connect() as conn:
        c = conn.execute(select(db.financial_connections).where(db.financial_connections.c.id == connection_id)).first()
    if c is None:
        raise ValueError("unknown connection")
    if c.status != "ACTIVE":
        raise PermissionError("this connection is not authorized; the owner must authorize it first")
    run_id = db.new_id()
    with transaction() as conn:
        conn.execute(insert(db.financial_sync_runs).values(id=run_id, organization_id=c.organization_id, connection_id=c.id, status="RUNNING",
                                                           data_mode=c.data_mode))
    try:
        if batch is None:
            secret = crypto.decrypt(c.secret_ciphertext) if c.secret_ciphertext else None
            since = c.last_sync_at
            cursor = json.loads(secret).get("cursor") if (c.provider == "plaid" and secret) else None
            batch = C.fetch(c.provider, secret, since=since, cursor=cursor, upload=upload)
    except C.AdapterError as exc:
        with transaction() as conn:
            conn.execute(update(db.financial_sync_runs).where(db.financial_sync_runs.c.id == run_id).values(
                status="FAILED", finished_at=db.utcnow(), errors=[f"{exc.kind}: {exc}"]))
            conn.execute(update(db.financial_connections).where(db.financial_connections.c.id == c.id).values(
                last_error=f"{exc.kind}: {exc}"[:500], status="ERROR" if exc.kind == "auth" else c.status))
            audit.record(conn, org_id=c.organization_id, actor_type="system", actor_id=None, action="sync.failed",
                         subject_type="financial_connection", subject_id=c.id, detail={"kind": exc.kind, "error": str(exc)[:300]})
            femit(conn, "finance.sync_failed", {"connection_id": c.id, "sync_run_id": run_id, "provider": c.provider,
                                                "reason_code": exc.kind, "data_mode": c.data_mode}, simulated=c.data_mode == "simulated")
        return {"sync_run_id": run_id, "status": "FAILED", "error": str(exc), "kind": exc.kind}
    with transaction() as conn:
        result = _apply(conn, c, run_id, batch)
        if c.provider == "plaid" and batch.cursor and c.secret_ciphertext:
            cred = json.loads(crypto.decrypt(c.secret_ciphertext))
            cred["cursor"] = batch.cursor
            conn.execute(update(db.financial_connections).where(db.financial_connections.c.id == c.id).values(
                secret_ciphertext=crypto.encrypt(json.dumps(cred))))
    return result


def _account_ids(conn: Connection, c, batch: C.SyncBatch) -> dict[str | None, str]:
    ids: dict[str | None, str] = {}
    for a in batch.accounts:
        h = crypto.ref_hmac(f"{c.provider}:{a.external_id}")
        row = conn.execute(select(db.financial_accounts.c.id).where(db.financial_accounts.c.organization_id == c.organization_id,
                                                                    db.financial_accounts.c.connection_id == c.id,
                                                                    db.financial_accounts.c.external_ref_hmac == h)).first()
        vals = dict(name=scrub(a.name)[:80], mask=(a.mask or "")[-4:] or None, account_type=a.account_type, currency=a.currency,
                    current_balance_minor=a.current_balance_minor, available_balance_minor=a.available_balance_minor,
                    balance_as_of=db.utcnow(), data_mode=batch.data_mode)
        if row:
            conn.execute(update(db.financial_accounts).where(db.financial_accounts.c.id == row.id).values(**vals))
            ids[a.external_id] = row.id
        else:
            aid = db.new_id()
            conn.execute(insert(db.financial_accounts).values(id=aid, organization_id=c.organization_id, connection_id=c.id,
                                                              external_ref_hmac=h, **vals))
            ids[a.external_id] = aid
    return ids


def _apply(conn: Connection, c, run_id: str, batch: C.SyncBatch) -> dict:
    org = c.organization_id
    categories.seed(conn, org)
    accounts = _account_ids(conn, c, batch)
    inserted = dupes = 0
    new_fee_ids: list[str] = []
    for t in batch.transactions:
        key = dedupe_key(c.id, t.external_id or f"{t.posted_at}|{t.amount_minor}|{t.description}")
        if conn.execute(select(db.financial_transactions.c.id).where(db.financial_transactions.c.organization_id == org,
                                                                     db.financial_transactions.c.dedupe_key == key)).first():
            dupes += 1
            continue
        cat, kind, is_fee = categories.categorize(t.description, t.merchant, t.amount_minor, t.kind_hint, t.category_hint)
        tid = db.new_id()
        conn.execute(insert(db.financial_transactions).values(
            id=tid, organization_id=org, connection_id=c.id, account_id=accounts.get(t.account_external_id), dedupe_key=key,
            external_id=(t.external_id or "")[:200] or None, posted_at=t.posted_at, amount_minor=int(t.amount_minor), currency=t.currency,
            description=scrub(t.description), merchant=scrub(t.merchant)[:80] if t.merchant else None, category_key=cat, kind=kind,
            is_fee=int(is_fee), data_mode=batch.data_mode,
            reconciliation_status="UNRECONCILED" if kind not in ("other",) else "NEEDS_REVIEW"))
        inserted += 1
        if is_fee:
            new_fee_ids.append(tid)
    _apply_extras(conn, org, c, batch)
    _mark_recurring(conn, org)
    matched = reconcile(conn, org)
    coverage = {"from": batch.covered_from, "to": batch.covered_to, "provider": c.provider, "kind": C.PROVIDERS[c.provider].kind,
                "accounts": len(batch.accounts), "warnings": batch.errors[:20]}
    status = "PARTIAL" if (batch.rejected or batch.errors) else "COMPLETED"
    conn.execute(update(db.financial_sync_runs).where(db.financial_sync_runs.c.id == run_id).values(
        status=status, finished_at=db.utcnow(), fetched=len(batch.transactions), inserted=inserted, duplicates=dupes,
        rejected=batch.rejected, coverage=coverage, errors=batch.errors[:50]))
    conn.execute(update(db.financial_connections).where(db.financial_connections.c.id == c.id).values(last_sync_at=db.utcnow(), last_error=None))
    audit.record(conn, org_id=org, actor_type="system", actor_id=None, action="sync.completed", subject_type="financial_connection",
                 subject_id=c.id, detail={"inserted": inserted, "duplicates": dupes, "rejected": batch.rejected, "matched": matched})
    femit(conn, "finance.sync_completed", {"connection_id": c.id, "sync_run_id": run_id, "provider": c.provider, "inserted": inserted,
                                           "duplicates": dupes, "status": status, "data_mode": batch.data_mode},
          simulated=batch.data_mode == "simulated")
    packets = detect_fees(conn, org, batch.data_mode) if new_fee_ids else []
    return {"sync_run_id": run_id, "status": status, "fetched": len(batch.transactions), "inserted": inserted, "duplicates": dupes,
            "rejected": batch.rejected, "reconciled": matched, "fee_reviews_opened": len(packets), "errors": batch.errors[:20]}


def _apply_extras(conn: Connection, org: str, c, batch: C.SyncBatch) -> None:
    ex = batch.extras or {}
    for b in ex.get("bills", []):
        if not conn.execute(select(db.bills.c.id).where(db.bills.c.organization_id == org, db.bills.c.payee == b["payee"],
                                                        db.bills.c.status != "PAID")).first():
            conn.execute(insert(db.bills).values(id=db.new_id(), organization_id=org, currency="USD", status="UPCOMING",
                                                 data_mode=batch.data_mode, **b))
    for s in ex.get("subscriptions", []):
        if not conn.execute(select(db.subscriptions.c.id).where(db.subscriptions.c.organization_id == org, db.subscriptions.c.vendor == s["vendor"],
                                                                db.subscriptions.c.plan == s["plan"])).first():
            renews = datetime.now(timezone.utc) + timedelta(days=12 if s["interval"] == "month" else 140)
            conn.execute(insert(db.subscriptions).values(id=db.new_id(), organization_id=org, currency="USD", status="ACTIVE",
                                                         renews_at=renews.isoformat(), data_mode=batch.data_mode, **s))
    for r in ex.get("revenue_sources", []):
        if not conn.execute(select(db.revenue_sources.c.id).where(db.revenue_sources.c.organization_id == org,
                                                                  db.revenue_sources.c.platform == r["platform"],
                                                                  db.revenue_sources.c.name == r["name"])).first():
            conn.execute(insert(db.revenue_sources).values(id=db.new_id(), organization_id=org, connection_id=c.id, data_mode=batch.data_mode, **r))
    for i in ex.get("invoices", []):
        if not conn.execute(select(db.invoices.c.id).where(db.invoices.c.organization_id == org, db.invoices.c.counterparty == i["counterparty"],
                                                           db.invoices.c.status == "OPEN")).first():
            conn.execute(insert(db.invoices).values(id=db.new_id(), organization_id=org, currency="USD", status="OPEN",
                                                    issued_at=db.utcnow(), data_mode=batch.data_mode, **i))


def _merchant_key(t) -> str:
    return (t.merchant or t.description.split(" ")[1] if t.description else "").lower()


def _mark_recurring(conn: Connection, org: str) -> None:
    """Same merchant, similar amount (±25%), seen in 2+ different months → recurring."""
    rows = conn.execute(select(db.financial_transactions.c.id, db.financial_transactions.c.merchant, db.financial_transactions.c.description,
                               db.financial_transactions.c.amount_minor, db.financial_transactions.c.posted_at)
                        .where(db.financial_transactions.c.organization_id == org, db.financial_transactions.c.amount_minor < 0,
                               db.financial_transactions.c.recurring == 0)).fetchall()
    groups: dict[tuple, list] = defaultdict(list)
    for r in rows:
        groups[((r.merchant or "").lower(), " ".join(r.description.split()[:3]).lower())].append(r)
    for _, items in groups.items():
        months = {i.posted_at[:7] for i in items}
        amounts = [abs(i.amount_minor) for i in items]
        if len(months) >= 2 and max(amounts) <= 1.25 * min(amounts):
            conn.execute(update(db.financial_transactions).where(db.financial_transactions.c.id.in_([i.id for i in items])).values(recurring=1))


def reconcile(conn: Connection, org: str) -> int:
    """Match unreconciled payments to bills, subscriptions and transfers. Unmatched rows stay UNRECONCILED; nothing is forced."""
    n = 0
    txns = conn.execute(select(db.financial_transactions).where(db.financial_transactions.c.organization_id == org,
                                                                db.financial_transactions.c.reconciliation_status == "UNRECONCILED")).fetchall()
    subs = conn.execute(select(db.subscriptions).where(db.subscriptions.c.organization_id == org)).fetchall()
    for t in txns:
        hit = None
        if t.kind == "transfer":
            hit = ("transfer", None)
        elif t.kind == "revenue" or t.kind == "fee" or t.kind == "refund":
            hit = ("processor_statement", None) if t.merchant in ("Stripe", "Apple") else None
        elif t.kind == "tax":
            hit = ("tax_payment", None)
        else:
            for s in subs:
                if s.vendor.lower() in (t.merchant or t.description).lower() and abs(abs(t.amount_minor) - s.amount_minor) <= max(100, s.amount_minor // 10):
                    hit = ("subscription", s.id)
                    break
            if hit is None:
                b = conn.execute(select(db.bills).where(db.bills.c.organization_id == org, db.bills.c.amount_minor == -t.amount_minor)).fetchall()
                for bill in b:
                    if bill.payee.split()[0].lower() in t.description.lower():
                        hit = ("bill", bill.id)
                        break
        if hit:
            conn.execute(update(db.financial_transactions).where(db.financial_transactions.c.id == t.id).values(
                reconciliation_status="MATCHED", matched_type=hit[0], matched_id=hit[1]))
            n += 1
    return n


def detect_fees(conn: Connection, org: str, data_mode: str) -> list[str]:
    """One cost review per kind of fee (merchant + fee description), unless one is already open or was decided in the
    last 90 days. Recurring fees use the latest monthly total; unusual amounts (>3x the median) are flagged high risk."""
    since = (datetime.now(timezone.utc) - timedelta(days=180)).isoformat()
    fees = conn.execute(select(db.financial_transactions).where(db.financial_transactions.c.organization_id == org,
                                                                db.financial_transactions.c.is_fee == 1,
                                                                db.financial_transactions.c.posted_at >= since)).fetchall()
    groups: dict[str, list] = defaultdict(list)
    for f in fees:
        label = " ".join(w for w in f.description.replace("SIM ", "").split() if not w.startswith(("ch_", "txn_", "po_")))[:40]
        label = " ".join(label.split()[:3])
        groups[f"{f.merchant or 'unknown'}|{label}"].append(f)
    opened = []
    recent = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    for key, items in groups.items():
        merchant, label = key.split("|", 1)
        exists = conn.execute(select(db.cost_review_packets.c.id).where(
            db.cost_review_packets.c.organization_id == org, db.cost_review_packets.c.origin == "fee_detected",
            db.cost_review_packets.c.vendor == merchant, db.cost_review_packets.c.item == label,
            (db.cost_review_packets.c.status.notin_(["REJECTED", "CLOSED", "EXECUTED"])) | (db.cost_review_packets.c.updated_at >= recent))).first()
        if exists:
            continue
        by_month: dict[str, int] = defaultdict(int)
        for i in items:
            by_month[i.posted_at[:7]] += -i.amount_minor
        months = sorted(by_month)
        latest = by_month[months[-1]]
        interval = "month" if len(months) >= 2 else "one_time"
        unusual = len(months) >= 3 and latest > 3 * median(by_month[m] for m in months[:-1])
        if P.annualize(latest, interval) < fee_review_min_minor() and not unusual:
            continue
        newest = max(items, key=lambda i: i.posted_at)
        pid = P.create(conn, org_id=org, origin="fee_detected", vendor=merchant, item=label, amount_minor=int(latest), currency=newest.currency,
                       interval=interval, justification=None, requested_by_agent_id=_auditor_id(conn), request_mission_id=None,
                       subject_type="transaction", subject_id=newest.id, data_mode=data_mode, unusual=unusual)
        femit(conn, "finance.fee_detected", {"packet_id": pid, "subject_type": "transaction", "subject_id": newest.id, "data_mode": data_mode,
                                             "label": "fee detected"}, agent_id=_auditor_id(conn), simulated=data_mode == "simulated")
        opened.append(pid)
    return opened


def _auditor_id(conn: Connection) -> str | None:
    return conn.execute(select(db.agents.c.id).where(db.agents.c.key == "expense_auditor")).scalar()


def coverage(conn: Connection, org: str) -> dict:
    """What the dashboard knows and, as importantly, what it doesn't (THREAT_MODEL F13)."""
    conns = conn.execute(select(db.financial_connections).where(db.financial_connections.c.organization_id == org,
                                                                db.financial_connections.c.status.in_(["ACTIVE", "ERROR"]))).fetchall()
    have = {C.PROVIDERS[c.provider].kind for c in conns if c.provider in C.PROVIDERS and c.status == "ACTIVE"}
    if any(c.provider == "simulated" and c.status == "ACTIVE" for c in conns):
        have |= {"bank_feed", "card_feed", "payment_processor", "app_store"}
    gaps = [k for k in C.SOURCE_KINDS if k not in have and k != "upload"]
    span = conn.execute(select(func.min(db.financial_transactions.c.posted_at), func.max(db.financial_transactions.c.posted_at))
                        .where(db.financial_transactions.c.organization_id == org)).first()
    return {"connected_kinds": sorted(have), "gaps": gaps, "from": span[0], "to": span[1],
            "connections": [{"id": c.id, "provider": c.provider, "status": c.status, "last_sync_at": c.last_sync_at, "last_error": c.last_error,
                             "data_mode": c.data_mode} for c in conns]}
