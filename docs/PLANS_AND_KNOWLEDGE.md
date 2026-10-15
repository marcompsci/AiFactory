# Plans, the Codex Factory and the company knowledge base

## Agents on your own plans

Set `AICIV_USE_PLANS=1` in `.env` and every agent model call goes through the official command-line tool for a plan
you're signed in to on the computer that runs the API. No API key is needed and none is used as a fallback.

| Order | Plan | How | Stops when |
|---|---|---|---|
| 1 | Codex (ChatGPT plan) | `codex exec --json --sandbox read-only` in an empty folder (`~/.aiciv/agent-workdir`) | Codex's own 5-hour or weekly window reaches the stop line (default 95%), or Codex answers "usage limit" |
| 2 | Claude plan | `claude -p --tools "" --strict-mcp-config --no-session-persistence --max-turns 1` | Claude answers "limit reached", or (if you set a 5-hour budget) the estimate reaches the share kept for you (default: agents stop at 60%, 40% stays yours) |
| — | nothing left | the task waits (`quota`), visible on the Tasks tab | — |

**While you're using Claude**, agents on the Claude plan use the smallest model (Haiku) so your own work has room.
"Using Claude" means a Claude Code session you wrote to in the last 10 minutes (the agents' own runs don't count), or the
Claude app open on the Mac (on by default; switch off with `app_open_counts_as_active`).

Both CLIs only ever return text: the agents' tools stay the app's own, permission-checked tools. Sign in once in
Terminal (`codex` → sign in with ChatGPT; `claude` → `/login`). Use is subject to each plan's terms and limits.

### The meters

- **Codex** — Codex writes its rate-limit status (`rate_limits.primary` 5-hour, `secondary` weekly) into
  `~/.codex/sessions/**/rollout-*.jsonl`; the meter reads the latest report. Labeled "reported by Codex".
- **Claude** — there's no public usage figure for subscriptions, so the meter is an **estimate**: tokens in your Claude
  Code sessions in the last 5 hours plus the agents' recorded calls, against a 5-hour token budget you set in
  Factories → Plan meters. Without a budget it shows the token count only.

Every check-in (every 5 minutes) **Nyx** (Codex Factory) and **Coda** (Claude Code Factory) read the meters and brief
every agent in the mission log, and each agent's instructions carry a one-line usage budget ("Codex plan 42% of 5h…
be brief") on every call.

Settings (Factories → Plan meters, or environment): `codex_stop_percent` (`AICIV_CODEX_STOP_PERCENT`),
`claude_reserve_percent` (`AICIV_CLAUDE_RESERVE_PERCENT`), `claude_5h_token_budget` (`AICIV_CLAUDE_5H_TOKEN_BUDGET`),
`owner_active_minutes` (`AICIV_OWNER_ACTIVE_MINUTES`), `app_open_counts_as_active`, `prefer` (`codex` or `claude`).
Optional: `AICIV_CODEX_MODEL` (Codex model for agents), `AICIV_CODEX_BIN` / `AICIV_CLAUDE_BIN`, `AICIV_CODEX_HOME`.

## Codex Factory

Next to the Claude Code and GitHub factories. Link it on the Factories tab to show recent Codex sessions and the plan
steps Codex marked complete, and to share `~/.codex/AGENTS.md` (and project `AGENTS.md`) with the other agents through
`read_codex_memory`, the same way Claude Code's memory is shared. Read-only, secrets scrubbed, owner/admin only. Sessions
the agents ran are labeled "agents".

## Company knowledge base

Floating over the middle of the city: the Phoronomics and Phoronomic Studios library. Click the sign (or the
Knowledge tab) to manage it.

- **Docs and skills.** A `SKILL.md` (or any Markdown file with `name:` and `description:` front matter) is a skill.
- **Owners and admins** add, edit, upload (`.md`/`.txt`, 400 KB each) and delete; every member reads.
- **Agents** get the one or two clearly relevant entries automatically with each model call, and can search and read the
  rest with `search_knowledge_base` and `read_knowledge_document`. Each pull is logged (`knowledge.consulted`) and the
  crystal flashes. Entries are owner-curated guidance and never override safety rules, approvals or tool permissions.
- **Folder import.** Files in `knowledge/skills/`, `knowledge/phoronomics/` and `knowledge/phoronomic-studios/`
  (`AICIV_KNOWLEDGE_DIR`) are imported when the API starts; changed files update their entry. These folders are
  gitignored, so your skills stay on your computer.
