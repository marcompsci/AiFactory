# V5.0 acceptance run: AI Central Bank fee review

Recorded 2026-10-14 18:11:29 PDT by tests/integration/test_v5_acceptance.py.
Financial data: **SIMULATED** (labeled in every row, response and export). Alternatives come from the bundled **fixture** vendor catalog. No model key: agent text is templated and labeled `[simulation]`.

0. Loaded a simulated ledger: 176 transactions; the Expense Auditor opened 4 fee review(s).
1. Kade (Developer) requested **Figma Professional (per editor)** at $15.00/month: classified *recurring*, significant=True, risk=medium.
2. Packages: `purchase_request` code-forge→central-bank → `fee_research_request` central-bank→data-observatory → `savings_recommendation` data-observatory→central-bank → `purchase_request` central-bank→nexus-spire → `owner_approval_request` nexus-spire→owners-tower.
3. Research: 3 options from the fixture catalog. Recommendation: **choose_alternative**: Penpot (Cloud (free tier)) costs less over three years, migration included. Compatibility is partial: check the notes before switching.
4. General Manager (rules): forward.
5. Refused: approval without step-up (401), with a mismatched payload hash (409), and with a step-up token issued for another action (401). Nothing was bought.
6. Owner asked for more research → `fee_research_request` Owner's Tower→Data Observatory → second round (by Wren) → back through the bank and the GM to the tower.
7. Owner approved **Penpot** (step-up: TOTP). The Bill Manager's execution was re-checked at the tool boundary and recorded as **simulated** (SIM-15a16c07). The other option was invalidated.
8. A Sentry request was **rejected** and a Vercel request **deferred** then reopened (fresh approval requests, new expiry). Neither bought anything: 2 + 4 approvals, none executed.
9. 912 events, all valid against the v1 envelope schema. The packet passed through AT_BANK → RESEARCH_REQUESTED → RESEARCHING → FINDINGS_RETURNED → GM_REVIEW → OWNER_DECISION → RESEARCH_REQUESTED → RESEARCHING → FINDINGS_RETURNED → GM_REVIEW → OWNER_DECISION → APPROVED → EXECUTED. Finance and package events carry no amounts, balances, recipients or account references.
10. Financial audit log: 124 hash-chained entries, chain verified.

## Packet timeline (from the bank's own audit trail)

| # | action | actor | detail |
|---|---|---|---|
| 9 | packet.created | agent | {} |
| 18 | packet.status_changed | system | {"from": "SUBMITTED", "to": "AT_BANK", "reason": "received at the AI Central Bank"} |
| 19 | packet.status_changed | system | {"from": "AT_BANK", "to": "RESEARCH_REQUESTED", "reason": "sent to the Research Division"} |
| 26 | packet.status_changed | system | {"from": "RESEARCH_REQUESTED", "to": "RESEARCHING", "reason": "research mission started"} |
| 29 | research.completed | agent | {"category": "design_tools", "count": 3} |
| 39 | packet.status_changed | system | {"from": "RESEARCHING", "to": "FINDINGS_RETURNED", "reason": "findings received by the Savings Strategist"} |
| 48 | analysis.recorded | agent | {"action": "choose_alternative"} |
| 50 | packet.classified | agent | {} |
| 53 | approval.requested | agent | {} |
| 54 | approval.requested | agent | {} |
| 55 | packet.status_changed | system | {"from": "FINDINGS_RETURNED", "to": "GM_REVIEW", "reason": "significant: escalated to the General Manager"} |
| 59 | gm.reviewed | agent | {"outcome": "forward"} |
| 60 | packet.status_changed | system | {"from": "GM_REVIEW", "to": "OWNER_DECISION", "reason": "General Manager forwarded it to the owner"} |
| 62 | decision.refused | owner | {"reason": "step-up verification required: this action needs step-up verification"} |
| 70 | decision.refused | owner | {"reason": "what you reviewed is not what is on record (stale or modified request)"} |
| 71 | decision.refused | owner | {"reason": "step-up verification required: step-up token was issued for a different action"} |
| 72 | approval.more_research | owner | {"from": "REQUESTED", "reason": "check self-hosted options too"} |
| 73 | approval.more_research | owner | {"from": "REQUESTED", "reason": "check self-hosted options too"} |
| 74 | packet.status_changed | owner | {"from": "OWNER_DECISION", "to": "RESEARCH_REQUESTED", "reason": "owner asked for more research"} |
| 75 | packet.status_changed | system | {"from": "RESEARCH_REQUESTED", "to": "RESEARCHING", "reason": "research mission started"} |
| 76 | research.completed | agent | {"category": "design_tools", "count": 3} |
| 77 | packet.status_changed | system | {"from": "RESEARCHING", "to": "FINDINGS_RETURNED", "reason": "findings received by the Savings Strategist"} |
| 78 | analysis.recorded | agent | {"action": "choose_alternative"} |
| 79 | packet.classified | agent | {} |
| 80 | approval.requested | agent | {} |
| 81 | approval.requested | agent | {} |
| 82 | packet.status_changed | system | {"from": "FINDINGS_RETURNED", "to": "GM_REVIEW", "reason": "significant: escalated to the General Manager"} |
| 83 | gm.reviewed | agent | {"outcome": "forward"} |
| 84 | packet.status_changed | system | {"from": "GM_REVIEW", "to": "OWNER_DECISION", "reason": "General Manager forwarded it to the owner"} |
| 85 | approval.approved | owner | {"from": "REQUESTED", "reason": "approve"} |
| 86 | approval.invalidated | system | {"from": "REQUESTED", "reason": "owner decided option 805ea1ca-792a-4914-96bc-b3d5065eb515"} |
| 87 | packet.status_changed | owner | {"from": "OWNER_DECISION", "to": "APPROVED", "reason": "owner approved (step-up verified)"} |
| 88 | approval.executed | agent | {"execution_mode": "simulated"} |
| 89 | packet.status_changed | system | {"from": "APPROVED", "to": "EXECUTED", "reason": "owner-approved action carried out"} |
