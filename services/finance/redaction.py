"""What leaves the bank (THREAT_MODEL F8, F9).

* `scrub` removes account/card/routing/tax-id-like numbers and emails from free text (applied on import).
* `for_model` builds the only view of a cost or transaction a model may see: vendor, category, rounded amount.
* `event_safe` is the payload shape for finance events: ids, statuses and labels, never money or accounts.
"""
from __future__ import annotations

import re

_PATTERNS = [
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[card/account]"),            # card and long account numbers
    (re.compile(r"\b\d{9}\b"), "[routing/tax id]"),                        # ABA routing numbers, SSN/EIN without dashes
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[ssn]"),
    (re.compile(r"\b\d{2}-\d{7}\b"), "[ein]"),
    (re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"), "[iban]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[email]"),
    (re.compile(r"(?i)\b(?:acct|account|card)\s*(?:no\.?|number|#)?\s*[:#]?\s*\d{4,}"), "[account]"),
]


def scrub(text: str | None) -> str:
    out = text or ""
    for p, rep in _PATTERNS:
        out = p.sub(rep, out)
    return out[:300]


def round_amount(minor: int) -> str:
    """'about $30' style: enough for reasoning about alternatives, nothing exact."""
    dollars = abs(minor) / 100
    if dollars < 10:
        return f"about ${dollars:.0f}"
    if dollars < 1000:
        return f"about ${round(dollars / 5) * 5:.0f}"
    return f"about ${round(dollars / 100) * 100:,.0f}"


def for_model(*, vendor: str, item: str, category: str | None, amount_minor: int, interval: str) -> dict:
    return {"vendor": scrub(vendor)[:60], "item": scrub(item)[:80], "category": category or "uncategorized",
            "approximate_cost": round_amount(amount_minor), "billing": interval}


EVENT_SAFE_KEYS = {"packet_id", "approval_id", "status", "from", "to", "origin", "package_id", "package_type", "classification",
                   "significant", "risk", "action_type", "decision", "connection_id", "sync_run_id", "kind", "provider", "data_mode",
                   "label", "reason_code", "tax_year", "jurisdiction", "bill_id", "estimate_id", "round", "agent_key", "inserted",
                   "duplicates", "coverage_gaps", "subject_type", "subject_id"}


def event_safe(payload: dict) -> dict:
    """Drop anything not on the allowlist. Amounts, balances, payees and account references never reach the stream."""
    return {k: v for k, v in payload.items() if k in EVENT_SAFE_KEYS}
