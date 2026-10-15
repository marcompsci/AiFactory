# Deployment

## Shape

- **Web app**: static-friendly Next.js build. Any Node host (Vercel, Fly, Render) or `AICIV_STATIC_EXPORT=1 npm run build`
  for a pure static export on a CDN. Needs HTTPS to install as an app on iPhone outside your home network.
- **API + worker**: one Python process (`uvicorn services.api.main:app`). It runs the worker pool and the outbox
  publisher in-process. Keep it to a single instance until the queue moves to Redis.
- **Database**: Supabase Postgres. Apply `infrastructure/migrations/0001_init.sql`, then set `DATABASE_URL`
  (install `psycopg[binary]`). Seed data is inserted on first start.
- **Realtime**: the API's own SSE stream works everywhere. Optionally set `SUPABASE_URL` and
  `SUPABASE_SERVICE_ROLE_KEY` (server-side only) to also publish to Supabase Realtime Broadcast.

## Checklist

1. Generate `AICIV_API_TOKEN` (or set `SUPABASE_JWT_SECRET` to use Supabase Auth).
2. Set `AICIV_ALLOWED_ORIGINS` to the web app's exact origin.
3. Set `ANTHROPIC_API_KEY` and/or `OPENAI_API_KEY` for live mode; set `AICIV_DAILY_BUDGET_USD`.
4. Use `AICIV_SANDBOX=docker` on a host where the worker may start containers (never mount the socket into
   the API container that serves requests from the internet without isolating the worker first).
5. Put the API behind HTTPS (the SSE endpoint needs proxy buffering off: `X-Accel-Buffering: no` is sent).
6. Build the web app with `NEXT_PUBLIC_API_URL=https://your-api` or set it in the app under System → Server.
7. Sign-in with Google/GitHub: set `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` on the web app and
   `SUPABASE_URL` (JWKS; or `SUPABASE_JWT_SECRET` for legacy projects) plus optionally `AICIV_OWNER_EMAILS` on the API. See docs/AUTH.md.
8. App Lab: set `AICIV_FINANCE_KEY` (tokens are encrypted with it). Optional: `AICIV_APPLAB_AUTOPILOT_HOURS`
   (default 24). Repositories are connected from the app by the owner, never from env. See docs/APP_LAB.md.
9. Apply migrations `0001`–`0006` (the API applies pending ones on start when `DATABASE_URL` is Postgres).

## Docker

```bash
cp .env.example .env    # fill in
docker compose up --build
```

`docker compose --profile postgres up` adds Postgres (pgvector) and Redis containers. The API applies
`infrastructure/migrations/*.sql` itself on start (tracked in `schema_migrations`); on plain Postgres a stub
`auth.uid()` is created and `memory_entries.embedding` falls back to `jsonb` when pgvector is missing.

### Container sandbox

```bash
docker build -f infrastructure/docker/sandbox.Dockerfile -t aiciv-sandbox:latest .
AICIV_SANDBOX=docker            # optional: AICIV_SANDBOX_IMAGE=your-registry/aiciv-sandbox:tag
```
The worker needs the Docker CLI and daemon; workspaces are bind-mounted at the same absolute path, so the
worker's data directory must be a real host path (not a path that exists only inside another container).

### Real pull requests

```bash
AICIV_GITHUB_REPO=owner/repo          # where pull requests go
AICIV_GITHUB_BASE=main                # the branch they target
AICIV_GITHUB_SUBDIR=path/in/repo      # where the mission's project lives in that repo ("" = root)
GITHUB_TOKEN=github_pat_…             # fine-grained: Contents + Pull requests (read/write) on that one repo
# or a GitHub App: GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY_PATH, GITHUB_APP_INSTALLATION_ID
```
Pull requests open as drafts, only after you approve the mission's publish step.

### Live models

Add an `ANTHROPIC_API_KEY` repository secret (GitHub → Settings → Secrets and variables → Actions), then run the
**Live models** workflow from the Actions tab. It calls each model the roster uses and, optionally, runs one live
mission to the approval gate. Locally: `ANTHROPIC_API_KEY=… python scripts/live_smoke.py --mission`.

### AI Central Bank (V5)

```bash
AICIV_FINANCE_KEY=…   # required outside dev mode: encrypts financial credentials and step-up secrets
```
Then, in the app (Bank tab, as the owner):
1. **Set up step-up.** The first approval asks you to enroll an authenticator app. With Supabase Auth, an `aal2`
   session whose MFA happened in the last 10 minutes also counts.
2. **Connect read-only sources.** Add a connection, then **Authorize** it. Stripe needs a *restricted* key (`rk_…`)
   with read access to Balance and Balance transactions. Plaid needs a Link access token for the transactions product.
   App Store Connect needs an API key with the Finance or Sales role. CSV statements can be uploaded any time.
   Nothing is read from environment variables.
3. Until something is connected, the dashboard shows gaps, not zeros. The **Load simulated ledger** button gives a
   labeled test ledger for trying the workflow.

No payment, transfer or tax-filing integration exists. Approved actions on live data become a checklist that you
complete yourself and then mark done (with step-up).

## Status

Verified: SQLite and **PostgreSQL 16** (full test suite on both), the **Docker sandbox** (real containers, a whole
mission), **real draft pull requests** (see `docs/acceptance/github-pr-log.md`), and the native iOS app's build and
unit tests on GitHub's macOS runners. Not yet verified: Supabase-hosted Postgres specifically (RLS with real
`auth.uid()`), Supabase Broadcast, the GitHub App token exchange (the PR run used ambient git credentials), and any
real model call (needs your key). AI Central Bank: verified end to end on simulated data (API tests, the Postgres
suite, and a browser test that approves with a real TOTP code). The Stripe, Plaid and App Store Connect adapters are
tested against recorded-shape mock responses only; no real financial account has been connected.
