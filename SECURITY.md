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

## Backend hardening (V5.1)

| Control | Implementation | Verified by |
|---|---|---|
| Security headers on every response | `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, a locked-down `Permissions-Policy`, a deny-all CSP for JSON (file routes set their own), `Cache-Control: no-store` on the API, HSTS behind HTTPS (`AICIV_HSTS`) | `test_security_headers_on_every_response` |
| Request body caps | 1 MB (`AICIV_MAX_BODY_BYTES`), 20 MB for uploads, enforced on declared and chunked bodies | `test_oversized_bodies_are_refused` |
| Token rules | Supabase tokens must be signed (HS256 secret or ES256/RS256 JWKS), unexpired (`exp` required, 30 s leeway), for `aud=authenticated`, from this project's issuer when `SUPABASE_URL` is set; `alg=none` and oversized tokens refused; static token compared in constant time | `test_tokens_must_be_unexpired_signed_and_for_this_audience`, `test_issuer_is_enforced_when_supabase_url_is_set` |
| Credential stuffing | 10 bad tokens from one address in 5 minutes → that address gets 429 for 15 minutes | `test_repeated_bad_tokens_lock_out_the_client` |
| Step-up brute force | 5 wrong authenticator codes in 10 minutes → step-up locked for 15 minutes for that user | `test_step_up_codes_lock_after_five_wrong_tries` |
| Request budget | 600 requests per minute per client address across the API (`AICIV_REQUESTS_PER_MINUTE`), on top of the per-user mutation limiter | `test_request_budget_per_client` |
| Authorization before parsing | every mutating route resolves the caller before reading the body; anonymous → 401, viewer → 403 on all of them | `test_no_mutating_route_accepts_anonymous_or_viewer_requests` (walks every route) |
| No internals in errors | unexpected errors return `{"detail":"internal error","request_id":…}`; the stack trace is only in the server log under that id | `HardeningMiddleware` |
| Smaller attack surface | `/docs` and `/openapi.json` only in local dev mode; optional `AICIV_ALLOWED_HOSTS` (Host header allow-list); CORS never allows `*` | `test_api_docs_are_off_outside_dev_mode` |
| Public config is public-only | `/api/public-config` (unauthenticated, for the iPhone app) returns only the Supabase address and a key that must look publishable (`sb_publishable_…`/anon JWT); anything else, or the service-role key, is blanked | `test_public_config_exposes_only_public_values` |
| iPhone sign-in | OAuth PKCE (S256) in `ASWebAuthenticationSession`; session in the iOS Keychain, refreshed before expiry; App Lab approval needs Face ID then the server step-up | `V51Tests` (iOS CI) |
| Plan CLIs return text only | Agents' calls to `codex exec` run with `--sandbox read-only` in an empty folder; `claude -p` runs with `--tools ""`, no MCP, one turn, no saved session. The app never reads or stores plan credentials; nothing falls back to a paid key | `test_codex_first_then_claude_then_nothing` |
| Knowledge base can't widen permissions | Owner/admin write only; entries reach models labeled as owner-curated guidance below the safety rules; agents only read; uploads limited to .md/.txt, 400 KB | `test_knowledge_base_crud_upload_and_agents_pull_skills`, role matrix |
| Supply chain | `pip-audit` and `npm audit --audit-level=high` block CI (`security` job); a repo scan fails the build if keys, tokens or private keys are committed | `security` job, `test_no_secrets_are_committed` |

## Known gaps (tracked in PROGRESS.md)

- The process sandbox is a good local default, not a security boundary against a hostile kernel exploit.
  Use `AICIV_SANDBOX=docker` (or gVisor/Firecracker) in production. Run the worker as a non-root user (the
  container inherits its uid; as root it would be root with every capability dropped) or enable Docker
  `userns-remap`.
- Rate limiting and the mission queue are in-process; multi-instance deployments need Redis.
- Supabase JWT mode maps every user to the seed organization; multi-org membership lookup is not wired yet.
- No real Opus/Sonnet/Haiku call has been made yet: the build environment has no API key. The manual "Live models"
  workflow (`scripts/live_smoke.py`) makes those calls once an `ANTHROPIC_API_KEY` repository secret exists.
- The API connects to Postgres as the table owner (service role), so RLS read policies protect direct client
  access, not the API itself; organization scoping in the API is by query.
- Financial step-up uses TOTP (or Supabase aal2); WebAuthn/passkeys would resist phishing better.
- Financial rate limiting shares the in-process mutation limiter (single instance).
- Live Etsy, Depop, Apple and App Store Connect access was not exercised (no credentials or network); fixtures cover those paths.

## Reporting

Open a private security advisory on the GitHub repository.
