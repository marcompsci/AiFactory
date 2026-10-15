"""Read-only GitHub activity for the repositories the owner authorized in App Lab: recent commits on the default
branch, pull requests, Actions runs (including the Claude Code Action) and issues labeled `claude`. Uses the same
encrypted per-repository token; only GET requests."""
from __future__ import annotations

from services.applab import lab as L


def _get(client, path: str, headers: dict, params: dict | None = None):
    r = client.get(path, headers=headers, params=params or {})
    if r.status_code >= 400:
        return None
    return r.json()


def activity(repo) -> dict:
    pub = L.publisher_for(repo)
    headers = pub._headers()
    name = repo.full_name
    out = {"repo": name, "default_branch": repo.default_branch, "commits": [], "pulls": [], "runs": [], "claude_issues": [], "errors": []}
    with L.github_http() as client:
        commits = _get(client, f"/repos/{name}/commits", headers, {"sha": repo.default_branch, "per_page": 8})
        pulls = _get(client, f"/repos/{name}/pulls", headers, {"state": "all", "per_page": 8, "sort": "updated", "direction": "desc"})
        runs = _get(client, f"/repos/{name}/actions/runs", headers, {"per_page": 8})
        issues = _get(client, f"/repos/{name}/issues", headers, {"labels": "claude", "state": "all", "per_page": 6})
    if commits is None:
        out["errors"].append("commits unavailable")
    for c in commits or []:
        out["commits"].append({"sha": c.get("sha", "")[:7], "message": ((c.get("commit") or {}).get("message") or "").splitlines()[0][:120],
                               "author": ((c.get("commit") or {}).get("author") or {}).get("name"),
                               "at": ((c.get("commit") or {}).get("author") or {}).get("date"), "url": c.get("html_url")})
    for p in pulls or []:
        out["pulls"].append({"number": p.get("number"), "title": (p.get("title") or "")[:120], "state": "merged" if p.get("merged_at") else p.get("state"),
                             "draft": bool(p.get("draft")), "by": (p.get("user") or {}).get("login"), "updated_at": p.get("updated_at"),
                             "url": p.get("html_url"), "from_lab": (p.get("head") or {}).get("ref", "").startswith("aiciv/lab-")})
    for r in (runs or {}).get("workflow_runs", []) if isinstance(runs, dict) else []:
        out["runs"].append({"name": r.get("name"), "status": r.get("status"), "conclusion": r.get("conclusion"), "event": r.get("event"),
                            "branch": r.get("head_branch"), "at": r.get("updated_at"), "url": r.get("html_url"),
                            "claude": "claude" in (r.get("name") or "").lower() or "claude" in (r.get("path") or "").lower()})
    for i in issues or []:
        if i.get("pull_request"):
            continue
        out["claude_issues"].append({"number": i.get("number"), "title": (i.get("title") or "")[:120], "state": i.get("state"),
                                     "comments": i.get("comments", 0), "url": i.get("html_url"), "updated_at": i.get("updated_at")})
    return out
