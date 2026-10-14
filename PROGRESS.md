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
