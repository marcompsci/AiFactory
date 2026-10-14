"""Publishing a mission's change as a real GitHub pull request.

Off unless AICIV_GITHUB_REPO is set. Then the protected `prepare_pull_request` tool — which only runs after the
owner granted the approval — hands the committed patch to `GitHubPublisher`, which:

  1. clones / fetches AICIV_GITHUB_REPO at AICIV_GITHUB_BASE (default main) into the data directory,
  2. applies the patch under AICIV_GITHUB_SUBDIR (where the project lives in that repository), refusing any path
     outside it or under .github/,
  3. commits on `aiciv/mission-<id>` and pushes that branch (never the base branch),
  4. opens a **draft** pull request (or returns the existing one, so a retried task does not open two).

Credentials (agents never see them; the sandbox has no network):
  * GITHUB_TOKEN — a fine-grained token with Contents + Pull requests write on that one repository, or
  * a GitHub App: GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY_PATH, GITHUB_APP_INSTALLATION_ID (short-lived installation
    tokens), or
  * AICIV_GITHUB_AUTH=ambient — send no credentials and rely on the host's git credential helper / egress proxy.
The token is passed to git through GIT_CONFIG_* environment variables, never on the command line or in .git/config.
"""
from __future__ import annotations

import base64
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass

import httpx

API = "https://api.github.com"


@dataclass
class GitHubAppConfig:
    app_id: str
    private_key: str
    installation_id: str

    @classmethod
    def from_env(cls) -> "GitHubAppConfig | None":
        app_id = os.environ.get("GITHUB_APP_ID")
        key_path = os.environ.get("GITHUB_APP_PRIVATE_KEY_PATH")
        inst = os.environ.get("GITHUB_APP_INSTALLATION_ID")
        if not (app_id and key_path and inst and os.path.exists(key_path)):
            return None
        with open(key_path) as fh:
            return cls(app_id, fh.read(), inst)


class GitHubApp:
    def __init__(self, cfg: GitHubAppConfig, client: httpx.Client | None = None) -> None:
        self.cfg = cfg
        self.client = client or httpx.Client(base_url=API, timeout=20)
        self._token: tuple[str, float] | None = None

    def _app_jwt(self) -> str:
        import jwt  # RS256 needs the `cryptography` package (listed in requirements-github.txt)

        now = int(time.time())
        return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": self.cfg.app_id}, self.cfg.private_key, algorithm="RS256")

    def installation_token(self) -> str:
        if self._token and self._token[1] > time.time() + 60:
            return self._token[0]
        r = self.client.post(f"/app/installations/{self.cfg.installation_id}/access_tokens",
                             headers={"Authorization": f"Bearer {self._app_jwt()}", "Accept": "application/vnd.github+json"})
        r.raise_for_status()
        token = r.json()["token"]
        self._token = (token, time.time() + 3000)
        return token

    def open_pull_request(self, full_name: str, head: str, base: str, title: str, body: str) -> dict:
        r = self.client.post(f"/repos/{full_name}/pulls",
                             headers={"Authorization": f"Bearer {self.installation_token()}", "Accept": "application/vnd.github+json"},
                             json={"title": title, "head": head, "base": base, "body": body, "draft": True})
        r.raise_for_status()
        return {"number": r.json()["number"], "url": r.json()["html_url"]}


class PublishError(RuntimeError):
    pass


@dataclass
class PublishTarget:
    repo: str            # owner/name
    base: str            # branch the pull request targets
    subdir: str          # where the mission's project lives inside that repository ("" = repository root)
    auth: str            # token | app | ambient

    @classmethod
    def from_env(cls) -> "PublishTarget | None":
        repo = os.environ.get("AICIV_GITHUB_REPO", "").strip()
        if not repo:
            return None
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise PublishError("AICIV_GITHUB_REPO must look like owner/name")
        auth = os.environ.get("AICIV_GITHUB_AUTH") or ("token" if os.environ.get("GITHUB_TOKEN") else "app" if GitHubAppConfig.from_env() else "")
        if auth not in ("token", "app", "ambient"):
            raise PublishError("AICIV_GITHUB_REPO is set but no GitHub credentials are configured (GITHUB_TOKEN, a GitHub App, or AICIV_GITHUB_AUTH=ambient)")
        subdir = os.environ.get("AICIV_GITHUB_SUBDIR", "").strip("/")
        if ".." in subdir.split("/"):
            raise PublishError("AICIV_GITHUB_SUBDIR may not contain ..")
        return cls(repo, os.environ.get("AICIV_GITHUB_BASE", "main"), subdir, auth)


_PATCH_PATH = re.compile(r"^(?:\+\+\+|---) (?:a/|b/)(.+)$|^diff --git a/(\S+) b/(\S+)$", re.M)


def patch_paths(patch: str) -> set[str]:
    out = set()
    for m in _PATCH_PATH.finditer(patch):
        out.update(g for g in m.groups() if g and g != "/dev/null")
    return out


class GitHubPublisher:
    def __init__(self, target: PublishTarget, workdir, client: httpx.Client | None = None, git=None, remote_url: str | None = None) -> None:
        self.t = target
        self.remote_url = remote_url or f"https://github.com/{target.repo}.git"
        self.workdir = workdir
        self.client = client or httpx.Client(base_url=API, timeout=30)
        self._git = git or self._run_git
        self._app = GitHubApp(GitHubAppConfig.from_env(), self.client) if target.auth == "app" else None

    # -- credentials
    def _token(self) -> str | None:
        if self.t.auth == "token":
            return os.environ["GITHUB_TOKEN"]
        if self.t.auth == "app":
            return self._app.installation_token()
        return None

    def _headers(self) -> dict:
        h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        tok = self._token()
        if tok:
            h["Authorization"] = f"Bearer {tok}"
        return h

    def _git_env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy",
                                                             "http_proxy", "no_proxy", "SSL_CERT_FILE", "GIT_SSL_CAINFO", "LANG")}
        env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_NAME": "AI Civilization Agent", "GIT_AUTHOR_EMAIL": "agents@aiciv.local",
                    "GIT_COMMITTER_NAME": "AI Civilization Agent", "GIT_COMMITTER_EMAIL": "agents@aiciv.local"})
        tok = self._token()
        if tok:
            basic = base64.b64encode(f"x-access-token:{tok}".encode()).decode()
            env.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                        "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}"})
        return env

    def _run_git(self, args: list[str], cwd=None) -> str:
        p = subprocess.run(["git", *args], cwd=cwd, env=self._git_env(), capture_output=True, text=True, timeout=180)
        if p.returncode != 0:
            msg = (p.stderr or p.stdout).strip()
            tok = self._token()
            raise PublishError(f"git {args[0]} failed: {msg.replace(tok, '***') if tok else msg}"[:2000])
        return p.stdout

    # -- the publish flow
    def publish(self, mission_id: str, patch: str, title: str, body: str) -> dict:
        paths = patch_paths(patch)
        if not paths:
            raise PublishError("the patch changes no files")
        for p in paths:
            if p.startswith("/") or ".." in p.split("/") or p.startswith(".github/") or p.startswith(".git/"):
                raise PublishError(f"refusing to publish a change to {p}")
        branch = f"aiciv/mission-{mission_id[:8]}"
        repo_dir = self.workdir / self.t.repo.replace("/", "__")
        url = self.remote_url
        if not (repo_dir / ".git").exists():
            repo_dir.parent.mkdir(parents=True, exist_ok=True)
            self._git(["clone", "--quiet", "--depth", "1", "--branch", self.t.base, url, str(repo_dir)])
        else:
            self._git(["fetch", "--quiet", "--depth", "1", "origin", self.t.base], cwd=repo_dir)
        self._git(["checkout", "--quiet", "--force", "-B", branch, f"origin/{self.t.base}"], cwd=repo_dir)
        self._git(["clean", "-fdq"], cwd=repo_dir)
        with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False) as fh:
            fh.write(patch if patch.endswith("\n") else patch + "\n")
            patch_file = fh.name
        try:
            args = ["apply", "--index", "--whitespace=nowarn"]
            if self.t.subdir:
                args.append(f"--directory={self.t.subdir}")
            self._git([*args, patch_file], cwd=repo_dir)
        finally:
            os.unlink(patch_file)
        self._git(["commit", "--quiet", "-m", title[:120], "-m", body[:4000]], cwd=repo_dir)
        commit = self._git(["rev-parse", "HEAD"], cwd=repo_dir).strip()
        self._git(["push", "--quiet", "--force", "origin", f"HEAD:refs/heads/{branch}"], cwd=repo_dir)
        return {**self._open_or_find_pr(branch, title, body), "branch": branch, "commit": commit, "repo": self.t.repo, "base": self.t.base}

    def _open_or_find_pr(self, branch: str, title: str, body: str) -> dict:
        owner = self.t.repo.split("/")[0]
        r = self.client.post(f"/repos/{self.t.repo}/pulls", headers=self._headers(),
                             json={"title": title, "head": branch, "base": self.t.base, "body": body, "draft": True})
        if r.status_code == 422 and "already exists" in r.text:
            r = self.client.get(f"/repos/{self.t.repo}/pulls", headers=self._headers(), params={"head": f"{owner}:{branch}", "state": "open"})
            r.raise_for_status()
            pr = r.json()[0]
            return {"pr_number": pr["number"], "pr_url": pr["html_url"], "created": False}
        if r.status_code >= 400:
            raise PublishError(f"GitHub refused the pull request ({r.status_code}): {r.text[:500]}")
        pr = r.json()
        return {"pr_number": pr["number"], "pr_url": pr["html_url"], "created": True}
