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

## V4.0

**D11. Rules decide, Opus advises.** The General Manager's routing, acceptance and release verdicts are deterministic rules.
Opus 5.5 is consulted for the packet review and the release summary only, and its output can make a decision stricter, never
looser. This keeps the manager auditable and cheap, and means no model output can bypass a threshold.

**D12. Packages are the handoff.** A stage starts only when the backend marks the right package ARRIVED at the right building.
The conveyor is not a decoration over the workflow; it is the workflow's transport layer, and the 3D belt only draws it.

**D13. Approvals bind to artifact + digest.** Deterministic bundles mean identical rebuilds share a digest, so reviews and owner
approvals are tied to the artifact id as well. A rebuild always needs a new review and a new owner decision.

**D14. Prototype from a tested template.** App Studio's prototype comes from a template with a real tested core, filled in from
the approved spec. It is honest about this in the README, the preview footer and the checklist. Model-generated code is a later step.

**D15. Local release channel only.** `submit_release` copies the approved bundle to `data/releases/`. App Store submission,
listing publication and production deploys would be separate tools behind the same release gate; none are built yet.

**D16. Nexus Spire's gate faces east.** The parity test found Nexus Spire and Memory Vault sharing one ring junction; the
Nexus gate moved to the open east side so every district has its own junction.
