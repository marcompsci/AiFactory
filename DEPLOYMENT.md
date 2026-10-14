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

## Docker

```bash
cp .env.example .env    # fill in
docker compose up --build
```

`docker compose --profile postgres up` adds Postgres (pgvector) and Redis containers for experimenting with the
production database; the Supabase-specific RLS helpers (`auth.uid()`) need a real Supabase project.

## Status

The local SQLite stack is fully verified (see TESTING.md). The Postgres, Supabase Broadcast, Docker sandbox and
GitHub App paths are implemented but were **not exercised** in the build environment; treat the first deploy
as a test.
