# Implementation plan

| Phase | Scope | Status |
|---|---|---|
| 1 Foundation | monorepo, contracts, migrations, API, auth, Docker, CI | done (Postgres path unverified) |
| 2 3D world | city, six districts, cameras, avatars, navigation, interiors (focus + see-through) | done for the slice; GLB assets not used yet |
| 3 Live operations | event store, outbox, SSE, reconciliation, world sync, inspector, feed | done |
| 4 AI orchestration | model adapters, durable missions, delegation, checkpoints, memory | done with the D3 substitution; LangGraph + model-planned graphs pending |
| 5 Real execution | sandboxed repo tools, worktrees, tests, artifacts, approvals | done for the local sample repo; GitHub App adapter implemented, untested |
| 6 Hardening | security tests, budgets, recovery, responsive, deployment | partially done; see PROGRESS.md |

## Next milestones, in order

1. **Native iOS shell** (Capacitor wrapping the PWA, then native widgets/notifications for approvals).
2. **Deploy**: Supabase project, apply migration, run API on a small VM with `AICIV_SANDBOX=docker`, web on Vercel.
3. **Push notifications for approvals** (Web Push now, APNs with the native shell).
4. **Connect a real GitHub repository** through the GitHub App and open draft PRs.
5. **LangGraph planner** for model-planned missions beyond "fix the failing test".
6. **Redis** for the mission queue and rate limits; multiple API instances.
7. GLB agent models and richer interiors.

---

# V4.0 — Management, market intelligence, logistics, two-stage release approval

Built in the order the V4 spec requires, smallest complete slice first.

| # | Step | Where |
|---|---|---|
| 1 | Hierarchy + permissions: Owner → General Manager (Atlas, `claude-opus-5-5`) → supervisors → specialists; departments with budgets | `packages/shared-types/seed/agents.json`, `departments`, `agent_reporting_lines` |
| 2 | Manager service: durable scheduled jobs (`scheduled_jobs`) + event-driven checks; rules first, Opus only for judgment | `services/management/` |
| 3 | Structured reports (progress, blocker, completed package, quality concern, estimate, resource request) routed to the supervisor | `agent_reports`, `report.submitted` |
| 4 | Market connectors: Apple public charts, Etsy Open API, Depop partner API, App Store Connect; labeled fixtures when unavailable | `services/research/connectors.py` |
| 5 | Evidence storage, cache, dedupe, query limits, configurable weighted scoring, OpportunityPacket workflow | `research_runs`, `research_findings`, `opportunities`, `opportunity_scores` |
| 6 | Durable package routing: Dijkstra with congestion, reroute on belt failure, retry on no-route | `services/logistics/` |
| 7 | 3D conveyors driven by `package.*` events | `apps/web/components/world/Conveyors.tsx` |
| 8 | Manager review gate (12 categories, 4 verdicts) | `manager_reviews`, `review_checklists` |
| 9 | Owner's Tower: executive review, APPROVE / REQUEST_CHANGES / REJECT / DEFER (append-only) | `owner_decisions` |
| 10 | Release authorization bound to the bundle's sha256, enforced inside `execute_tool` | `release_authorizations`, `release_invalidations` |
| 11 | Acceptance test: research → GM → App Studio → QA → GM review → Owner's Tower → refused until owner approves exact artifact | `tests/integration/test_v4_acceptance.py` |
| 12 | Security + performance validation | tests + PROGRESS.md |

Model identifiers come from Anthropic's current model list: `claude-opus-5-5` (General Manager), `claude-haiku-5-5` (research),
`claude-sonnet-5-5` (routine work). All are overridable per agent in the seed or with `AICIV_MODEL_<AGENT_KEY>`.
