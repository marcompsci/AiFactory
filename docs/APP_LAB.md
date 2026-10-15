# App Lab

App Lab improves your own apps, with your permission at every step that touches GitHub.

1. **Research.** The Research Division (Pip, Haiku) collects design patterns that people engage with, pay for and
   play. Every pattern has a source. Today these come from a bundled **fixture** library
   (`services/applab/fixtures/design_patterns.json`, labeled everywhere). When live chart research exists, its findings
   are attached as evidence.
2. **Analysis.** A `design_insights` package travels Research Observatory → Code Forge. Kade (Sonnet) reads your
   repository **read-only** (a shallow clone in the worker's data directory) and drafts proposals:
   - the pinned **Claude Code GitHub Action** workflow, if your repository doesn't have it yet. This is a real patch,
     checked with `git apply --check` in a throwaway copy;
   - up to three improvements, each as a task for Claude Code (route `claude_code`). In live mode Kade tailors the
     plan to your files. In simulation the text is a labeled template.
   - Kade can also attach a patch (`draft_patch`) if it applies cleanly to the exact base commit.
3. **The General Manager's briefing.** A `lab_proposal` package travels to Nexus Spire. Atlas checks every proposal
   against rules that a model can tighten but never loosen:
   - no `.github/`, `.git/`, `.env`, secrets or keys, except the pinned workflow template;
   - at most 400 changed lines;
   - the patch must apply to the base commit;
   - a Claude Code task needs Claude Code installed.

   Atlas then briefs you (Opus when a key is configured, a labeled template otherwise). The proposals travel on to
   the Owner's Tower.
4. **You decide.** For each proposal you can **Approve** (step-up, bound to that proposal and its exact payload
   hash), **Reject** or **Later**. Nothing has touched GitHub up to this point.
5. **Publishing.** Your approval creates one `lab_publish` mission. Its tool re-checks the approval inside the
   publishing transaction, then publishes once (compare-and-swap):
   - **patch** → pushed to a new branch `aiciv/lab-<id>` and opened as a **draft** pull request;
   - **claude_code** → opened as an issue labeled `claude` that starts with `@claude`. The Claude Code GitHub Action
     picks it up and opens its own pull request. The instructions forbid pushing to the default branch and touching
     CI, secrets, billing or deployment.

   Nothing is ever pushed to your default branch. Merging is yours, on GitHub.
6. **Tracking.** The lab reads (never writes) the status of what it opened. When something is merged or closed, Atlas
   reports it.

**Autopilot** starts a research cycle every `AICIV_APPLAB_AUTOPILOT_HOURS` (default 24) for repositories you turn it on
for. Publishing still waits for you.

## Connecting a repository

App Lab → Repositories → Connect. Connecting needs step-up (purpose `lab-connect`). Choose one of:

| Credential | When to use it |
|---|---|
| **Fine-grained token** (recommended) | One repository, with Contents, Pull requests and Issues set to read and write. GitHub verifies it before it's stored. It's encrypted with `AICIV_FINANCE_KEY` and never returned by the API. |
| **My GitHub sign-in** | Uses the token from signing in with GitHub with repository access (`repo` scope). That token reaches every repository you can, so prefer a fine-grained token. |
| **Server credentials** | Only when the server sets `AICIV_GITHUB_AUTH=ambient` or `AICIV_APPLAB_ALLOW_AMBIENT=1`, for example behind a proxy that injects credentials. |

**Revoke access** deletes the encrypted token, turns off autopilot, and cancels running cycles.

## Connecting Claude Code

Third-party apps can't offer claude.ai login ([Anthropic's Claude Code legal and compliance page](https://code.claude.com/docs/en/legal-and-compliance)),
so this app never asks for it. The link between you, Claude and your code works like this:

- **Agents** use the server's `ANTHROPIC_API_KEY` (Console). Without it, the app runs in labeled simulation.
- **Claude Code** runs in your GitHub repository through Anthropic's [Claude Code GitHub Action](https://github.com/anthropics/claude-code-action).
  App Lab's first proposal installs `.github/workflows/aiciv-claude-code.yml` (from
  `services/applab/fixtures/claude-code-workflow.yml`). The workflow uses your `CLAUDE_CODE_OAUTH_TOKEN` repository
  secret. Create that token on your own machine with `claude setup-token` (Pro/Max plans), or use
  `ANTHROPIC_API_KEY` instead. You add the secret in GitHub yourself; this app never sees it.
  The workflow runs only for issues labeled `claude` and for comments that mention `@claude`.

## Enforcement (backend, not prompts)

- `services/tools/registry.py::_check_lab`:
  - App Lab missions can use App Lab tools only.
  - Each tool works only for the cycle or proposal its mission was created for, at the right stage, on an active
    repository.
  - `publish_lab_change` additionally needs an owner approval with step-up, the exact payload hash, and issuance to
    that mission.
- `services/applab/lab.py::authorize_publish`:
  - recomputes the payload hash from the stored change;
  - checks the patch digest;
  - refuses anything already published.
- The publisher refuses default branches. It refuses `.github/` and `.git/` paths except the byte-exact pinned
  workflow.
- The token never enters events, tool arguments, tool output or model prompts, and git error messages are scrubbed.
- No code from your repository is ever executed. Analysis reads files; validation is `git apply --check`.

Tests: `tests/integration/test_applab.py`, which uses a local bare repository plus a mock GitHub API. Acceptance log:
`docs/acceptance/app-lab-acceptance-log.md`.
