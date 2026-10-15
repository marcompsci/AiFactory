"""The executive financial dashboard (spec §5). Every figure says what it is (cash, revenue, profit estimate, tax
estimate, available balance), which data it came from, and how fresh and reconciled that data is. Missing data is
`null` plus a gap, never zero (THREAT_MODEL F13)."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import pstdev

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from services.core import db

from .sync import coverage

STALE_AFTER = timedelta(hours=24)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sum(rows, pred) -> int:
    return int(sum(r.amount_minor for r in rows if pred(r)))


def figures(rows) -> dict:
    revenue = _sum(rows, lambda r: r.kind == "revenue")
    refunds = _sum(rows, lambda r: r.kind == "refund")
    fees = _sum(rows, lambda r: r.kind == "fee")
    opex = _sum(rows, lambda r: r.kind == "expense")
    tax_paid = _sum(rows, lambda r: r.kind == "tax")
    inflow = _sum(rows, lambda r: r.kind != "transfer" and r.amount_minor > 0)
    outflow = _sum(rows, lambda r: r.kind != "transfer" and r.amount_minor < 0)
    gross = revenue + refunds + fees  # payment and store fees are a cost of earning the revenue
    return {
        "revenue_gross_minor": revenue, "refunds_minor": refunds, "fees_minor": fees, "operating_expenses_minor": opex,
        "gross_profit_estimate_minor": gross, "net_profit_estimate_minor": gross + opex, "tax_payments_minor": tax_paid,
        "cash_inflow_minor": inflow, "cash_outflow_minor": outflow, "net_cash_flow_minor": inflow + outflow,
        "ai_costs_ledger_minor": _sum(rows, lambda r: r.category_key == "ai_costs"),
        "uncategorized_count": sum(1 for r in rows if r.category_key == "uncategorized"),
        "transactions": len(rows),
    }


def forecast(conn: Connection, org: str) -> dict | None:
    """90-day cash projection from the last three full months' net cash flow (transfers excluded). An estimate."""
    start = (_now().replace(day=1) - timedelta(days=95)).replace(day=1)
    end = _now().replace(day=1)
    rows = conn.execute(select(db.financial_transactions.c.posted_at, db.financial_transactions.c.amount_minor, db.financial_transactions.c.kind)
                        .where(db.financial_transactions.c.organization_id == org, db.financial_transactions.c.posted_at >= start.isoformat(),
                               db.financial_transactions.c.posted_at < end.isoformat())).fetchall()
    by_month: dict[str, int] = defaultdict(int)
    for r in rows:
        if r.kind != "transfer":
            by_month[r.posted_at[:7]] += r.amount_minor
    if len(by_month) < 2:
        return None
    vals = list(by_month.values())
    avg = sum(vals) / len(vals)
    spread = pstdev(vals) if len(vals) > 1 else abs(avg) * 0.25
    cash = conn.execute(select(func.sum(db.financial_accounts.c.available_balance_minor)).where(
        db.financial_accounts.c.organization_id == org, db.financial_accounts.c.account_type.in_(["checking", "savings"]))).scalar()
    if cash is None:
        return None
    points = [{"days": d, "expected_minor": int(cash + avg * d / 30), "low_minor": int(cash + (avg - spread) * d / 30),
               "high_minor": int(cash + (avg + spread) * d / 30)} for d in (30, 60, 90)]
    return {"basis_months": sorted(by_month), "avg_monthly_net_minor": int(avg), "starting_cash_minor": int(cash), "points": points,
            "label": "ESTIMATE from recent months; not a guarantee", "method": "trailing average with ±1 standard deviation band"}


def build(conn: Connection, org: str) -> dict:
    now = _now()
    accounts = conn.execute(select(db.financial_accounts).where(db.financial_accounts.c.organization_id == org)).fetchall()
    tx = db.financial_transactions
    last30 = conn.execute(select(tx).where(tx.c.organization_id == org, tx.c.posted_at >= (now - timedelta(days=30)).isoformat())).fetchall()
    ytd = conn.execute(select(tx).where(tx.c.organization_id == org, tx.c.posted_at >= now.replace(month=1, day=1, hour=0, minute=0,
                                                                                                   second=0, microsecond=0).isoformat())).fetchall()
    modes = sorted({r[0] for r in conn.execute(select(tx.c.data_mode).where(tx.c.organization_id == org).distinct())})
    recon = {r[0]: r[1] for r in conn.execute(select(tx.c.reconciliation_status, func.count()).where(tx.c.organization_id == org)
                                              .group_by(tx.c.reconciliation_status))}
    cov = coverage(conn, org)
    fresh = []
    for c in cov["connections"]:
        last = datetime.fromisoformat(c["last_sync_at"]) if c["last_sync_at"] else None
        fresh.append({**c, "stale": last is None or now - last > STALE_AFTER})
    bills = conn.execute(select(db.bills).where(db.bills.c.organization_id == org, db.bills.c.status != "PAID").order_by(db.bills.c.due_at)).fetchall()
    subs = conn.execute(select(db.subscriptions).where(db.subscriptions.c.organization_id == org, db.subscriptions.c.status == "ACTIVE")
                        .order_by(db.subscriptions.c.renews_at)).fetchall()
    est = conn.execute(select(db.tax_estimates).where(db.tax_estimates.c.organization_id == org).order_by(db.tax_estimates.c.created_at.desc())).first()
    savings = conn.execute(select(db.savings_opportunities).where(db.savings_opportunities.c.organization_id == org)
                           .order_by(db.savings_opportunities.c.created_at.desc()).limit(20)).fetchall()
    usage = conn.execute(select(func.coalesce(func.sum(db.usage_records.c.estimated_cost_usd), 0.0)).where(
        db.usage_records.c.organization_id == org, db.usage_records.c.created_at >= (now - timedelta(days=30)).isoformat())).scalar()
    has_data = bool(accounts or last30 or ytd)

    def acct(a) -> dict:
        return {"id": a.id, "name": a.name, "mask": a.mask, "type": a.account_type, "currency": a.currency,
                "current_balance_minor": a.current_balance_minor, "available_balance_minor": a.available_balance_minor,
                "as_of": a.balance_as_of, "data_mode": a.data_mode}

    cash_avail = [a.available_balance_minor for a in accounts if a.account_type in ("checking", "savings") and a.available_balance_minor is not None]
    return {
        "has_data": has_data,
        "data_modes": modes,
        "simulated": "simulated" in modes,
        "labels": {
            "available_balance": "Money you can spend now in bank accounts (processor and store balances are listed separately).",
            "cash_flow": "Money in minus money out over the period, excluding moves between your own accounts.",
            "revenue": "Gross sales before refunds and fees.",
            "profit": "ESTIMATE: revenue minus refunds, fees and categorized operating expenses. Excludes taxes, depreciation and uncategorized items.",
            "tax": "ESTIMATE for planning a reserve, not a tax calculation. Review with a qualified tax professional.",
        },
        "accounts": [acct(a) for a in accounts],
        "available_cash_minor": sum(cash_avail) if cash_avail else None,
        "last_30_days": figures(last30) if has_data else None,
        "year_to_date": figures(ytd) if has_data else None,
        "ai_operating_costs": {"ledger_last_30_minor": figures(last30)["ai_costs_ledger_minor"] if has_data else None,
                               "agents_estimated_usd_last_30": round(float(usage or 0), 4),
                               "label": "Ledger = what your AI provider billed. Agents = this app's own estimate of its model usage."},
        "bills": [{"id": b.id, "payee": b.payee, "amount_minor": b.amount_minor, "currency": b.currency, "due_at": b.due_at,
                   "autopay": bool(b.autopay), "status": b.status, "data_mode": b.data_mode} for b in bills],
        "subscriptions": [{"id": s.id, "vendor": s.vendor, "plan": s.plan, "amount_minor": s.amount_minor, "interval": s.interval,
                           "renews_at": s.renews_at, "contract_terms": s.contract_terms, "data_mode": s.data_mode} for s in subs],
        "subscriptions_monthly_minor": sum(s.amount_minor if s.interval == "month" else s.amount_minor // 12 for s in subs) if subs else None,
        "tax": None if est is None else {"id": est.id, "tax_year": est.tax_year, "jurisdiction": est.jurisdiction, "period": est.period,
                                         "estimated_tax_minor": est.estimated_tax_minor, "reserve_minor": est.reserve_minor,
                                         "uncertainty": est.uncertainty, "missing_evidence": est.missing_evidence, "created_at": est.created_at,
                                         "data_mode": est.data_mode, "label": "ESTIMATE"},
        "forecast": forecast(conn, org),
        "savings": [{"id": s.id, "packet_id": s.packet_id, "title": s.title, "current_annual_minor": s.current_annual_minor,
                     "proposed_annual_minor": s.proposed_annual_minor, "migration_cost_minor": s.migration_cost_minor,
                     "first_year_saving_minor": s.first_year_saving_minor, "confidence": s.confidence, "status": s.status,
                     "data_mode": s.data_mode} for s in savings],
        "reconciliation": {"matched": recon.get("MATCHED", 0), "unreconciled": recon.get("UNRECONCILED", 0),
                           "needs_review": recon.get("NEEDS_REVIEW", 0)},
        "freshness": fresh,
        "coverage": {"connected_kinds": cov["connected_kinds"], "gaps": cov["gaps"], "from": cov["from"], "to": cov["to"]},
        "generated_at": now.isoformat(),
    }
