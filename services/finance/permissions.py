"""Who may do what in the bank (THREAT_MODEL F1, F6, F7)."""
from __future__ import annotations

from fastapi import HTTPException

from services.core.auth import Principal

# Every action that moves money, binds the owner, or speaks officially. None is ever automatic.
APPROVAL_ACTIONS = ("purchase", "payment", "transfer", "official_submission", "tax_filing", "financial_publication", "banking_change")

# Tools only finance-department agents may hold (ledger reads, classification, proposals, gated execution).
FINANCE_TOOLS = {"read_ledger_summary", "classify_cost", "propose_financial_action", "execute_financial_action",
                 "record_cost_findings", "research_cost_alternatives"}
# research_cost_alternatives is held by the Research Division's Haiku researchers; it sees only the redacted packet view.
RESEARCH_SHARED_TOOLS = {"research_cost_alternatives"}
# What any agent may do: ask the bank for something. It reads nothing.
REQUEST_TOOLS = {"request_purchase"}

FINANCE_READ_ROLES = ("owner", "admin")


def require_finance(p: Principal) -> None:
    if p.role not in FINANCE_READ_ROLES:
        raise HTTPException(status_code=403, detail="financial data is limited to owners and admins")


def require_owner(p: Principal) -> None:
    if p.role != "owner":
        raise HTTPException(status_code=403, detail="only the owner can do this")
