"""Live-model smoke test: real calls to the Claude API with the key from the environment. Nothing is simulated.

    ANTHROPIC_API_KEY=... python scripts/live_smoke.py            # ping every model the roster uses
    ANTHROPIC_API_KEY=... python scripts/live_smoke.py --mission  # ...and run one live mission end to end

CI: the "Live models" workflow (manual, .github/workflows/live-models.yml) runs this with the ANTHROPIC_API_KEY
repository secret. Exit codes: 0 all passed, 1 a check failed, 2 no key (nothing was called).
Model identifiers checked against https://platform.claude.com/docs/en/models/overview on 2026-10-14.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EXPECTED_IDS = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"}


def out(line: str, summary: list[str]) -> None:
    print(line, flush=True)
    summary.append(line)


def ping_models(summary: list[str]) -> bool:
    from services.core.config import load_seed
    from services.model_gateway.gateway import ModelGateway, ModelRequest, ProviderError

    roster: dict[str, list[str]] = {}
    for a in load_seed()["agents"]:
        model = os.environ.get(f"AICIV_MODEL_{a['key'].upper()}", a["model"]["model"])
        roster.setdefault(model, []).append(a["name"])
    gw = ModelGateway(max_retries=1, timeout=60)
    ok = True
    out("| model | used by | result | tokens in/out | est. cost | latency |", summary)
    out("|---|---|---|---|---|---|", summary)
    for model, who in sorted(roster.items()):
        if model not in EXPECTED_IDS:
            out(f"| `{model}` | {', '.join(who)} | not in the documented model list; check it | | | |", summary)
        try:
            r = gw.complete(ModelRequest("Reply with exactly: ready", "Are you ready?", max_tokens=16, model=model))
            good = r.model == model and r.output_tokens > 0
            ok &= good
            out(f"| `{r.model}` | {', '.join(who)} | {'ok' if good else 'unexpected'}: {r.text.strip()[:40]!r} "
                f"| {r.input_tokens}/{r.output_tokens} | ${r.estimated_cost_usd:.5f} | {r.latency_ms} ms |", summary)
        except ProviderError as exc:
            ok = False
            out(f"| `{model}` | {', '.join(who)} | FAILED ({exc.kind}): {str(exc)[:160]} | | | |", summary)
    return ok


def live_mission(summary: list[str]) -> bool:
    os.environ.setdefault("AICIV_DATA_DIR", tempfile.mkdtemp(prefix="aiciv-live-"))
    os.environ["AICIV_TRAVEL_SECONDS"] = "0"
    from fastapi.testclient import TestClient

    from services.api.main import app

    prompt = "Inspect the sample project, find a failing test, implement a fix, rerun the tests, and prepare a reviewable code change."
    with TestClient(app) as c:
        mid = c.post("/api/missions", json={"prompt": prompt}).json()["id"]
        deadline = time.time() + 600
        while time.time() < deadline:
            m = c.get(f"/api/missions/{mid}").json()["mission"]
            if m["status"] in ("WAITING_FOR_APPROVAL", "FAILED", "COMPLETED", "CANCELLED") or m.get("paused"):
                break
            time.sleep(2)
        detail = c.get(f"/api/missions/{mid}").json()
        tasks = {t["key"]: t for t in detail["tasks"]}
        mode, status = detail["mission"]["execution_mode"], detail["mission"]["status"]
        source = (tasks.get("implement", {}).get("outputs") or {}).get("patch_source")
        verify = tasks.get("verify", {}).get("outputs") or {}
        costs = c.get("/api/costs")
        usage = costs.json() if costs.status_code == 200 else {}
        out("", summary)
        out(f"Live mission `{mid}`: mode **{mode}**, status **{status}**, patch from **{source}**, "
            f"tests {verify.get('passed')} passed / {verify.get('failed')} failed", summary)
        if status == "FAILED":
            out(f"Failure reason: {detail['mission'].get('failure_reason')}", summary)
        if usage:
            out(f"Usage (estimated, not billed amounts): `{json.dumps(usage)[:400]}`", summary)
        return mode == "live" and status == "WAITING_FOR_APPROVAL" and source == "model" and verify.get("failed") == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mission", action="store_true", help="also run one live mission up to the approval gate")
    args = ap.parse_args()
    summary: list[str] = ["## Live models smoke test", ""]
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("No ANTHROPIC_API_KEY in the environment: nothing was called, nothing is claimed.")
        return 2
    ok = ping_models(summary)
    if args.mission:
        ok &= live_mission(summary)
    out("", summary)
    out("**PASSED**" if ok else "**FAILED**", summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text("\n".join(summary) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
