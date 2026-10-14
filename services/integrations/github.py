"""GitHub App integration (adapter).

Enabled only when GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY_PATH and GITHUB_APP_INSTALLATION_ID are set.
Agents never hold these credentials: the worker exchanges the App JWT for a short-lived installation
token scoped to the repositories the operator authorized, and only the protected `prepare_pull_request`
path (after a granted approval) calls `open_pull_request`.

Not exercised against GitHub in this build — see PROGRESS.md "Known limitations".
"""
from __future__ import annotations

import os
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
