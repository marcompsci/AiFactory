# Progress

## Increment 1 — playable vertical slice (Oct 14, 2026)

### Built
- Monorepo: `apps/web`, `packages/{world-engine,event-contracts,shared-types}`, `services/*`, `infrastructure`, `tests`, docs, CI.
- Backend: FastAPI API, durable mission runner, worker with crash recovery, transactional outbox + SSE,
  model gateway (Anthropic + OpenAI), sandboxed tool registry (12 tools), approvals, budgets, memory,
  emergency stop, Postgres migration with RLS.
- Frontend: 3D city with six districts and six agents, four camera modes, district focus/interior view,
  deterministic event interpreter, command center (missions, task graph, tool calls, conversation,
  artifacts, approvals, activity, costs, health, memory, settings, emergency stop), phone layout,
  installable PWA, offline demo mode.

### Commands run and results
- `python -m pytest` → **62 passed** (×3)
- `npx vitest run` → **9 passed**
- `npx tsc --noEmit` and `next build` → clean
- `npx playwright test -c tests/e2e/playwright.config.ts` → **4 passed**
- Manual run through the UI in headless Chromium: mission sent from the panel, agents walked, real tests went
  from 1 failed / 4 passed to 5 passed, approval requested, approved in the UI, commit created on
  `mission/<id>`, state intact after reload.

### Bugs the tests caught and fixed during the build
- Two agents initializing the sample repo at the same moment (now locked + atomic rename).
- Denied tool calls lost their audit row on rollback (now written in their own transaction).
- After a crash, an expired approval was not re-requested (expired approvals never count now).
- A relative data directory put git worktrees in the wrong place (paths are resolved now).
- Activity feed was empty after reload (recent history is loaded on connect).

### Known limitations
- Live model mode was tested with a fake provider only; no real API key was available in the build environment.
- Postgres/Supabase, Supabase Broadcast, DockerSandbox and the GitHub App adapter are implemented but untested here.
- One mission template ("fix the failing test" on the bundled sample repo). Missions on other repositories
  need the GitHub integration milestone.
- LangGraph not used yet (see DECISIONS.md D3).
- Agents are procedural shapes, not GLB models. Interiors are a see-through focus view, not separate scenes.
- No native iOS app yet; the PWA installs from Safari's Share menu.
- Queue and rate limiter are in-process (single API instance).

### Credentials / setup you provide
- `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` for live mode.
- `AICIV_API_TOKEN` to use the app from your phone.
- Supabase project + `DATABASE_URL` for production.
- GitHub App id, key and installation id for real pull requests.

### Next milestone
Native iOS shell around the web app, plus push notifications when an agent needs approval.

---

## Increment 2 — V4.0 management, market intelligence, logistics, two-stage release (Oct 14, 2026)

### Built
- **Hierarchy**: Owner → Atlas (General Manager, `claude-opus-5-5`) → 5 department supervisors → specialists, including two Haiku researchers (Pip, Wren). Departments with daily budgets; reporting lines; structured reports (progress, blocker, completed package, quality concern, estimate, resource request) filed automatically as tasks run.
- **Manager service**: durable scheduled jobs (`supervisor`, `logistics`, `pipeline`) with event pokes; rule-based supervision (stalls, budget suspensions, goal drift vs the approved spec, reassignment, release integrity); every decision a structured `manager_decisions` row + event; Opus consulted only for packet review and release summaries, and only able to tighten.
- **Research division**: Apple charts, Etsy, Depop (partner-only), App Store Connect connectors; rate limits, daily caps, 6-hour cache/dedupe; findings with source, time, region, coverage, measurement type and confidence; fixtures labeled end to end.
- **Opportunity scoring**: 9 weighted components with evidence; configurable weights and owner priorities; OpportunityPacket workflow with rejection, revision, deferral, cancellation and reopen paths.
- **Logistics**: 21 terminals/junctions, 28 directed belt segments; Dijkstra with congestion; reroute around DOWN belts; failed-delivery retry; all state in `logistics_packages` + `package_transitions`.
- **App Studio**: tested focus-and-streaks prototype template, deterministic sha256 release bundles.
- **Two-stage release**: 12-category manager review → Owner's Tower decision (owner role, exact digest, append-only) → authorization enforced inside `execute_tool` → local release channel; tampering invalidates and forces rebuild + renewed reviews.
- **3D**: Owner's Tower district with a beacon while a release waits; animated belts with moving slats, terminals with queue stacks and status lights, packages positioned from server routes and clock (pulse at the end until the backend confirms arrival), agents carrying holographic packages to dispatch, new GM and drone silhouettes, click-to-inspect packages.
- **Command center**: Company tab (research launcher, opportunity stage bars, chain of command with models, manager decisions, supervisor reports, conveyor status with belt controls) and Owner tab (Owner's Tower review: product summary, recommendation, sandboxed live preview, digest + download, test results, checklist, cited research, costs, risks, four decisions; escalations; V3 publish approvals).

### Results
- pytest **97 passed** · vitest **13 passed** · Playwright **5 passed** · tsc and build clean
- Acceptance scenario passes and is recorded in `docs/acceptance/v4-acceptance-log.md`.

### Bugs found and fixed while building V4
- GM's Opus call ran inside a pipeline transaction → SQLite lock; all model calls now happen with no transaction open.
- Deterministic rebuilds kept the old manager review valid → reviews and approvals now bind to artifact id + digest.
- Owner "request changes" didn't count as a revision or send a package back → now does both.
- Nexus Spire and Memory Vault shared one belt junction (caught by the browser/backend parity test) → Nexus gate moved east.
- Background threads touched a reset database after tests → scheduler and publisher are joined on shutdown.

### Known limitations
- No real Opus/Haiku calls and no live marketplace calls were possible here: model paths ran against a fake provider; research ran on labeled fixtures.
- Releases go to a local channel only; App Store submission, listing publication and production deploy tools are not built (they would sit behind the same gate).
- The prototype comes from one template category (productivity); other categories score lower on feasibility and are not buildable yet.
- Package rerouting snaps the package to the end of its current belt; queue stacks are capped at six visible boxes.
- Single API instance (in-process queue, scheduler and rate limits).
- Native iOS shell still pending (from increment 1).

### Next milestone
Connect real credentials (Anthropic key, Etsy key) and run one live research → release cycle; then the native iOS shell with push notifications for the Owner's Tower.
