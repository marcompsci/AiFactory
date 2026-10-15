# Security model

Zero-trust between the UI, the agents and the tools. Nothing an agent, another agent, a repository file or a
web page says can widen what a tool call is allowed to do.

## Controls and where they live

| Control | Implementation | Verified by |
|---|---|---|
| Authentication | `services/core/auth.py`: dev (localhost only), static bearer token (constant-time compare), or Supabase Auth JWT (HS256, `aud=authenticated`) | `test_token_auth`, `test_supabase_jwt_roles`, `test_remote_clients_refused_in_dev_mode` |
| Role-based authorization | viewer < operator < admin < owner; missions/approvals need operator, budgets/emergency stop/memory deletion need admin | `test_supabase_jwt_roles` |
| Organization isolation | every query filters by `organization_id`; Postgres RLS policies (`is_member()`) on every table; outbox has no client policy | migration `0001_init.sql` |
| Tool permissions | `execute_tool` checks emergency stop, agent capability, task `permitted_tools`, project `allowed_tools`, task ownership, mission state | `test_unauthorized_tool_request_is_denied_and_audited` |
| Approval at execution time | protected tools require a GRANTED approval row for the exact task, re-read inside the transaction that records the start; expired approvals never count | `test_protected_tool_denied_without_approval`, `test_recovery_after_worker_interruption` |
| Audit | every call (including denials, stored in their own transaction) → `tool_executions` + `tool.*` event; agent audit trail in the inspector | same tests |
| Sandboxed execution | argv allowlist (`python -m pytest|compileall`, limited `git` subcommands), no shell, workspace jail incl. symlinks and `git -C`, scrubbed env (no keys), CPU/memory/file/FD rlimits, process-group kill on timeout, empty network namespace (`unshare --net`) when available; DockerSandbox: `--network none --read-only --cap-drop ALL --no-new-privileges --pids-limit --memory --cpus`, the worker's uid, named and killed on timeout | `test_sandbox_*`, `test_confine_blocks_escapes`, `test_docker_sandbox_command_is_locked_down`, and in real containers (CI `sandbox` job) `test_container_has_no_network_and_a_read_only_root`, `test_timeout_kills_the_container`, `test_whole_mission_runs_its_tools_in_containers` |
| Pull requests only after approval, only as drafts | `prepare_pull_request` is protected; the worker (not the sandbox) pushes `aiciv/mission-<id>`, never the base branch; patches touching `.github/`, `.git/`, absolute or `..` paths are refused; token passed to git via `GIT_CONFIG_*` env, redacted from errors | `tests/unit/test_github_publisher.py`; real run in `docs/acceptance/github-pr-log.md` |
| No host Docker socket for agents | agents only reach tools; only the worker process may talk to a container runtime | design + `test_docker_sandbox_command_is_locked_down` |
| Prompt-injection defense | repo/web text fenced in `<untrusted>` with a system rule never to follow it; model output only becomes an `edit_file` call after schema checks; edits to `tests/` refused; sample repo ships an injection canary | `test_live_mode_uses_model_patch_and_records_cost`, `test_model_cannot_make_tests_pass_by_editing_tests` |
| Secret management | env vars only; `.env` git-ignored; outputs and arguments redacted (Anthropic/OpenAI/GitHub/JWT patterns); service-role key never sent to the browser | `test_secret_redaction` |
| Rate limiting | token bucket per principal on mutations (use Redis for multiple instances) | `test_rate_limiter` |
| Budgets | per-mission, per-agent and daily caps checked before every model call; breach suspends (pauses) the mission | `test_budget_exhaustion_suspends_mission` |
| Cancellation / emergency stop | cancel per mission; emergency stop cancels all and blocks every tool call until released | `test_cancel_mission`, `test_emergency_stop_blocks_everything` |
| Dependency scanning | `npm audit --audit-level=high` in CI | `.github/workflows/ci.yml` |
| Memory trust | `verified` entries must cite a tool execution or artifact; model text is stored as `hypothesis`; nothing is promoted automatically | `test_verified_memory_requires_source` |

## V4.0 controls

| Control | Implementation | Verified by |
|---|---|---|
| Owner-only release decisions | `owner` role required; admins and the General Manager cannot decide | `test_viewer_cannot_approve_releases` |
| Exact-artifact approval | owner request must carry the reviewed digest; authorization bound to artifact id + sha256 | acceptance test steps 6, 8 |
| Release enforced at the tool boundary | `submit_release` checks authorization, invalidations, newest bundle and on-disk hash inside `execute_tool` | acceptance test steps 5, 9 |
| Tamper detection | supervisor and the gate re-hash bundles; mismatch → append-only invalidation → rebuild + renewed reviews | acceptance test step 8 |
| Append-only decisions | Postgres triggers / SQLite triggers forbid UPDATE/DELETE on owner decisions, authorizations, invalidations | `test_owner_decisions_are_append_only` |
| Manager cannot loosen rules | Opus output may only reject or tighten | `test_gm_model_can_only_tighten` |
| Spending beyond delegation | escalates to the owner (`owner-commit`) | `test_spend_beyond_delegated_limit_escalates_to_owner` |
| Low-confidence research | never routed to production | `test_low_confidence_research_never_reaches_production` |
| Compliant data access | no scraping; Depop only via configured partner API; Etsy 429 is respected; fixtures labeled everywhere | connector unit tests |
| Prototype preview isolation | rendered via `srcDoc` in an iframe sandboxed without `allow-same-origin`; API serves bundle files with a CSP | Owner's Tower code + `bundle_file` headers |
| Bundle extraction | rejects path traversal entries | `test_bundle_is_deterministic_and_safe` |
| Untrusted research text | fenced in `<untrusted>` in every Haiku/Opus prompt; the spec used for building is read from the approved record, never from tool arguments | `scaffold_prototype` |

## Financial district (V5)

The AI Central Bank has its own threat model with 17 enforced rules and the test for each:
[docs/finance/THREAT_MODEL.md](docs/finance/THREAT_MODEL.md). In short:
- no money moves without an owner approval for exact terms, with step-up, unexpired and unused;
- financial tools belong to the finance department, are scoped to one packet, and are re-checked at execution;
- integrations are read-only and authorized explicitly in this app;
- credentials are Fernet-encrypted (`AICIV_FINANCE_KEY`, required outside dev mode);
- events and models see no amounts or account data;
- the audit log is append-only and hash-chained;
- simulated data is labeled everywhere;
- tax filing is always refused.

## Known gaps (tracked in PROGRESS.md)

- The process sandbox is a good local default, not a security boundary against a hostile kernel exploit.
  Use `AICIV_SANDBOX=docker` (or gVisor/Firecracker) in production. Run the worker as a non-root user (the
  container inherits its uid; as root it would be root with every capability dropped) or enable Docker
  `userns-remap`.
- Rate limiting and the mission queue are in-process; multi-instance deployments need Redis.
- Supabase JWT mode maps every user to the seed organization; multi-org membership lookup is not wired yet.
- Python dependency scanning (`pip-audit`) is not in CI yet.
- No real Opus/Sonnet/Haiku call has been made yet: the build environment has no API key. The manual "Live models"
  workflow (`scripts/live_smoke.py`) makes those calls once an `ANTHROPIC_API_KEY` repository secret exists.
- The API connects to Postgres as the table owner (service role), so RLS read policies protect direct client
  access, not the API itself; organization scoping in the API is by query.
- Financial step-up uses TOTP (or Supabase aal2); WebAuthn/passkeys would resist phishing better.
- Financial rate limiting shares the in-process mutation limiter (single instance).
- Live Etsy, Depop, Apple and App Store Connect access was not exercised (no credentials or network); fixtures cover those paths.

## Reporting

Open a private security advisory on the GitHub repository.
