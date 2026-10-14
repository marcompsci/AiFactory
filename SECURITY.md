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
| Sandboxed execution | argv allowlist (`python -m pytest|compileall`, limited `git` subcommands), no shell, workspace jail incl. symlinks and `git -C`, scrubbed env (no keys), CPU/memory/file/FD rlimits, process-group kill on timeout, empty network namespace (`unshare --net`) when available; DockerSandbox: `--network none --read-only --cap-drop ALL --no-new-privileges --pids-limit --user 65534` | `test_sandbox_*`, `test_confine_blocks_escapes`, `test_docker_sandbox_command_is_locked_down` |
| No host Docker socket for agents | agents only reach tools; only the worker process may talk to a container runtime | design + `test_docker_sandbox_command_is_locked_down` |
| Prompt-injection defense | repo/web text fenced in `<untrusted>` with a system rule never to follow it; model output only becomes an `edit_file` call after schema checks; edits to `tests/` refused; sample repo ships an injection canary | `test_live_mode_uses_model_patch_and_records_cost`, `test_model_cannot_make_tests_pass_by_editing_tests` |
| Secret management | env vars only; `.env` git-ignored; outputs and arguments redacted (Anthropic/OpenAI/GitHub/JWT patterns); service-role key never sent to the browser | `test_secret_redaction` |
| Rate limiting | token bucket per principal on mutations (use Redis for multiple instances) | `test_rate_limiter` |
| Budgets | per-mission, per-agent and daily caps checked before every model call; breach suspends (pauses) the mission | `test_budget_exhaustion_suspends_mission` |
| Cancellation / emergency stop | cancel per mission; emergency stop cancels all and blocks every tool call until released | `test_cancel_mission`, `test_emergency_stop_blocks_everything` |
| Dependency scanning | `npm audit --audit-level=high` in CI | `.github/workflows/ci.yml` |
| Memory trust | `verified` entries must cite a tool execution or artifact; model text is stored as `hypothesis`; nothing is promoted automatically | `test_verified_memory_requires_source` |

## Known gaps (tracked in PROGRESS.md)

- The process sandbox is a good local default, not a security boundary against a hostile kernel exploit.
  Use `AICIV_SANDBOX=docker` (or gVisor/Firecracker) in production.
- Rate limiting and the mission queue are in-process; multi-instance deployments need Redis.
- Supabase JWT mode maps every user to the seed organization; multi-org membership lookup is not wired yet.
- Python dependency scanning (`pip-audit`) is not in CI yet.

## Reporting

Open a private security advisory on the GitHub repository.
