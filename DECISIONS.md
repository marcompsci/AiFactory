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

**D10. The fee review workflow before account aggregation (V5).** The spec asked for this order. The full path
runs end to end on simulated data: request → bank → research → bank → GM → Owner's Tower → approval → gated
execution. Read-only connectors (CSV, Stripe, Plaid, App Store Connect) plug into the same sync, but no
real account has been connected yet.

**D11. Approvals are for exact terms, and the gate is at the tool.** An approval binds a hash of action, amount
(minor units), currency, recipient, funding account and packet. The tool recomputes it from what it is asked to do
and from the packet's current option, inside the executing transaction. That makes "approved something slightly
different" impossible rather than unlikely. Execution is compare-and-swap, so an approval works once.

**D12. Step-up is TOTP or Supabase `aal2`, not the session.** A stolen session token can read, reject or defer,
but it can't approve: approving needs a fresh second factor bound to that one approval. On iPhone, Face ID is
added on top as a local gate. WebAuthn would be stronger and is the next step.

**D13. No payment, transfer or filing rails.** Approved actions on simulated data are recorded as simulated. On
live data the bank hands the owner a checklist and records the owner's own completion (with step-up). Tax filing
is refused even with an approval. A real rail would be a new executor behind the same gate, never a shortcut
around it.

**D14. Financial data never rides the event stream.** The city, the activity feed and every viewer-visible API
show that a cost review moved, not what it costs. Amounts live only behind `/api/finance` (owners and admins).
Financial tool arguments and results are withheld from `tool_executions` and `tool.*` events.

## V5.1

**D15. Fixture compatibility kits instead of downloading candidates.** The spec says to test the strongest candidate
in an isolated sandbox and never to run downloaded software outside one. This build runs **real pytest** in the
sandbox, against bundled, labeled kits that model each candidate's documented behavior. Results (including Penpot
failing Figma import) are real test outcomes for those kits, not claims about the products. Live candidates are
refused until a vetted download-and-isolate path exists.

**D16. App Lab publishes drafts and issues, never merges.** Merging is the owner's, on GitHub, where branch
protection and CI already live. A draft PR (patch route) or an issue for the Claude Code GitHub Action
(`claude_code` route) keeps a human between the agents and the default branch. The Action runs with the owner's own
`CLAUDE_CODE_OAUTH_TOKEN` secret, which this app never sees.

**D17. No "Sign in with Claude".** Anthropic doesn't allow third-party apps to offer claude.ai login
([legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)). Users sign in with Google or GitHub.
Agents use an API key. Claude Code runs in GitHub through Anthropic's Action.

**D18. The money game scores only verified money.** A leaderboard invites gaming, so no agent and no endpoint can
write a score. The scorer reads executed approvals, owner decisions in the audit chain, and owner-linked revenue,
and splits each amount equally among the agents who did the work. Simulated plays are kept separate.

**D19. A GitHub sign-in token is accepted for App Lab, with a nudge toward fine-grained tokens.** The `repo` OAuth
scope reaches every repository the user can, so the UI recommends a single-repository fine-grained token. Either
way, the owner authorizes one repository at a time, with step-up.

## D20 — Agents on the owner's subscriptions through the official CLIs
Calls go through `codex exec` and `claude -p` rather than reusing plan credentials in our own HTTP client, so each
plan's sign-in, limits and terms stay with its own tool. Both run text-only (read-only sandbox / no tools). Codex
usage comes from Codex's own reports; Claude's is an estimate, labeled as such, plus the hard "limit reached" signal.
