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

---

## Increment 3 — finishing the open items (Oct 14, 2026)

### Done
- **Native iOS app** (`apps/ios`): SwiftUI tabs for City (the 3D web city), Company, Owner's Tower (Face ID before
  approving, network-blocked prototype preview, exact digest), Activity and Settings (token in the Keychain); SSE with
  ordered/deduplicated/gap-replayed events; local notifications and background refresh when a release reaches your
  tower. Builds and passes its XCTest suite on GitHub's macOS runner (`ios.yml`), plus an unsigned device build.
- **LangGraph**: every mission is a LangGraph thread; approvals are `interrupt()`s; checkpoints in SQLite or Postgres;
  `GET /api/missions/{id}/graph`. DECISIONS.md D3 rewritten.
- **PostgreSQL**: migrations applied by the API (`schema_migrations`), Postgres types adapted, seeding ordered for
  foreign keys, pgvector / `auth.uid()` optional. The full suite passes on Postgres 16, locally and in a new CI job.
- **Container sandbox**: hardened `DockerSandbox` (worker uid, 1:1 mounts for worktrees, kill on timeout) and its
  image; a whole mission runs with every tool in containers, locally and in a new CI job.
- **Real pull requests**: approved missions open draft PRs on GitHub — [AiFactory#2](https://github.com/marcompsci/AiFactory/pull/2)
  (log: `docs/acceptance/github-pr-log.md`).
- **Live models**: model IDs checked against Anthropic's model list (`claude-opus-5-5`, `claude-sonnet-5-5`,
  `claude-haiku-5-5`); `scripts/live_smoke.py` and a manual "Live models" workflow make real calls once you add the key.

### Bugs found and fixed
- CI backend failures on Python 3.12: two background threads stored an `Event` as `self._stop`, which shadows
  `Thread._stop()` there (renamed).
- iOS test host not found: the app's product name had a space (`AI Civ.app`); the display name keeps the space.
- First real PR attempt included compiled `__pycache__` files and a retry tried to commit twice (fixed, see log).
- Event-replay tests raced background ticks on Postgres (assertions made exact about what they mean).
- `/api/snapshot` could mix rows from different moments on Postgres (READ COMMITTED); it now reads in one
  REPEATABLE READ snapshot, so its `sequence` always matches its rows.
- A research brief could be dispatched twice: the pipeline's recovery path fired while the researcher was still
  walking it to the terminal. Recovery now waits for the research mission to end, and dispatch is idempotent.

### Still open
- **No real model call yet** — add `ANTHROPIC_API_KEY` as a repository secret and run the "Live models" workflow.
- The iPhone app is built and unit-tested on a simulator in CI, not yet installed on a physical phone (needs your
  Apple developer signing; see `apps/ios/README.md`). Remote push needs an APNs key.
- Supabase-hosted specifics (real `auth.uid()` RLS, Broadcast) and the GitHub App token exchange are untested; the
  PR run used the environment's own git credentials.
- Marketplace research still runs on labeled fixtures without Etsy/App Store Connect credentials.

---

## Increment 4: V5.0 AI Central Bank (Oct 14, 2026)

Built in the order the spec gave. The secure fee review workflow came first.

### Built
- **Threat model** with 17 rules, each enforced in code and tested: `docs/finance/THREAT_MODEL.md`.
- **Database**: 15 finance tables, a financial reports table and step-up secrets. Migration `0003` adds owner/admin
  RLS, an append-only and hash-chained audit log, check constraints, and the 10 financial package types with
  required subject references.
- **Agents**: Sterling (CFO) → Atlas, with six specialists under Sterling. Haiku does routine work, Sonnet does
  judgment. Routine classification uses rules, not models.
- **Fee review workflow**: paid-tool requests from Kade and fees detected in the ledger both travel the belts
  through the bank, the Research Division, the bank again, the GM (when significant) and the Owner's Tower.
  Decisions are approve, reject, defer or more research. Execution is gated at the tool on exact, expiring,
  single-use, step-up-verified approvals.
- **Data**: a labeled simulated ledger (6 months of a small app business) and read-only adapters for CSV,
  Stripe, Plaid and App Store Connect. Sync covers dedupe, categorization, recurring detection, reconciliation,
  coverage gaps and sync runs. Bills get reminders and payment proposals and are never autopaid.
- **Dashboard**: cash and available balances, revenue, fees, refunds, operating costs, gross and net profit
  *estimates*, cash flow, bills, subscriptions, tax reserve, a 90-day forecast band, AI costs (ledger and agents'
  own estimate), savings, reconciliation, freshness and gaps.
- **Tax**: deadlines (US federal; CA optional), document checklist and upload, labeled estimates with uncertainty
  and missing evidence, and an export zip for a tax professional. Filing is always refused.
- **3D**: an AI Central Bank skyscraper west of the plaza. Floors light up from real tool events, staff stand at
  their floor desks, "Go inside" shows the labeled floor stack, the belts carry financial packages, and the Owner's
  Tower beacon also lights for financial decisions.
- **Web**: a Bank tab, and financial decisions at the Owner's Tower with a step-up dialog (enroll once, then a
  6-digit code per approval).
- **iPhone**: financial decisions in the Owner tab, with Face ID and then an authenticator code.

### Results
- pytest **148 passed, 3 skipped** on SQLite and on PostgreSQL 16 · vitest **15** · Playwright **7** · tsc and next build clean
- Acceptance log: `docs/acceptance/v5-acceptance-log.md`

### Bugs found and fixed while building V5
- A second research round never reached the General Manager, because the first review was still on record. Each
  round now gets a fresh GM review, and the old one stays in the audit log.
- Postgres rejected Python booleans for `significant` (stored as an integer now). A malformed account
  reference reached a uuid query (now validated).
- Payment-processor and AI-usage pricing is per transaction or per use, so a "$0 plan" in the catalog would have
  ranked as cheapest. Usage-priced options are now never ranked on price.
- Unknown deposits were going to count as revenue. They are now "other" and wait for review.

### Still open
- No real financial account has been connected; the adapters are tested against mock responses.
- Live alternatives research needs an authorized search connector. Today it uses the labeled fixture catalog.
- No payment, transfer or filing rails exist, by design (D13).
- Step-up is TOTP or aal2. WebAuthn/passkeys are next.
- Accounting, marketplace-payout and billing integrations are listed as gaps and not built.

## Increment 5: V5.1 free-alternative investigation, App Lab, money game, pixel-art city (Oct 14, 2026)

### Built
- **Free-alternative investigations (V5.1 spec).**
  - The owner's `RESEARCH_FREE_ALTERNATIVE` decision keeps the request `PENDING_OWNER_DECISION` and starts a
    durable investigation.
  - The investigation travels as a physical packet: Central Bank → Data Observatory → bank → Code Forge →
    Sentinel Citadel → Nexus Spire → Owner's Tower.
  - It runs on 7 new tables (migration `0004`), a persisted state machine with realtime events, and real sandboxed
    pytest against labeled fixture kits.
  - QA gives a verdict and the GM makes a recommendation that can't authorize anything.
  - The owner gets the full comparison with sources, licenses, prices, test results and costs.
- **App Lab.**
  - The owner authorizes a repository with step-up and an encrypted token, from a fine-grained token or GitHub
    sign-in.
  - Research collects design patterns people engage with, buy and play. Code Forge reads the repository read-only
    and drafts proposals.
  - The GM reviews them against hard rules and briefs the owner.
  - An owner approval of the exact change publishes it once: a draft PR on `aiciv/lab-*`, or a `claude`-labeled issue
    for the Claude Code GitHub Action, never the default branch. Status is tracked read-only.
  - Includes autopilot and migration `0005`.
- **The money game.** A monthly leaderboard scored only on verified money: realized savings, avoided costs and
  owner-linked revenue. Scores are append-only and idempotent, simulated plays are labeled, amounts are visible to
  owners and admins only. Migration `0006`.
- **Sign in with Google and GitHub** via Supabase Auth, with owner mapping through `app_metadata.role` or verified
  `AICIV_OWNER_EMAILS`. Claude is connected through an API key for the agents and Anthropic's Claude Code GitHub
  Action for code; there is no claude.ai login, by Anthropic's policy.
- **Pixel-art city and dashboard frame** following the reference image:
  - low-resolution, pixelated rendering;
  - floating islands, waterfalls, neon signs, flying cars, chibi agents and pixel speech bubbles;
  - a stats bar (cash, agents, tasks, projects, 30-day revenue, date and time) and left navigation;
  - four live bottom panels (activity, conveyor flow, active projects, financial overview) fed by `/api/overview`.

### Results
- pytest **161 passed, 3 skipped** on SQLite and on PostgreSQL 16 · vitest **15** · Playwright **8** · tsc and next build clean
- Acceptance logs: `docs/acceptance/v51-acceptance-log.md`, `docs/acceptance/app-lab-acceptance-log.md`

### Bugs found and fixed while building
- With an unknown vendor, research returned no options, so the GM rejected the request before the owner could ask
  for an investigation. Research now always includes the requested option.
- The new stats bar selected a fresh array from the store on every render and looped in React. It now selects a
  count.

### Still open
- Weather from the reference image is not shown: there's no weather source, and a made-up one would be fabricated
  data. The bar shows the local date and time.
- Live alternatives and live design research need authorized search/chart connectors; today both use labeled
  fixtures.
- App Lab has been exercised against a local bare repository and a mock GitHub API, not a real GitHub repository.
  Connecting one is the owner's step.
- Docker-sandbox tests weren't re-run in this environment (no Docker); CI runs them.

## V5.1 — Native iPhone redesign and backend hardening

- iPhone app redesigned in the pixel-art style: Home (stats bar, live pixel map of the city, activity, conveyor,
  projects, finance), City, Arena, Owner (now with App Lab proposals: Face ID, then authenticator step-up), More (App Lab,
  Factories, Company, Activity, Settings). Sign in with Google or GitHub through Supabase (PKCE, Keychain).
- Backend hardening: security headers, body caps, token rules (exp/aud/issuer), lockouts for bad tokens and step-up codes,
  per-client request budget, auth before body parsing on every mutating route, generic 500s with a request id, docs off
  outside dev, supply-chain audit job. See SECURITY.md.
- `/api/public-config` gives the iPhone app the Supabase address and publishable key.

### Still open
- The Swift code is compiled and tested only on CI (macOS); it hasn't run on a physical iPhone here.
- Supabase needs `aiciv://auth-callback` in its redirect URLs, and the Google/GitHub providers saved, before phone sign-in works.

## V5.2: Codex Factory, plans and the company knowledge base

- Agents run on the owner's Codex plan first and switch to the Claude plan when Codex runs out; while the owner uses
  Claude, agents on the Claude plan use Haiku. Nyx (Codex) and Coda (Claude) brief every agent each check-in.
- Codex Factory: sessions, finished plan steps, AGENTS.md shared as memory.
- Company knowledge base floating over the city (Phoronomics, Phoronomic Studios): docs and skills; agents pull the
  relevant ones automatically. The owner's 15 skills are in `knowledge/skills` on the Mac and import on start.

### Still open
- Neither CLI has been run against a real plan from here (the build environment has neither signed in); tests use
  stand-in CLIs that speak the documented output formats. First real run happens on the Mac.
- The Claude meter is an estimate; Anthropic publishes no usage figure for subscriptions.

## V6.0: Playable pixel-art town (first milestone)

- `/play` (and the iPhone City tab): walk your own character around a pixel-art town with WASD, a joystick or tap
  to walk. Three enterable buildings (Research Observatory, Nexus Spire, Code Forge) with your agents at their desks.
- Talk to agents in RPG dialogue. Answers come from backend records; requests become proposals that run only on
  Confirm (research missions, software-change missions, cancel).
- Agent animations follow backend execution state; packages ride the conveyor by their server route clock; the bell
  and the Owner's Tower open the approval screen. Your look and position persist.
- Verified locally end to end in simulation: talk → confirm → research mission → research brief rode the belt to the
  Nexus Spire; Kade's fix mission → approval on the approval screen → completed.
- See docs/PLAYABLE_TOWN.md.

### Still open
- Not yet run on the physical iPhone; other building interiors; Claude Code / Codex session management (see doc).
