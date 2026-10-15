# Architecture

## The one rule

**The world never decides anything.** Agents, workstations and district lights animate only in response
to events that the backend has already committed to the database. The renderer cannot start, approve or
complete work, and an animation finishing never means a task finished.

```
 Browser (phone / desktop)                         API process                               Database
 ┌───────────────────────────┐   POST /missions   ┌──────────────────────────────┐   one txn   ┌──────────────┐
 │ Command center (React)    │ ─────────────────▶ │ FastAPI routes               │ ──────────▶ │ missions     │
 │                           │                    │   auth · roles · rate limit  │             │ tasks …      │
 │ World (R3F)               │ ◀── SSE envelopes ─│ OutboxPublisher ◀── poll ─────│◀─────────── │ events       │
 │  interpreter(state, evt)  │ ◀─ GET /snapshot ──│                              │             │ event_outbox │
 │  gap → GET /events?after  │                    │ MissionWorker (thread pool)  │             └──────────────┘
 └───────────────────────────┘                    │  └ LangGraph thread/mission  │──▶ checkpoints (SQLite / Postgres)
                                                  │    └ MissionRunner steps     │
                                                  │      └ handlers per agent    │──▶ ModelGateway (Anthropic / OpenAI)
                                                  │          └ execute_tool ─────│──▶ Sandbox (rlimits, no network,
                                                  └──────────────────────────────┘     argv allowlist, workspace jail)
```

## Data flow for one mission

1. `POST /api/missions` stores the mission (CREATED) and its `mission.created` event + outbox row in one
   transaction, then enqueues it.
2. The runner moves it through **VALIDATING** (prompt, repository/project membership, project tool policy,
   emergency stop, budget) → **PLANNING** (validated task graph with explicit inputs, permitted tools,
   expected outputs and validation rules; cycle and capability checks) → **QUEUED** → **RUNNING**.
3. Ready tasks (all dependencies COMPLETED or SKIPPED) run in parallel. For each task the agent is
   ASSIGNED, walks (`agent.movement_requested` → `agent.arrived`), becomes EXECUTING, and its handler calls
   tools through `execute_tool`, which re-checks permissions at execution time and writes `tool_executions`.
4. `publish` raises `NeedsApproval`; the task, agent and mission enter WAITING_FOR_APPROVAL and an
   `approvals` row + `approval.requested` event are written. The mission's LangGraph thread stops at
   `interrupt()` in its `await_approval` node, checkpointed.
5. `POST /api/approvals/{id}/grant` records the decision and re-enqueues; the worker resumes the thread with
   `Command(resume=...)`. The protected tool runs only if the database shows a GRANTED approval for that exact task
   at that moment. With `AICIV_GITHUB_REPO` set, publishing pushes `aiciv/mission-<id>` and opens a draft pull
   request (DECISIONS.md D8).
6. On completion every agent returns home and to IDLE; the mission records an `outcome`
   (`published`, `not_published`, `no_change`).

## Realtime

- `events` holds the authoritative, gapless per-organization `sequence`. `event_outbox` is written in the
  same transaction; `OutboxPublisher` delivers unpublished rows in order to SSE subscribers and, when
  configured, to Supabase Realtime Broadcast (`org:<id>` topic).
- Clients: `GET /api/snapshot` (state at sequence N) → `GET /api/stream?after=N` (SSE, `id:` = sequence, so
  `Last-Event-ID` works) → strict in-order application; duplicates ignored; a gap pauses application and
  triggers `GET /api/events?after=<last>`. Reconnects re-hydrate from a fresh snapshot.
- Every envelope is validated against `packages/event-contracts` (JSON Schema on the server tests, a
  hand-written validator in the client).

## World engine (`packages/world-engine`)

- `districts.json` drives the renderer, navigation and labels. Adding a district is a config change.
- `navigation.ts`: deterministic hub-and-spoke walkways (gate → plaza ring arc → gate → workstation).
- `interpreter.ts`: pure `(state, envelope, now) → state`; tested for ordering, dedupe, gap refusal,
  movement/execution separation, workstation activation and determinism.
- `simulation.ts`: the offline demo script; every envelope is `execution_mode: "simulation"`.

## Event → animation mapping

| Event | What you see |
|---|---|
| `task.assigned` | assignment bubble over the agent |
| `task.started` | district activity rises |
| `agent.movement_requested` / `agent.arrived` | agent walks the computed route / stops at the workstation |
| `tool.started` / `tool.completed` | workstation screen and light beam on / off, tool name label |
| `agent.message` | speech bubble |
| `approval.requested` | persistent amber bubble, floating "needs your approval" call, Approvals badge |
| `task.completed` / `task.failed` | green "Done" / red "Problem" bubble |
| `mission.completed` | plaza ring pulses green, all districts light up |

## Backend modules

| Module | Responsibility |
|---|---|
| `services/core/db.py` | portable table definitions (SQLite locally); Postgres schema in `infrastructure/migrations` |
| `services/core/pg.py` | Postgres: migration runner (`schema_migrations`), uuid/timestamptz/numeric adapters |
| `services/integrations/github.py` | approved patch → branch push → draft pull request (token, GitHub App, or ambient credentials) |
| `services/core/events.py` | `transaction()`, `emit()` (event + outbox atomically), replay |
| `services/core/realtime.py` | broadcaster, outbox publisher, Supabase adapter |
| `services/core/state.py` | mission / task / agent transition tables |
| `services/core/auth.py` | dev / token / Supabase JWT modes, roles, rate limiting |
| `services/orchestrator/plan.py` | prompt + graph validation, the mission template |
| `services/orchestrator/graph.py` | LangGraph `StateGraph` per mission: prepare → execute waves → approval interrupt; checkpointer |
| `services/orchestrator/runner.py` | the steps the graph calls: validation, planning, one wave of tasks, retries, cancellation, budget suspension |
| `services/orchestrator/handlers.py` | what each agent does; simulation vs live sourcing |
| `services/workers/worker.py` | bounded pool, re-enqueue, crash recovery |
| `services/tools/registry.py` | tool implementations + `execute_tool` enforcement + audit |
| `services/tools/sandbox.py` | ProcessSandbox, DockerSandbox, path confinement |
| `services/model_gateway/gateway.py` | provider adapters, retries, error normalization, cost estimates, context fitting |
| `services/memory/store.py` | verified (must cite a tool execution/artifact) vs hypothesis memory, TTL, deletion |

---

# V4.0 — management, market intelligence, logistics, two-stage release

```
 OWNER ──(Owner's Tower: APPROVE / REQUEST_CHANGES / REJECT / DEFER, bound to a sha256)──┐
   │                                                                                     │
 Atlas, General Manager (claude-opus-5-5) ── rules first; Opus only for packet review and release review
   ├─ Vega   (Operations)          ── releases only with a valid owner authorization
   ├─ Orin   (App Studio)  └─ Kade ── builds the prototype + deterministic bundle
   ├─ Sentry (Quality & Security)  ── tests the exact bundle
   ├─ Lumen  (Research)    └─ Pip, Wren (claude-haiku-5-5) ── permitted market data only
   └─ Iris   (Design)
```

## Opportunity workflow (`services/management/pipeline.py`)

`RESEARCHED → MANAGER_REVIEW → ROUTED → DEPARTMENT_ACCEPTED → IN_PRODUCTION → QUALITY_REVIEW → MANAGER_APPROVAL → OWNER_APPROVAL → RELEASE_AUTHORIZED`,
plus `REVISION_REQUESTED`, `REJECTED` (reopenable), `DEFERRED`, `CANCELLED`. Transitions are validated (`core/state.py`).

Each stage starts only when the right package has **arrived** at the right building:

| Package | From → To | Consumed by | Next |
|---|---|---|---|
| research_brief | Research Observatory → Nexus Spire | Atlas | packet review (rules, then optional Opus veto) |
| product_proposal | Nexus Spire → Code Forge | Orin (capacity check) | `build_prototype` mission |
| code_artifact | Code Forge → Sentinel Citadel | Sentry | `qa_prototype` mission on the exact bundle |
| test_report | Sentinel Citadel → Nexus Spire | Atlas | 12-category release review |
| release_package | Nexus Spire → Owner's Tower | the owner | owner decision |
| revision_request | any → Code Forge | Orin | new production mission (max 2 revisions) |

## Durable supervision without a model in the loop

`scheduled_jobs` holds three jobs with persisted due times, run by `management/scheduler.py` and poked early when a mission
finishes or the owner decides:

- **logistics** (1 s): advances packages from stored route + start time + belt speed; reroutes around DOWN belts; retries failed deliveries with backoff.
- **pipeline** (1 s): one idempotent step per active opportunity.
- **supervisor** (15 s): stalled tasks, budget suspensions, goal-drift checkpoints against the approved spec, reassignment to idle peers with the same permissions, release-integrity scan. Pure rules; it never asks a model whether something is still running.

## Conveyor network (`services/logistics/`)

Derived from `districts.json`: every district has a dispatch and a receiving terminal at its gate, spoke belts to a ring of
junctions, and the ring runs both ways — so every pair of buildings has two independent paths. Routing is Dijkstra with a
congestion penalty (+50% length per package already on a belt). The browser mirrors the same geometry
(`packages/world-engine/src/logistics.ts`, parity-tested against the backend) and positions each package from its
server-side route, start time and belt speed, corrected for clock skew. A package whose animation reaches the end before the
backend says ARRIVED waits there, pulsing.

## Two-stage release approval

1. **Manager review** — `management/release.py` checks requirements, functionality, tests (on the reviewed digest), security,
   privacy, accessibility, performance, store metadata, documentation, market rationale, cost and known limitations; verdict
   `APPROVED_FOR_OWNER_REVIEW | CHANGES_REQUESTED | REJECTED | BLOCKED`. Opus may write the summary and may tighten the verdict, never loosen it.
2. **Owner decision** — only the `owner` role; the request must carry the digest the owner saw; stored append-only.
   APPROVE creates a `release_authorizations` row bound to that artifact and digest.
3. **Enforcement** — `submit_release` is a release-gated tool. Inside `execute_tool` the backend re-checks: owner APPROVE
   exists, no invalidation, the artifact is still the newest bundle, and the file on disk still hashes to the approved digest.
   Any mismatch writes an append-only invalidation, emits `release.invalidated`, sends the opportunity back to manager
   review (rebuild), and denies the call. A rebuilt bundle always gets a fresh review and a fresh owner decision, even if its bytes are identical.

## Research (`services/research/`)

Connectors: Apple's public RSS charts (no key), Etsy Open API v3 (`ETSY_API_KEY`), Depop authorized partner API (only if configured — Depop has no public API),
App Store Connect for the owner's own apps (ES256 API key). Every finding stores source URL, collection time, region, coverage,
measurement type (ranking / listing count / popularity proxy / review signal / direct sales) and confidence. Fixtures are only
used in `fixture` mode or as a labeled fallback in `auto`; their URLs are `fixture://…`, their findings `data_mode=fixture`, and the
packet, review, Owner's Tower and acceptance log all say so. Runs are rate-limited and daily-capped per source, cached for 6 hours
(dedupe), and executed through the `query_market_source` tool so permissions, budgets and audit apply.

## Cost routing

| Work | Model / mechanism |
|---|---|
| Strategy and complex review | `claude-opus-5-5` (two calls per opportunity at most) |
| Research extraction and summarization | `claude-haiku-5-5` |
| Routine development and analysis | `claude-sonnet-5-5` |
| Scheduling, status, routing, supervision | deterministic code |

Per-agent, per-department, per-mission and daily budgets; per-source research query limits; temperature-0 response cache in the gateway; deduplicated research runs.

---

# V5.0: AI Central Bank (financial district)

The rules come first: [docs/finance/THREAT_MODEL.md](docs/finance/THREAT_MODEL.md) (F1–F17). Each rule names its
enforcement point and its test.

```
 Kade (Developer) ──request_purchase──▶ purchase_request ═══belt═══▶ AI CENTRAL BANK (west of the plaza)
                                                                     Sterling (CFO, Sonnet) classifies (rules)
                    ◀═══ fee_research_request ═══                    │
 DATA OBSERVATORY: Pip / Wren (Haiku) research_cost_alternatives      │  (authorized sources only; fixture catalog today)
                    ═══ savings_recommendation ═══▶                  Penny (Savings, Sonnet) compares 3-year cost
                                                                     Sterling proposes exact, expiring approvals
                                       significant? ═══▶ NEXUS SPIRE: Atlas (GM, Opus) forward / more research / reject
                                                         ═══ owner_approval_request ═══▶ OWNER'S TOWER
 Owner: approve (Face ID / TOTP step-up, exact fingerprint) │ reject │ defer │ more research
        ──▶ finance_execute mission: Billie (Bill Manager, Haiku) → execute_financial_action
            re-checks approval + terms + expiry + emergency stop in the executing transaction; single-use
```

| Piece | Where |
|---|---|
| Tables (15 + reports + step-up secrets), RLS, append-only audit | `services/core/db.py`, `infrastructure/migrations/0003_financial_district.sql` |
| Cost review packets and classification (rules) | `services/finance/packets.py` |
| Fee review workflow (scheduled job `finance`) | `services/finance/pipeline.py` |
| Approval engine: exact terms, expiry, step-up, single use | `services/finance/approvals.py`, `services/finance/stepup.py` |
| Financial tools and the tool-boundary gate | `services/finance/tools.py`, `services/tools/registry.py` (`_check_finance`) |
| Mission templates: `request_tool`, `cost_research`, `cost_analysis`, `finance_execute` | `services/orchestrator/plan.py`, `services/finance/handlers.py` |
| Read-only connectors: simulated, CSV, Stripe, Plaid, App Store Connect | `services/finance/connectors.py` |
| Sync: dedupe, categorize, reconcile, coverage, fee detection | `services/finance/sync.py`, `services/finance/categories.py` |
| Bills: reminders and payment proposals (never autopaid) | `services/finance/bills.py` |
| Dashboard (labeled figures, freshness, gaps) and forecast | `services/finance/dashboard.py` |
| Tax: deadlines, checklist, labeled estimates, export; filing always refused | `services/finance/tax.py` |
| Encryption, keyed hashing, redaction, audit chain, retention | `services/finance/{crypto,redaction,audit,retention}.py` |
| API (`/api/finance/*`, owner/admin; step-up header `X-Step-Up`) | `services/api/finance.py` |
| 3D bank: floors light from real tool events; staff at their desks | `apps/web/components/world/District.tsx` (`BankFloors`) |
| Bank tab and financial decisions at the Owner's Tower | `apps/web/components/command/{Bank,OwnerTower}.tsx` |
| iPhone: financial decisions with Face ID plus an authenticator code | `apps/ios/AICiv/Views/FinanceViews.swift` |

**Agents.** Sterling (Chief Financial Agent, Sonnet) reports to Atlas. Six others report to Sterling:

| Agent | Role | Model |
|---|---|---|
| Tally | Revenue Analyst | Haiku |
| Audra | Expense Auditor | Haiku |
| Billie | Bill Manager | Haiku |
| Ledger | Tax Preparation Agent | Sonnet |
| Penny | Savings Strategist | Sonnet |
| Vesta | Financial Forecaster | Haiku |

Routine classification, categorization and reconciliation use rules, with no model call. Models write only
narrative text, from a redacted view.

**Packages.** There are ten financial package types: `revenue_report`, `expense_alert`, `bill_reminder`,
`fee_research_request`, `savings_recommendation`, `purchase_request`, `payment_proposal`, `tax_review_package`,
`financial_forecast` and `owner_approval_request`. Each one must name its authoritative record (`subject_type` and
`subject_id`); this is enforced in code and by a Postgres check constraint.

## V5.1: investigations, App Lab, the money game, the dashboard frame

**Free-alternative investigations** (`services/finance/investigations.py`, `alt_research.py`, `investigation_tools.py`).
The owner's `RESEARCH_FREE_ALTERNATIVE` decision creates a durable `savings_investigations` row. The original request
stays pending. A `savings_investigation` package then travels Central Bank → Research Observatory → Central Bank → Code
Forge → Sentinel Citadel → Nexus Spire → Owner's Tower, with one mission per stage:

- `alt_research` (Haiku): up to 5 candidates with evidence;
- `alt_evaluation`: weighted scoring and the cost comparison;
- `alt_sandbox`: real pytest against the candidate's compatibility kit in a disposable sandbox;
- `alt_qa`: verdict;
- GM: a rules recommendation, with Opus explaining only.

State: `REQUESTED → RESEARCHING → EVALUATING → TESTING → MANAGER_REVIEW → AWAITING_OWNER`, plus `BLOCKED`, `FAILED`
and `CANCELLED`. The finance job advances it from database state only, so it survives restarts.

**App Lab** (`services/applab/`). The `applab` scheduled job advances `lab_cycles` through
`RESEARCHING → ANALYZING → MANAGER_REVIEW → AWAITING_OWNER → DONE`. Packages travel Observatory → Forge → Nexus →
Tower. Missions: `lab_research` (insights), `lab_analyze` (read-only clone, proposals, optional patch), and
`lab_publish` (created only by the owner's approval). Publishing goes through `GitHubPublisher` with the owner's
per-repository token. Details and the enforcement list: [docs/APP_LAB.md](docs/APP_LAB.md).

**The money game** (`services/game/scoring.py`). The `game` scheduled job turns authoritative records into
append-only `game_scores`:

- executed approvals → realized savings;
- an owner rejection after an investigation recommended the alternative → avoided cost;
- revenue from owner-linked payers → attributed revenue.

`GET /api/game` ranks agents per monthly season. See [docs/GAME.md](docs/GAME.md).

**Dashboard frame** (`apps/web/components/command/Frame.tsx`, `GET /api/overview`). The stats bar, side navigation,
and the four bottom panels (live activity from the event feed; conveyor counts by destination district; active
products, App Lab cycles and investigations with progress; and 30-day finance) are all read from the database.
Pixel-art rendering renders the canvas at `dpr 0.5` and upscales it with `image-rendering: pixelated`.
`PixelWorld.tsx` adds decorative islands, waterfalls, signs and flying cars.
