"""Task handlers for the V4 mission kinds: market research, prototype build, QA, release."""
from __future__ import annotations

import json
import time

from sqlalchemy import insert, select

from services.core import db
from services.core.config import get_settings
from services.core.events import emit, transaction
from services.logistics import service as logistics
from services.management.hierarchy import submit_report
from services.research.scoring import COMPONENTS, score_app_category, weights
from services.studio.template import FEATURES

from . import ops
from .handlers import TaskEnv, TaskError, _json_from

MIN_PACKET_SCORE = 0.45
EST_BUILD_COST_USD = 1.5


def _walk(env: TaskEnv, district: str, waypoint: str) -> None:
    with transaction() as conn:
        moving = ops.request_move(conn, env.agent.id, district, waypoint, env.mission.id, env.mission.execution_mode)
    if moving and get_settings().travel_seconds:
        time.sleep(get_settings().travel_seconds)
    with transaction() as conn:
        if moving:
            ops.arrive(conn, env.agent.id, district, waypoint, env.mission.id, env.mission.execution_mode)


def _default_spec(category: str, region: str) -> dict:
    return {"app_name": "Steady Focus", "tagline": "Short focus sessions, a daily goal, and a streak worth keeping.",
            "category": category.title(), "features": list(FEATURES), "keywords": ["focus", "streak", "timer", "habit", "study"],
            "target_user": "students and remote workers", "platform": "iOS (web prototype first)", "region": region,
            "acceptance": ["log a focus session of 5-120 minutes", "show daily goal progress", "count a streak with one freeze"]}


def research(env: TaskEnv) -> dict:
    p = env.mission.params or {}
    source, query, region = p.get("source", "apple_charts"), p.get("query", "productivity"), p.get("region", "US")
    r = env.tool("query_market_source", source=source, query=query, region=region)
    if r["status"] != "completed" or not r["finding_ids"]:
        with transaction() as conn:
            submit_report(conn, org_id=env.ctx.org_id, agent_id=env.agent.id, kind="blocker", mission_id=env.mission.id,
                          body=f"{source} gave no usable data: {r.get('reason') or 'no matching results'}. Nothing to package.")
        return {"opportunity_id": None, "reason": r.get("reason") or "no findings"}
    with db.get_engine().connect() as conn:
        findings = [dict(x._mapping) for x in conn.execute(select(db.research_findings).where(db.research_findings.c.id.in_(r["finding_ids"])))]
    total, comps, confidence, flags = score_app_category(query, findings, EST_BUILD_COST_USD)
    data_mode = "fixture" if any(f["data_mode"] == "fixture" for f in findings) else "live"
    spec = _default_spec(query, region)
    if env.live:
        try:
            got = _json_from(env.ask_model(
                "From these findings, propose a small app. Reply JSON {\"app_name\": \"<=24 chars\", \"tagline\": \"<=80 chars\", "
                f"\"features\": subset of {list(FEATURES)}, \"keywords\": [<=6 words]}}.\n<untrusted>"
                + json.dumps([{k: f[k] for k in ("title", "summary", "measurement_type", "data_mode")} for f in findings]) + "</untrusted>", 300))
            spec.update({k: got[k] for k in ("app_name", "tagline", "keywords") if isinstance(got.get(k), (str, list))})
            feats = [f for f in got.get("features", []) if f in FEATURES]
            if feats:
                spec["features"] = feats
        except TaskError:
            pass  # keep the deterministic spec; the model's suggestion is optional
    if total < MIN_PACKET_SCORE:
        return {"opportunity_id": None, "score": total, "reason": "score below packet threshold"}
    evidence = [{"finding_id": f["id"], "title": f["title"], "source_url": f["source_url"], "collected_at": f["collected_at"],
                 "measurement_type": f["measurement_type"], "data_mode": f["data_mode"], "geographic_scope": f["geographic_scope"],
                 "coverage": f["data_coverage"], "confidence": f["confidence"]} for f in findings]
    oid = db.new_id()
    w = weights()
    brief = (f"# Research brief: {spec['app_name']}\n\n"
             + ("> **Fixture data.** These findings come from labeled test fixtures, not live market research.\n\n" if data_mode == "fixture" else "")
             + f"Score **{total:.2f}** (confidence {confidence}).\n\n## Evidence\n"
             + "".join(f"- {e['title']} — {e['measurement_type'].replace('_', ' ')}, {e['coverage']}, collected {e['collected_at'][:10]}, "
                       f"{e['geographic_scope']} — source: {e['source_url']}\n" for e in evidence)
             + "\nRanks and favorites are popularity proxies; no sales figures were available, so none are stated.\n\n## Components\n"
             + "".join(f"- {k}: {comps[k].score:.2f} × weight {w[k]} — {'; '.join(comps[k].evidence)}\n" for k in COMPONENTS)
             + f"\n## Proposed spec\n```json\n{json.dumps(spec, indent=2)}\n```\n")
    with transaction() as conn:
        aid = db.new_id()
        conn.execute(insert(db.opportunities).values(
            id=oid, organization_id=env.ctx.org_id, source_platform=findings[0]["source_platform"], research_agent_id=env.agent.id,
            research_mission_id=env.mission.id, title=f"{spec['app_name']} — {query} app", description=spec["tagline"],
            evidence=evidence, confidence=confidence, opportunity_score=total, proposed_department="app_studio",
            estimated_effort="~1 hour of agent time (template prototype)", estimated_cost_usd=EST_BUILD_COST_USD, risk_flags=flags,
            artifact_references=[aid], spec=spec, status="RESEARCHED", data_mode=data_mode))
        for k in COMPONENTS:
            conn.execute(insert(db.opportunity_scores).values(opportunity_id=oid, component=k, score=comps[k].score, weight=w[k], evidence=comps[k].evidence))
        conn.execute(insert(db.artifacts).values(id=aid, organization_id=env.ctx.org_id, mission_id=env.mission.id, task_id=env.task.id,
                                                 agent_id=env.agent.id, kind="research_brief", title=f"Research brief — {spec['app_name']}",
                                                 content=brief, opportunity_id=oid))
        emit(conn, "artifact.created", mission_id=env.mission.id, agent_id=env.agent.id, execution_mode=env.mission.execution_mode,
             payload={"artifact_id": aid, "kind": "research_brief", "title": f"Research brief — {spec['app_name']}"})
        emit(conn, "research.opportunity_identified", mission_id=env.mission.id, agent_id=env.agent.id, execution_mode=env.mission.execution_mode,
             payload={"opportunity_id": oid, "title": spec["app_name"], "score": total, "confidence": confidence, "data_mode": data_mode,
                      "carrier_agent_id": env.agent.id})
    _walk(env, "data-observatory", "data-observatory:dispatch")  # carries the holographic package to the dispatch terminal
    with transaction() as conn:
        existing = conn.execute(select(db.logistics_packages.c.id).where(db.logistics_packages.c.opportunity_id == oid,
                                                                         db.logistics_packages.c.package_type == "research_brief")).first()
        pid = existing.id if existing else logistics.create_package(
            conn, org_id=env.ctx.org_id, package_type="research_brief", origin="data-observatory",
            destination="nexus-spire", opportunity_id=oid, mission_id=env.mission.id, task_id=env.task.id,
            artifact_references=[aid], priority=4, carrier_agent_id=env.agent.id)
        emit(conn, "research.completed", mission_id=env.mission.id, agent_id=env.agent.id, execution_mode=env.mission.execution_mode,
             payload={"opportunity_id": oid, "package_id": pid, "score": total})
        submit_report(conn, org_id=env.ctx.org_id, agent_id=env.agent.id, kind="completed_package", mission_id=env.mission.id,
                      body=f"Opportunity '{spec['app_name']}' scored {total:.2f} ({confidence}); brief dispatched to the General Manager.",
                      data={"opportunity_id": oid, "data_mode": data_mode})
    return {"opportunity_id": oid, "score": total, "confidence": confidence, "data_mode": data_mode, "package_id": pid}


def scaffold(env: TaskEnv) -> dict:
    oid = env.mission.opportunity_id
    r = env.tool("scaffold_prototype", opportunity_id=oid)
    meta = json.loads(env.tool("read_file", path="store/metadata.json")["content"])
    return {"files": r["files"], "app_name": meta["name"], "features": meta["features"]}


def bundle(env: TaskEnv) -> dict:
    r = env.tool("build_release_bundle", opportunity_id=env.mission.opportunity_id)
    return {"artifact_id": r["artifact_id"], "digest": r["digest"], "files": r["files"]}


def qa_verify(env: TaskEnv) -> dict:
    artifact_id = (env.mission.params or {}).get("artifact_id")
    staged = env.tool("stage_bundle", artifact_id=artifact_id)
    build = env.tool("run_build")
    tests = env.tool("run_tests")
    report = env.tool("create_artifact", kind="test_report", title=f"QA on bundle {staged['digest'][:10]} — {tests['summary_line']}",
                      content=f"Bundle digest: {staged['digest']}\nBuild exit code: {build['exit_code']}\n\n{tests['output']}")
    out = {"bundle_digest": staged["digest"], "artifact_id": artifact_id, "build_exit_code": build["exit_code"], "passed": tests["passed"],
           "failed": tests["failed"], "errors": tests["errors"], "summary_line": tests["summary_line"], "report_artifact_id": report["artifact_id"],
           "network_isolated": tests["network_isolated"]}
    env.say(f"Tested bundle {staged['digest'][:10]}: {tests['summary_line']}.", to_key="general_manager", kind="handoff")
    return out


def release(env: TaskEnv) -> dict:
    r = env.tool("submit_release", authorization_id=(env.mission.params or {}).get("authorization_id", ""))
    env.say(f"Released bundle {r['digest'][:10]} to the local release channel.", to_key="general_manager", kind="status")
    return r


V4_HANDLERS = {"research": research, "scaffold": scaffold, "bundle": bundle, "qa_verify": qa_verify, "release": release}
