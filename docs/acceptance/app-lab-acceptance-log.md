# App Lab acceptance run

Recorded 2026-10-14 19:42:04 PDT by tests/integration/test_applab.py.
GitHub is a local bare repository (git over file://) plus a mock REST API. Design patterns come from the **FIXTURE** pattern library; no model key, so proposal text is the labeled simulation template.

1. Owner connected `owner/habit-app` with step-up; GitHub verified write access; the token is stored encrypted and never returned. Without step-up: 401. With a token GitHub rejects: 400.
2. Cycle travelled data-observatory → code-forge → nexus-spire → owners-tower as physical packages; research produced 6 design insight(s), each with a source.
3. Code Forge read the repository (read-only) and drafted 4 proposal(s): the pinned Claude Code workflow (patch; `git apply --check` passed) and 3 Claude Code task(s). The General Manager reviewed every one (`authorizes_publish: false`) and briefed the owner. **Nothing was pushed: GitHub still has only `main`.**
4. Approval without step-up: 401; with a step-up token for another proposal: 401; with a different payload hash: 409. The approved install was pushed to `aiciv/lab-39951e95` and opened as **draft** PR #1; `main` is unchanged.
5. A second approved proposal was handed to Claude Code as issue #2 labeled `claude`, whose instructions forbid pushing to the default branch and touching CI or secrets.
6. Remaining proposals rejected; the cycle finished `DONE`. Re-approving a published proposal: 409. After the PR was merged on GitHub, status tracking (read-only) picked it up and the General Manager reported it. No event contains the token.
7. Owner revoked access: the encrypted token was deleted and new cycles are refused (409).
