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
 └───────────────────────────┘                    │  └ MissionRunner (durable)   │
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
   `approvals` row + `approval.requested` event are written. The runner exits.
5. `POST /api/approvals/{id}/grant` records the decision and re-enqueues; the protected tool runs only if the
   database shows a GRANTED approval for that exact task at that moment.
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
| `services/core/events.py` | `transaction()`, `emit()` (event + outbox atomically), replay |
| `services/core/realtime.py` | broadcaster, outbox publisher, Supabase adapter |
| `services/core/state.py` | mission / task / agent transition tables |
| `services/core/auth.py` | dev / token / Supabase JWT modes, roles, rate limiting |
| `services/orchestrator/plan.py` | prompt + graph validation, the mission template |
| `services/orchestrator/runner.py` | durable scheduling, retries, approvals, cancellation, budget suspension |
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
| research_brief | Data Observatory → Nexus Spire | Atlas | packet review (rules, then optional Opus veto) |
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
