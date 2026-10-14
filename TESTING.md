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

- Postgres/Supabase mode (migrations, RLS) — no Postgres was available in the build environment.
- Database-disconnect resilience and 3D frame-time budgets on real phones.
- Load tests for concurrent missions.
