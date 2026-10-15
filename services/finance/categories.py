"""Expense categories and the rule-based categorizer (routine classification uses rules, not models).

`tax_line` is a mapping hint for a tax professional (US Schedule C). It is not tax advice.
"""
from __future__ import annotations

import re

from sqlalchemy import insert, select
from sqlalchemy.engine import Connection

from services.core import db

CATEGORIES = [
    ("revenue", "Revenue", "not_expense", None),
    ("refunds", "Refunds to customers", "not_expense", "Schedule C line 2 (returns and allowances)"),
    ("transfers", "Transfers between own accounts", "not_expense", None),
    ("software", "Software and subscriptions", "deductible", "Schedule C line 18/27a (office expense / other)"),
    ("ai_costs", "AI model usage", "deductible", "Schedule C line 27a (other expenses)"),
    ("payment_fees", "Payment processing fees", "deductible", "Schedule C line 10 (commissions and fees)"),
    ("store_commission", "App store commission", "deductible", "Schedule C line 10 (commissions and fees)"),
    ("bank_fees", "Bank fees", "deductible", "Schedule C line 27a (other expenses)"),
    ("office", "Office and coworking", "deductible", "Schedule C line 20b (rent: other business property)"),
    ("utilities", "Phone and internet", "partially_deductible", "Schedule C line 25 (utilities); business-use share only"),
    ("contractors", "Contract labor", "deductible", "Schedule C line 11 (contract labor)"),
    ("taxes", "Tax payments", "not_deductible", "Estimated tax payments are not business expenses"),
    ("bills", "Other bills", "deductible", "Schedule C line 27a (other expenses)"),
    ("uncategorized", "Uncategorized", "not_deductible", "Needs review before any deduction"),
]

RULES = [
    (re.compile(r"(?i)\b(irs|usataxpymt|franchise tax|ftb)\b"), "taxes", "tax"),
    (re.compile(r"(?i)\brefund\b"), "refunds", "refund"),
    (re.compile(r"(?i)\b(transfer|payout to|online transfer)\b"), "transfers", "transfer"),
    (re.compile(r"(?i)\b(stripe fee|processing fee|stripe processing)\b"), "payment_fees", "fee"),
    (re.compile(r"(?i)\b(app store commission|apple commission)\b"), "store_commission", "fee"),
    (re.compile(r"(?i)\b(maintenance fee|monthly service fee|wire fee|foreign transaction|overdraft|atm fee)\b"), "bank_fees", "fee"),
    (re.compile(r"(?i)\b(anthropic|openai)\b"), "ai_costs", "expense"),
    (re.compile(r"(?i)\b(github|vercel|figma|notion|google workspace|apple developer|sentry|slack|netlify)\b"), "software", "expense"),
    (re.compile(r"(?i)\b(cowork|wework|office rent)\b"), "office", "expense"),
    (re.compile(r"(?i)\b(comcast|xfinity|verizon|t-mobile|at&t|internet|phone)\b"), "utilities", "expense"),
    (re.compile(r"(?i)\b(upwork|contractor|fiverr)\b"), "contractors", "expense"),
    (re.compile(r"(?i)\b(stripe charge|stripe revenue|app store proceeds|invoice payment|payment from)\b"), "revenue", "revenue"),
]


def seed(conn: Connection, org_id: str) -> None:
    have = {r.key for r in conn.execute(select(db.expense_categories.c.key).where(db.expense_categories.c.organization_id == org_id))}
    for key, name, treatment, line in CATEGORIES:
        if key not in have:
            conn.execute(insert(db.expense_categories).values(id=db.new_id(), organization_id=org_id, key=key, name=name,
                                                              tax_treatment=treatment, tax_line=line))


def categorize(description: str, merchant: str | None, amount_minor: int, kind_hint: str | None = None,
               category_hint: str | None = None) -> tuple[str, str, bool]:
    """Returns (category_key, kind, is_fee). Hints from a structured source (processor fee lines) win over text."""
    if category_hint and kind_hint:
        return category_hint, kind_hint, kind_hint == "fee"
    text = f"{merchant or ''} {description}"
    for rx, cat, kind in RULES:
        if rx.search(text):
            if kind == "revenue" and amount_minor < 0:
                continue
            return cat, kind, kind == "fee"
    if kind_hint:
        return category_hint or ("revenue" if kind_hint == "revenue" else "uncategorized"), kind_hint, kind_hint == "fee"
    # Unknown money in is NOT assumed to be revenue (it could be a loan, a transfer or a deposit): it waits for review.
    return "uncategorized", ("other" if amount_minor > 0 else "expense"), False
