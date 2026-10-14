"""GitHubPublisher against a local bare repository standing in for github.com, and a mocked REST API.
The real-GitHub run is recorded in docs/acceptance/github-pr-log.md."""
import json
import subprocess

import httpx
import pytest

from services.integrations.github import GitHubPublisher, PublishError, PublishTarget, patch_paths

PATCH = """diff --git a/calc/stats.py b/calc/stats.py
--- a/calc/stats.py
+++ b/calc/stats.py
@@ -1,2 +1,2 @@
 def median(xs):
-    return xs[len(xs) // 2]
+    return sorted(xs)[len(xs) // 2]
"""


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                               "GIT_COMMITTER_EMAIL": "t@t", "HOME": str(cwd or "/tmp")}).stdout


@pytest.fixture
def remote(tmp_path):
    seed = tmp_path / "seed"
    (seed / "projects/calc/calc").mkdir(parents=True)
    (seed / "projects/calc/calc/stats.py").write_text("def median(xs):\n    return xs[len(xs) // 2]\n")
    git("init", "-q", "-b", "demo", cwd=seed)
    git("add", "-A", cwd=seed)
    git("commit", "-q", "-m", "seed", cwd=seed)
    bare = tmp_path / "remote.git"
    git("clone", "-q", "--bare", str(seed), str(bare))
    return bare


def api(calls, existing=False):
    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path, json.loads(req.content) if req.content else dict(req.url.params)))
        if req.method == "POST" and existing:
            return httpx.Response(422, json={"message": "Validation Failed", "errors": [{"message": "A pull request already exists for o:b."}]})
        if req.method == "POST":
            return httpx.Response(201, json={"number": 7, "html_url": "https://github.com/o/r/pull/7"})
        return httpx.Response(200, json=[{"number": 7, "html_url": "https://github.com/o/r/pull/7"}])
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.github.com")


def publisher(tmp_path, remote, calls, existing=False):
    return GitHubPublisher(PublishTarget("o/r", "demo", "projects/calc", "ambient"), tmp_path / "work",
                           client=api(calls, existing), remote_url=str(remote))


def test_publishes_patch_under_subdir_on_a_mission_branch_and_opens_a_draft_pr(tmp_path, remote):
    calls = []
    out = publisher(tmp_path, remote, calls).publish("abcdef1234", PATCH, "Fix median", "why")
    assert out["pr_url"] == "https://github.com/o/r/pull/7" and out["branch"] == "aiciv/mission-abcdef12" and out["created"]
    method, path, payload = calls[0]
    assert (method, path) == ("POST", "/repos/o/r/pulls")
    assert payload["draft"] is True and payload["base"] == "demo" and payload["head"] == "aiciv/mission-abcdef12"
    shown = git("--git-dir", str(remote), "show", "aiciv/mission-abcdef12:projects/calc/calc/stats.py")
    assert "sorted(xs)" in shown
    # the base branch is untouched
    assert "sorted" not in git("--git-dir", str(remote), "show", "demo:projects/calc/calc/stats.py")


def test_retry_returns_the_existing_pr(tmp_path, remote):
    calls = []
    publisher(tmp_path, remote, []).publish("abcdef1234", PATCH, "Fix median", "why")
    out = publisher(tmp_path, remote, calls, existing=True).publish("abcdef1234", PATCH, "Fix median", "why")
    assert out["pr_number"] == 7 and out["created"] is False
    assert calls[1][0] == "GET" and calls[1][2]["head"] == "o:aiciv/mission-abcdef12"


@pytest.mark.parametrize("path", [".github/workflows/x.yml", "../escape.py", ".git/config"])
def test_refuses_dangerous_paths(tmp_path, remote, path):
    bad = PATCH.replace("calc/stats.py", path)
    with pytest.raises(PublishError):
        publisher(tmp_path, remote, []).publish("abcdef1234", bad, "x", "y")


def test_target_requires_credentials(monkeypatch):
    monkeypatch.setenv("AICIV_GITHUB_REPO", "o/r")
    with pytest.raises(PublishError):
        PublishTarget.from_env()
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    assert PublishTarget.from_env().auth == "token"


def test_patch_paths():
    assert patch_paths(PATCH) == {"calc/stats.py"}
