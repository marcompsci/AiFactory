# Testing

| Suite | Command | What it covers |
|---|---|---|
| Backend unit | `python -m pytest tests/unit` | state machines, graph validation (cycles, capability), prompt validation, sandbox (allowlist, path escapes, symlinks, no-network, secret scrubbing, timeout kill, docker flags), model gateway (usage parsing, retries, error normalization, context fitting), auth (token, JWT roles, forged tokens, query-token scope), rate limiting, memory trust/TTL/deletion, secret redaction |
| Backend integration | `python -m pytest tests/integration` | full simulation mission with real pytest runs and git worktrees; event ordering + JSON-Schema validation + replay + outbox drain; approve / reject / cancel; protected-tool denial; unauthorized tool denial with audit; idempotent creation; emergency stop; live mode with a fake provider (model patch, cost records, untrusted fencing); refusing test edits; provider outage; budget suspension and resume; crash recovery; reconnection snapshot; dev-mode remote refusal |
| World engine + contract | `npx vitest run` | envelope validator, in-order/duplicate/gap handling, movement vs execution separation, workstation activation, approvals, determinism, routes between all districts, demo script validity |
| End to end | `npx playwright test -c tests/e2e/playwright.config.ts` | starts a fresh API and the production web build; sends a mission from the UI, approves it, opens the diff artifact, reloads (snapshot hydration + feed history), agent inspector, phone layout, offline demo |

Locally without Playwright's browser download: `PW_CHROME=/path/to/chrome PYTHON_BIN_DIR=/path/to/venv/bin npx playwright test -c tests/e2e/playwright.config.ts`.

## Last verified run (Oct 14, 2026, Linux, Python 3.13, Node 22)

- `pytest`: 62 passed (three consecutive runs)
- `vitest`: 9 passed
- `playwright`: 4 passed (system Chromium 141 with SwiftShader WebGL)
- `next build` + `tsc --noEmit`: clean

## Not yet automated

- Supabase-hosted Postgres specifically (RLS with a real `auth.uid()`); plain Postgres 16 is covered (see below).
- Database-disconnect resilience and 3D frame-time budgets on real phones.
- Load tests for concurrent missions.

## V4.0 additions

| Suite | What it covers |
|---|---|
| `tests/integration/test_v4_acceptance.py` | **Acceptance scenario** end to end (Haiku researcher → cited packet → belt → Opus GM → App Studio prototype → QA real tests on the exact bundle → 12-category GM review → Owner's Tower → release refused until the owner approves that digest → release → tamper → invalidation → rebuild → renewed reviews → old approval refused); Opus used only for judgment and Haiku for research; the model can only tighten; low-confidence research never reaches production; spend beyond delegation escalates to the owner; owner REQUEST_CHANGES / DEFER / reopen; non-owners cannot decide |
| `tests/unit/test_v4_units.py` | belt graph reachability, ring alternative paths, congestion routing, package lifecycle driven by the backend, reroute around a DOWN belt, failed delivery + retry, state machines, scoring components/weights/flags, connector fixture labeling, live mode never using fixtures, Apple feed parsing, Etsy 429 handling, research cache dedupe + daily limits, reporting chain, append-only owner decisions, deterministic + traversal-safe bundles, the prototype template passing its own tests, verdict rules, model routing, per-agent model override, backend/browser graph parity, logistics tick under load |
| `packages/world-engine/src/world.test.ts` | client belt graph matches the backend exactly, terminal positions, package sampling, package/owner-queue events |
| `tests/e2e/app.spec.ts` | V4 owner flow in a real browser: research → Owner's Tower with live prototype preview, digest match and fixture banner → approve → released |

### Last verified run (Oct 14, 2026)

- `pytest`: **97 passed** (two consecutive full runs before the load test was added: 96 + 96)
- `vitest`: **13 passed**
- `playwright`: **5 passed**
- `tsc --noEmit`, `next build`: clean
- Performance: logistics tick with 200 packages in flight **40 ms** (interval 1 s); full acceptance pipeline from research to Owner's Tower ≈ 1.5 s with test belt speed
- Recorded acceptance log: [`docs/acceptance/v4-acceptance-log.md`](docs/acceptance/v4-acceptance-log.md) (286 events)

## Increment 3 additions

| Suite | Command | What it covers |
|---|---|---|
| Whole backend suite on **PostgreSQL** | `AICIV_TEST_DATABASE_URL=postgresql://… python -m pytest tests/unit tests/integration` | migrations applied by the app's runner, uuid/timestamptz/numeric round-trips, append-only triggers, LangGraph `PostgresSaver` checkpoints; CI job `postgres` (Postgres 16 service container) |
| **Docker sandbox**, real containers | `docker build -f infrastructure/docker/sandbox.Dockerfile -t aiciv-sandbox:latest . && AICIV_TEST_DOCKER=1 python -m pytest tests/integration/test_docker_sandbox.py` | no network, read-only root, writable workspace owned by the worker, no secrets in env, timeout kills the container, a whole mission with every tool in containers; CI job `sandbox` |
| **LangGraph** | in `tests/integration/test_missions.py` | missions are LangGraph threads; approval is an `interrupt()`; the checkpoint survives a process restart and resumes |
| **GitHub publisher** | `python -m pytest tests/unit/test_github_publisher.py` | push + draft PR flow against a local bare repo and mocked API; dangerous paths refused; retry reuses the PR. Real run: `docs/acceptance/github-pr-log.md` |
| **Live models** | `ANTHROPIC_API_KEY=… python scripts/live_smoke.py --mission` or the manual "Live models" workflow | one real call per model the roster uses, then one live mission to the approval gate; exits 2 and calls nothing without a key |
| **iOS** | `.github/workflows/ios.yml` on macOS 15 | XcodeGen project, XCTest unit tests on an iPhone simulator, unsigned device build |

### Last verified run (Oct 14, 2026)

- `pytest` on SQLite (Python 3.13 and 3.12): **106 passed, 3 skipped** (the 3 Docker tests skip without `AICIV_TEST_DOCKER`)
- `pytest` on PostgreSQL 16: **106 passed, 3 skipped**
- Docker sandbox tests in real containers: **3 passed** (plus the command-flags unit test)
- `vitest` **13 passed** · Playwright **5 passed**
- iOS: build, XCTest and unsigned device build **passed** on GitHub's macOS runner
- `scripts/live_smoke.py` was exercised against a local stand-in that speaks the Messages API, only to check the
  script itself; **no real model has been called**
