# V5.1 acceptance run: free-alternative investigation

Recorded 2026-10-14 19:42:12 PDT by tests/integration/test_v51_investigation.py.
Candidates come from the bundled **FIXTURE** catalog (labeled everywhere). The sandbox runs real pytest against **FIXTURE compatibility kits** that model each candidate's documented behavior; no downloaded software is executed. Financial data is **SIMULATED**.

1. Owner chose **RESEARCH_FREE_ALTERNATIVE**. The purchase request stayed `PENDING_OWNER_DECISION` with its approval requests untouched; a second concurrent investigation was refused (409).
2. Savings Investigation Packet: central-bank→data-observatory → data-observatory→central-bank → central-bank→code-forge → code-forge→sentinel-citadel → sentinel-citadel→nexus-spire → nexus-spire→owners-tower (each leg delivered by the backend).
3. 5 candidates, each with source URL, license, pricing evidence (source + as-of), features, maintenance, documentation, limitations, estimated costs and confidence:
   - #1 **Penpot** (MPL-2.0) score 0.81, three-year $200, shortlisted
   - #2 **Lunacy** (Proprietary freeware) score 0.62, three-year $150, shortlisted
   - #3 **Excalidraw** (MIT) score 0.48, three-year $300, shortlisted
   - #4 **Inkscape** (GPL-2.0-or-later) score 0.40, three-year $300
   - #5 **Akira** (GPL-3.0) score 0.29, three-year $400
4. Code Forge ran the requirements in a disposable `process` sandbox (network isolated: True): **FAILED**, 4 passed / 1 failed / 0 errors. Failed: figma_import. QA: gaps_found: 4 of 5 requirements met; gaps: Open existing Figma files
5. General Manager: **keep_request_or_accept_gaps**: Penpot met 4 of 5 requirements. Buying Figma keeps them all; switching would save about $340 over three years but accept the gaps QA listed. (authorizes_transaction = false; approvals unchanged; no money moved).
6. Cost comparison delivered to the owner: Lunacy $150/3y; Penpot $200/3y; Excalidraw $300/3y; Inkscape $300/3y; Akira $400/3y; Figma (requested) $540/3y
7. Only after a new, explicit owner approval with step-up did the Bill Manager execute the Figma purchase (simulated).
8. Realtime events: REQUESTED → RESEARCHING → EVALUATING → TESTING → MANAGER_REVIEW → AWAITING_OWNER. No amounts or recipients in any finance or package event.

## Audit trail

| # | action | actor |
|---|---|---|
| 60 | investigation.requested | owner |
| 62 | investigation.status_changed | system |
| 63 | investigation.candidates_found | agent |
| 64 | investigation.status_changed | system |
| 65 | investigation.scored | agent |
| 66 | investigation.status_changed | system |
| 67 | investigation.sandbox_evaluated | agent |
| 68 | investigation.qa_reviewed | agent |
| 69 | investigation.status_changed | system |
| 70 | investigation.manager_recommendation | agent |
| 71 | investigation.status_changed | system |
