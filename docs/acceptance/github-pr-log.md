# Real pull request from a mission — run log (Oct 14, 2026)

**Result:** a mission opened draft pull request
[marcompsci/AiFactory#2](https://github.com/marcompsci/AiFactory/pull/2), only after its publish step was approved.

## Setup

```
AICIV_GITHUB_REPO=marcompsci/AiFactory
AICIV_GITHUB_BASE=demo/agent-prs          # a branch made for this demo; main is never targeted
AICIV_GITHUB_SUBDIR=services/api/sample_repo
AICIV_GITHUB_AUTH=ambient                 # the build environment's git credentials; no token was handled by the app
AICIV_SANDBOX=docker                      # every tool command ran in its own container
```

The API ran with `uvicorn` and was driven over HTTP (`POST /api/missions`, then `POST /api/approvals/{id}/grant`).

## What happened

| Step | Result |
|---|---|
| Mission `f0f8b82b-deae-4eb0-8a9e-d8e1b319a1bc` | inspect → reproduce → implement → verify → review → publish → archive, all COMPLETED |
| Tests before the fix | `tests/test_stats.py::test_median_even` failing (real pytest, in a container) |
| Tests after the fix | 5 passed, 0 failed (real pytest, in a container) |
| Stopped at | WAITING_FOR_APPROVAL; nothing was pushed before the grant |
| After the grant | `prepare_pull_request` committed locally, pushed `aiciv/mission-f0f8b82b`, opened draft PR #2 into `demo/agent-prs` (5.8 s) |
| Pull request | draft, 1 file (`services/api/sample_repo/calc/stats.py`), +1 −1, head `6c7a398` |
| Mission message | "Opened draft pull request #2 on marcompsci/AiFactory (aiciv/mission-f0f8b82b into demo/agent-prs): https://github.com/marcompsci/AiFactory/pull/2" |

**Honest labels:** the mission ran in **simulation mode** (no model key in this environment), so the patch came from
the sample repository's labeled fixture (`.aiciv/known_fix.json`), not from a model. The tests, the git operations,
the push and the pull request are real.

An earlier run (PR #1) failed on its first attempt because compiled `__pycache__` files were committed along with
the fix; the sample repository now ignores them and a retried publish step no longer tries to commit twice.
PR #1 was closed as superseded.

## Covered by automated tests

`tests/unit/test_github_publisher.py` runs the same publisher against a local bare repository and a mocked REST API:
branch naming, subdirectory placement, base branch untouched, draft flag, re-use of an existing PR on retry, and
refusal of `.github/`, `.git/` and `..` paths.
