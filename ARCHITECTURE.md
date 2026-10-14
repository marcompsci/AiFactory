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
