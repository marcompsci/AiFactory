# Decisions

**D1. One vertical slice before breadth.** Following the spec's directive, the build delivers one complete,
verifiable mission path (inspect → reproduce → fix → verify → review → approve → publish → archive) rather
than partial versions of all six phases.

**D2. Web app first, installable as a PWA; native iOS next.** The spec targets desktop and mobile browsers with
Next.js + React Three Fiber. The owner asked for "both" web and native; the PWA gives an installable iPhone
app now, and a native shell is the next milestone (see PROGRESS.md).

**D3. Durable runner instead of LangGraph (for now).** The mission workflow is a small, fixed graph whose every
step is persisted (tasks, task_runs, approvals, events), which already gives checkpoints, approval interrupts
and restart recovery with plain, testable Python. LangGraph is deferred until missions need model-planned,
branching graphs; the runner's handler interface is where a LangGraph node would plug in. Not silently
skipped: this is a deliberate substitution and is listed as open work.

**D4. SQLite locally, Postgres in production, one schema.** Lets the whole system run and be tested with no
infrastructure. Column names match the Postgres migration; Postgres-only features (RLS, pgvector) live in the
migration.

**D5. Server-Sent Events as the primary realtime channel; Supabase Broadcast as an optional adapter.** SSE works
on iOS Safari, needs no extra service, carries `id:` for resumption, and the outbox makes it reliable.

**D6. Templated task graph, model-generated content.** The model writes plans, reviews and patches; it never
writes the task graph or permissions. This keeps "Mission Commander coordinates but cannot override
permissions" structurally true.

**D7. Simulation is explicit at three levels.** `execution_mode` on every mission and event; message text prefixed
`[simulation …]`; the client demo has its own badge. Tools always execute for real, so test results are never
simulated.

**D8. `services/` is one Python package.** The spec's `services/model-gateway` folder became
`services/model_gateway` so it is importable.

**D9. No shadcn/ui CLI scaffold.** The command center uses a handful of hand-written primitives in
`components/command/ui.tsx` styled with Tailwind v4 tokens. shadcn components can be added later if the UI grows.

**D10. Typography.** Unbounded for the few display moments (brand, mission and agent names), IBM Plex Sans for UI,
IBM Plex Mono only for code, tool names and diffs.
