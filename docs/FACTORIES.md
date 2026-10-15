# Claude Code Factory and GitHub Factory

Two buildings at the front of the city, each with its own agent:

- **Claude Code Factory** (Coda, Haiku). Shows your recent Claude Code sessions, the tasks they finished, and
  Claude Code's memory, read from the computer running the API (`~/.claude`, or `AICIV_CLAUDE_HOME`):
  - **Sessions.** From `projects/<project>/*.jsonl`, the app keeps only metadata: the session summary or first
    request (truncated, secrets scrubbed), project folder, branch and timestamps.
  - **Finished tasks.** The titles of tasks marked completed with TodoWrite or TaskUpdate.
  - **Memory.** `~/.claude/CLAUDE.md`, `~/.claude/rules/*.md`, the projects' `CLAUDE.md` and `CLAUDE.local.md`, and
    auto memory in `projects/<project>/memory/*.md`
    ([layout](https://code.claude.com/docs/en/memory)).
- **GitHub Factory** (Rook, Haiku). Shows recent commits, pull requests (App Lab drafts are marked), Actions runs
  (including Claude Code Action runs) and `claude` issues for the repositories you authorized in App Lab. It uses the
  same encrypted token and makes only GET requests.

**How it runs.**
- Both factories are off until the owner links each one (Factories tab). Linking starts a check-in, and then one runs
  every `AICIV_FACTORY_SYNC_MINUTES` (default 5).
- A check-in is a real `factory_sync` mission. Coda and Rook walk to their consoles and make logged, read-only tool
  calls (`sync_claude_code`, `sync_github_activity`).
- The wall boards above the factories and the Factories tab show the result. Owners and admins only.
- Unlinking deletes what was read.

**Shared memory.** Other agents (developer, architect, researchers, QA, the General Manager) can call
`read_claude_code_memory`. App Lab's analysis uses it, so proposals follow conventions Claude Code already learned.
Excerpts are scrubbed and passed to models as untrusted text. They are never written into GitHub issues or pull
requests, and they don't appear in tool logs or events.

**Enforcement.** The `sync_*` tools run only inside `factory_sync` missions. Factory missions can use only factory
tools. Nothing writes to `~/.claude`, to your projects, or to GitHub. Tests: `tests/integration/test_factories.py`.
