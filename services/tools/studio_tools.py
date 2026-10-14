"""V4 tools: market research, App Studio prototype + bundle, QA staging, gated release.
Registered into the same registry, so capability, task, project, emergency-stop and audit checks apply."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from sqlalchemy import insert, select, update

from services.core import db
from services.core.config import get_settings
from services.core.events import emit, transaction
from services.research import service as research
from services.studio import bundle as bundles
from services.studio.template import render

from .registry import ToolContext, ToolFailed, redact, tool


def _opportunity(conn, ctx: ToolContext, opportunity_id: str):
    m = conn.execute(select(db.missions).where(db.missions.c.id == ctx.mission_id)).first()
    if m.opportunity_id != opportunity_id:
        raise ToolFailed("this mission is not working on that opportunity")
    o = conn.execute(select(db.opportunities).where(db.opportunities.c.id == opportunity_id)).first()
    if o is None:
        raise ToolFailed("unknown opportunity")
    return o


@tool("query_market_source", description="Query a permitted market data source (rate-limited, cached, cited).")
def query_market_source(ctx: ToolContext, source: str, query: str, region: str = "US") -> dict:
    if len(query) > 80 or not query.strip():
        raise ToolFailed("query must be 1-80 characters")
    if source not in ("apple_charts", "etsy", "depop", "app_store_connect"):
        raise ToolFailed(f"source not permitted: {source}")
    try:
        r = research.run(transaction, org_id=ctx.org_id, agent_id=ctx.agent_id, mission_id=ctx.mission_id,
                         source_key=source, query=query, region=region.upper()[:2])
    except research.ResearchLimit as exc:
        raise ToolFailed(str(exc)) from exc
    return {"run_id": r["run_id"], "status": r["status"], "data_mode": r.get("data_mode"), "from_cache": r.get("from_cache"),
            "finding_ids": [f["id"] for f in r["findings"]], "notice": r.get("notice", ""), "reason": r.get("reason")}


@tool("scaffold_prototype", description="Generate the App Studio prototype for an approved opportunity spec.")
def scaffold_prototype(ctx: ToolContext, opportunity_id: str) -> dict:
    with db.get_engine().connect() as conn:
        o = _opportunity(conn, ctx, opportunity_id)
    spec = {**(o.spec or {}), "opportunity_id": o.id}  # spec comes from the approved record, not from agent arguments
    files = render(spec)
    root = ctx.workspace
    if root.exists():
        shutil.rmtree(root)
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return {"files": sorted(files), "app_name": spec.get("app_name"), "features": spec.get("features")}


@tool("build_release_bundle", description="Package the prototype as a deterministic, digest-identified release bundle.")
def build_release_bundle(ctx: ToolContext, opportunity_id: str) -> dict:
    with db.get_engine().connect() as conn:
        o = _opportunity(conn, ctx, opportunity_id)
    if not ctx.workspace.exists():
        raise ToolFailed("nothing to bundle; scaffold first")
    aid = db.new_id()
    dest = get_settings().data_dir / "artifacts" / f"{aid}.zip"
    digest, manifest = bundles.make(ctx.workspace, dest)
    with transaction() as conn:
        conn.execute(insert(db.artifacts).values(id=aid, organization_id=ctx.org_id, mission_id=ctx.mission_id, task_id=ctx.task_id,
                                                 agent_id=ctx.agent_id, kind="release_bundle", title=f"{(o.spec or {}).get('app_name', 'Prototype')} bundle {digest[:10]}",
                                                 content=json.dumps({"digest": digest, "files": manifest}, indent=2), storage_path=str(dest),
                                                 digest=digest, opportunity_id=o.id))
        conn.execute(update(db.opportunities).where(db.opportunities.c.id == o.id).values(release_artifact_id=aid))
        emit(conn, "artifact.created", mission_id=ctx.mission_id, agent_id=ctx.agent_id, execution_mode=ctx.execution_mode,
             payload={"artifact_id": aid, "kind": "release_bundle", "title": f"bundle {digest[:10]}", "digest": digest})
    return {"artifact_id": aid, "digest": digest, "files": len(manifest), "bytes": dest.stat().st_size}


@tool("stage_bundle", description="Verify a release bundle's digest and unpack it for testing.")
def stage_bundle(ctx: ToolContext, artifact_id: str) -> dict:
    with db.get_engine().connect() as conn:
        a = conn.execute(select(db.artifacts).where(db.artifacts.c.id == artifact_id, db.artifacts.c.kind == "release_bundle")).first()
        m = conn.execute(select(db.missions).where(db.missions.c.id == ctx.mission_id)).first()
    if a is None or a.opportunity_id != m.opportunity_id:
        raise ToolFailed("no such bundle for this mission's opportunity")
    observed = bundles.digest(Path(a.storage_path))
    if observed != a.digest:
        raise ToolFailed(f"bundle digest mismatch: recorded {a.digest[:12]}, found {observed[:12]}")
    n = bundles.extract(Path(a.storage_path), ctx.workspace)
    return {"artifact_id": a.id, "digest": observed, "files": n}


@tool("submit_release", release_gate=True, description="Release an owner-authorized bundle to the local release channel.")
def submit_release(ctx: ToolContext, authorization_id: str) -> dict:
    """Local release channel only (data/releases). App Store submission needs a separate, not-yet-built adapter
    and would sit behind this same gate."""
    with db.get_engine().connect() as conn:
        auth = conn.execute(select(db.release_authorizations).where(db.release_authorizations.c.id == authorization_id)).first()
        art = conn.execute(select(db.artifacts).where(db.artifacts.c.id == auth.artifact_id)).first()
    dest = get_settings().data_dir / "releases" / auth.opportunity_id / f"{auth.artifact_digest[:16]}.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(art.storage_path, dest)
    if bundles.digest(dest) != auth.artifact_digest:
        dest.unlink(missing_ok=True)
        raise ToolFailed("copied bundle does not match the approved digest")
    with transaction() as conn:
        conn.execute(insert(db.release_executions).values(id=db.new_id(), authorization_id=auth.id, artifact_digest=auth.artifact_digest,
                                                          destination=str(dest.relative_to(get_settings().data_dir))))
        emit(conn, "release.executed", mission_id=ctx.mission_id, agent_id=ctx.agent_id, execution_mode=ctx.execution_mode,
             payload={"authorization_id": auth.id, "opportunity_id": auth.opportunity_id, "artifact_digest": auth.artifact_digest,
                      "destination": redact(str(dest.relative_to(get_settings().data_dir))), "channel": "local_release"})
    return {"destination": str(dest.relative_to(get_settings().data_dir)), "digest": auth.artifact_digest, "channel": "local_release"}
