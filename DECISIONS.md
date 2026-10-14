# Decisions

**D1. One vertical slice before breadth.** Following the spec's directive, the build delivers one complete,
verifiable mission path (inspect → reproduce → fix → verify → review → approve → publish → archive) rather
than partial versions of all six phases.

**D2. Web app first, installable as a PWA; native iOS next.** The spec targets desktop and mobile browsers with
Next.js + React Three Fiber. The owner asked for "both" web and native; the PWA gives an installable iPhone
app now, and a native shell is the next milestone (see PROGRESS.md).

**D3. Missions run on LangGraph; the database stays the source of truth.** (Revised in increment 3; the first
build used a plain saved-step runner and recorded that as a deliberate swap.) Each mission is a LangGraph thread
(`thread_id` = mission id) over `prepare → execute (one checkpoint per wave of parallel tasks) → await_approval`
(`services/orchestrator/graph.py`). `await_approval` calls `interrupt()`; the owner's decision resumes it with
`Command(resume=...)`; after a crash the worker re-enters the same thread from its last checkpoint. Checkpoints live
in SQLite locally and in Postgres (`PostgresSaver`) when `DATABASE_URL` is Postgres. Tasks, approvals and events stay
in our own tables, and every node is an idempotent wrapper around a runner step, so replaying a node never repeats
finished work and the task graph is still templated, never model-written (D6). `GET /api/missions/{id}/graph`
shows where a mission's graph is.

**D4. SQLite locally, Postgres in production, one schema.** Lets the whole system run and be tested with no
infrastructure. Column names match the Postgres migrations, which the API applies itself on start
(`services/core/pg.py`, recorded in `schema_migrations`, under an advisory lock). On Postgres, ids are real `uuid`,
times `timestamptz` and money `numeric`; psycopg loaders hand them back as strings / ISO-8601 UTC strings / floats and
parameters are sent untyped, so the same queries run on both. pgvector and `auth.uid()` are used when present
(Supabase) and stubbed when not (plain Postgres in CI). The whole test suite runs on both databases in CI.

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

**D8. Real pull requests: git push from the worker + REST, draft only, approval first.** With `AICIV_GITHUB_REPO`
set, the protected `prepare_pull_request` tool (which only runs after the owner grants the approval) hands the
committed patch to `services/integrations/github.py`. The worker — never the sandbox, which has no network — applies
it under `AICIV_GITHUB_SUBDIR` in a clone of the target repository, refuses paths outside it or under `.github/`,
pushes `aiciv/mission-<id>` (never the base branch) and opens a **draft** pull request against `AICIV_GITHUB_BASE`.
A retried task finds the existing pull request instead of opening a second one. Credentials come from a fine-grained
`GITHUB_TOKEN`, a GitHub App, or the host's own git credentials (`AICIV_GITHUB_AUTH=ambient`); the token reaches git
through `GIT_CONFIG_*` environment variables, never argv or `.git/config`.

**D9. Container sandbox runs as the worker's uid, with paths mounted 1:1.** `DockerSandbox` mounts the workspace
(and, for a git worktree, the repository's shared `.git`) at the same absolute path as on the host, so `git -C` and
worktree links work unchanged, and runs as the worker's uid:gid so files stay owned by the worker. Containers are
named and killed on timeout. The image is `infrastructure/docker/sandbox.Dockerfile`.
