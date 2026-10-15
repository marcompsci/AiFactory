"""Retention and deletion controls (THREAT_MODEL F16).

* CSV uploads are parsed in memory and never stored raw.
* Tax documents are stored (0600) under the data directory until the owner deletes them.
* Deleting a connection's data removes its accounts, transactions and sync runs and revokes it. The audit log keeps
  a "data deleted" entry (with counts, not contents), because the log itself is append-only.
"""
from __future__ import annotations

import os

from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import Connection

from services.core import db

from . import audit


def delete_connection_data(conn: Connection, *, org: str, connection_id: str, actor_id: str) -> dict:
    c = conn.execute(select(db.financial_connections).where(db.financial_connections.c.id == connection_id,
                                                            db.financial_connections.c.organization_id == org)).first()
    if c is None:
        raise ValueError("unknown connection")
    counts = {}
    for t in (db.financial_transactions, db.financial_accounts, db.financial_sync_runs):
        counts[t.name] = conn.execute(select(func.count()).select_from(t).where(t.c.connection_id == connection_id)).scalar()
    conn.execute(delete(db.financial_transactions).where(db.financial_transactions.c.connection_id == connection_id))
    conn.execute(delete(db.financial_sync_runs).where(db.financial_sync_runs.c.connection_id == connection_id))
    conn.execute(delete(db.financial_accounts).where(db.financial_accounts.c.connection_id == connection_id))
    if c.provider == "simulated":  # simulated extras belong to the simulated connection
        for t in (db.bills, db.subscriptions, db.invoices, db.revenue_sources):
            conn.execute(delete(t).where(t.c.organization_id == org, t.c.data_mode == "simulated"))
    conn.execute(update(db.financial_connections).where(db.financial_connections.c.id == connection_id).values(
        status="REVOKED", secret_ciphertext=None, last_error=None))
    audit.record(conn, org_id=org, actor_type="owner", actor_id=actor_id, action="data.deleted", subject_type="financial_connection",
                 subject_id=connection_id, detail=counts)
    return counts


def delete_tax_document(conn: Connection, *, org: str, doc_id: str, actor_id: str) -> None:
    d = conn.execute(select(db.tax_documents).where(db.tax_documents.c.id == doc_id, db.tax_documents.c.organization_id == org)).first()
    if d is None:
        raise ValueError("unknown document")
    others = conn.execute(select(func.count()).select_from(db.tax_documents).where(db.tax_documents.c.sha256 == d.sha256,
                                                                                    db.tax_documents.c.id != doc_id)).scalar()
    if d.storage_path and not others and os.path.exists(d.storage_path):
        os.remove(d.storage_path)
    conn.execute(delete(db.tax_documents).where(db.tax_documents.c.id == doc_id))
    audit.record(conn, org_id=org, actor_type="owner", actor_id=actor_id, action="tax.document_deleted", subject_type="tax_document",
                 subject_id=doc_id, detail={"doc_type": d.doc_type, "sha256": d.sha256})
