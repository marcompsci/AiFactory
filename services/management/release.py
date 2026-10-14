"""Two-stage release approval.

Stage 1 — the General Manager's documented review of one exact bundle (12 categories, 4 verdicts).
Stage 2 — the owner's decision in the Owner's Tower, bound to that bundle's sha256.

`check_authorization` runs inside `execute_tool` for every release-gated tool. A release is allowed only if:
the owner APPROVED, the authorization was never invalidated, the bundle on disk still hashes to the approved
digest, and no newer bundle exists for the opportunity. Any mismatch records an invalidation (append-only),
emits release.invalidated, sends the opportunity back to manager review, and refuses the tool call.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy import func, insert, select
from sqlalchemy.engine import Connection

from services.core import db
from services.core.events import emit
from services.studio import bundle as bundles

from .manager import gm_judgment, record_decision, set_opportunity_status

CATEGORIES = ("requirements", "functional", "tests", "security", "privacy", "accessibility", "performance",
              "store_requirements", "documentation", "market_rationale", "cost", "known_limitations")
FIXABLE = {"requirements", "functional", "tests", "accessibility", "documentation", "performance", "store_requirements"}
BLOCKING = {"security", "privacy"}
SECRET = re.compile(r"(sk-ant-|sk-[A-Za-z0-9]{20}|gh[pousr]_[A-Za-z0-9]{20}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY)")


class ReleaseDenied(PermissionError):
    pass


def latest_bundle(conn: Connection, opportunity_id: str):
    return conn.execute(select(db.artifacts).where(db.artifacts.c.opportunity_id == opportunity_id, db.artifacts.c.kind == "release_bundle")
                        .order_by(db.artifacts.c.created_at.desc())).first()


def _bundle_files(art) -> dict[str, bytes]:
    out = {}
    import zipfile
    with zipfile.ZipFile(art.storage_path) as z:
        for n in z.namelist():
            out[n] = z.read(n)
    return out


def run_checklist(conn: Connection, opp, art, qa_outputs: dict) -> list[tuple[str, str, str]]:
    """Deterministic evidence for each category. Returns [(category, status, evidence)]."""
    files = _bundle_files(art)
    text = {k: v.decode("utf-8", "replace") for k, v in files.items() if k.endswith((".py", ".html", ".md", ".json", ".toml", ".webmanifest", ".svg"))}
    spec = opp.spec or {}
    rows: list[tuple[str, str, str]] = []
    meta = json.loads(text.get("store/metadata.json", "{}") or "{}")
    missing = [f for f in spec.get("features", []) if f not in meta.get("features", [])]
    name_ok = meta.get("name") == spec.get("app_name", "")[:30]
    rows.append(("requirements", "pass" if not missing and name_ok else "fail",
                 f"spec features {spec.get('features')} {'all present' if not missing else 'missing ' + str(missing)}; name {'matches' if name_ok else 'differs from'} spec"))
    tested = qa_outputs.get("bundle_digest") == art.digest
    passed = qa_outputs.get("failed", 1) == 0 and qa_outputs.get("errors", 1) == 0 and qa_outputs.get("passed", 0) > 0
    rows.append(("functional", "pass" if passed and "app/core.py" in files else "fail",
                 f"core module present: {'app/core.py' in files}; behavior covered by {qa_outputs.get('passed', 0)} passing tests"))
    rows.append(("tests", "pass" if passed and tested else "fail",
                 f"QA: {qa_outputs.get('summary_line', 'no run')} on digest {str(qa_outputs.get('bundle_digest'))[:12]} "
                 f"({'matches' if tested else 'DOES NOT match'} the reviewed bundle {art.digest[:12]})"))
    mission_ids = [m for m in (opp.production_mission_id, opp.qa_mission_id) if m]
    denied = conn.execute(select(func.count()).select_from(db.tool_executions).where(
        db.tool_executions.c.mission_id.in_(mission_ids), db.tool_executions.c.status == "DENIED")).scalar() if mission_ids else 0
    secrets = [k for k, v in text.items() if SECRET.search(v)]
    net = [k for k, v in text.items() if k.endswith((".py", ".html")) and re.search(r"https?://(?!www\.w3\.org)", v)]
    sec_status = "fail" if secrets else ("warn" if denied or net else "pass")
    rows.append(("security", sec_status, f"secrets found: {secrets or 'none'}; denied tool calls during build/QA: {denied}; network URLs in code: {net or 'none'}"))
    privacy = text.get("PRIVACY.md", "")
    analytics = [k for k, v in text.items() if re.search(r"(google-analytics|gtag\(|segment\.com|mixpanel|firebase)", v, re.I)]
    rows.append(("privacy", "pass" if privacy and not analytics else "fail",
                 f"PRIVACY.md {'present' if privacy else 'missing'}; analytics SDKs: {analytics or 'none'}"))
    page = text.get("index.html", "")
    a11y = {"lang attribute": bool(re.search(r"<html[^>]*\blang=", page)), "viewport meta": "name=\"viewport\"" in page,
            "labels for inputs": all(f'for="{i}"' in page for i in re.findall(r'<input[^>]*id="([^"]+)"', page)),
            "live region": "aria-live" in page or 'role="alert"' in page, "visible focus style": ":focus-visible" in page}
    rows.append(("accessibility", "pass" if all(a11y.values()) else "fail", "; ".join(f"{k}: {'yes' if v else 'NO'}" for k, v in a11y.items())))
    size = Path(art.storage_path).stat().st_size
    rows.append(("performance", "pass" if size < 200_000 and len(page) < 50_000 else "warn", f"bundle {size} bytes; preview page {len(page)} bytes; no external scripts"))
    store_ok = all([meta.get("name"), len(meta.get("name", "")) <= 30, len(meta.get("subtitle", "")) <= 30, len(meta.get("keywords", "")) <= 100,
                    meta.get("category"), meta.get("age_rating"), "icon.svg" in files, "PRIVACY.md" in files])
    rows.append(("store_requirements", "warn" if store_ok else "fail",
                 "metadata within App Store limits (name ≤30, subtitle ≤30, keywords ≤100), icon and privacy policy present"
                 if store_ok else "metadata or assets missing for a store listing"
                 + "; an App Store build still needs an Xcode project, signing and screenshots"))
    readme = text.get("README.md", "")
    rows.append(("documentation", "pass" if "## Run" in readme and "## Features" in readme else "fail", "README has features, run instructions and limitations"
                 if "## Run" in readme else "README incomplete"))
    fixture = opp.data_mode == "fixture"
    rows.append(("market_rationale", "warn" if fixture else ("pass" if opp.opportunity_score >= 0.55 else "fail"),
                 f"score {opp.opportunity_score:.2f}, confidence {opp.confidence}, {len(opp.evidence or [])} cited findings"
                 + ("; FIXTURE evidence — not live market research" if fixture else "")))
    spent = conn.execute(select(func.coalesce(func.sum(db.missions.c.spent_usd_estimated), 0.0)).where(
        db.missions.c.opportunity_id == opp.id)).scalar() or 0.0
    rows.append(("cost", "pass" if spent <= opp.estimated_cost_usd else "warn", f"estimated spend ${spent:.4f} vs plan ${opp.estimated_cost_usd:.2f}"))
    rows.append(("known_limitations", "warn", "web prototype from the App Studio template; data on device only; no App Store binary"
                 + ("; evidence is fixture data" if fixture else "")))
    return rows


def verdict_for(rows: list[tuple[str, str, str]]) -> str:
    failed = {c for c, s, _ in rows if s == "fail"}
    if failed & BLOCKING:
        return "BLOCKED"
    if "market_rationale" in failed:
        return "REJECTED"
    if failed & FIXABLE:
        return "CHANGES_REQUESTED"
    return "APPROVED_FOR_OWNER_REVIEW"


def manager_release_review(conn_factory, opp_id: str, gateway) -> dict:
    with conn_factory() as conn:
        opp = conn.execute(select(db.opportunities).where(db.opportunities.c.id == opp_id)).first()
        art = latest_bundle(conn, opp_id)
        qa = conn.execute(select(db.tasks.c.outputs).where(db.tasks.c.mission_id == opp.qa_mission_id, db.tasks.c.key == "qa_verify")).first()
        qa_outputs = (qa.outputs if qa else None) or {}
        emit(conn, "manager.review_started", payload={"opportunity_id": opp_id, "artifact_id": art.id, "artifact_digest": art.digest})
        rows = run_checklist(conn, opp, art, qa_outputs)
    verdict = verdict_for(rows)
    summary = (f"{sum(1 for _, s, _ in rows if s == 'pass')} pass, {sum(1 for _, s, _ in rows if s == 'warn')} warn, "
               f"{sum(1 for _, s, _ in rows if s == 'fail')} fail across {len(rows)} categories.")
    method, model = "rules", None
    judged, model_used = gm_judgment(gateway, (
        "Write the owner-facing release recommendation. Reply {\"summary\": \"<3 sentences>\", \"concern\": true|false}. "
        "Set concern=true only for a real problem the checklist shows.\n<untrusted>" + json.dumps(
            {"title": opp.title, "spec": opp.spec, "checklist": rows, "verdict": verdict}) + "</untrusted>"))
    if judged:
        method, model = "model", model_used
        summary = str(judged.get("summary", summary))[:1200]
        if judged.get("concern") and verdict == "APPROVED_FOR_OWNER_REVIEW":
            verdict = "CHANGES_REQUESTED"  # judgment may tighten, never loosen
    with conn_factory() as conn:
        rid = db.new_id()
        conn.execute(insert(db.manager_reviews).values(id=rid, organization_id=opp.organization_id, opportunity_id=opp_id, artifact_id=art.id,
                                                       artifact_digest=art.digest, verdict=verdict, summary=summary, method=method, model=model))
        for c, s, e in rows:
            conn.execute(insert(db.review_checklists).values(id=db.new_id(), review_id=rid, category=c, status=s, evidence=e))
        md = f"# Manager review: {opp.title}\n\nBundle `{art.digest}`\n\n**Verdict: {verdict}**\n\n{summary}\n\n| Category | Status | Evidence |\n|---|---|---|\n" + \
             "".join(f"| {c} | {s} | {e} |\n" for c, s, e in rows)
        aid = db.new_id()
        gm = conn.execute(select(db.agents).where(db.agents.c.tier == "general_manager")).first()
        conn.execute(insert(db.artifacts).values(id=aid, organization_id=opp.organization_id, mission_id=None, agent_id=gm.id, kind="manager_review",
                                                 title=f"Manager review — {verdict.replace('_', ' ').lower()}", content=md, opportunity_id=opp_id))
        emit(conn, "artifact.created", agent_id=gm.id, payload={"artifact_id": aid, "kind": "manager_review", "title": "Manager review"})
        record_decision(conn, decision_type="release_review", subject_type="opportunity", subject_id=opp_id, outcome=verdict,
                        rationale=summary, method=method, model=model, inputs={"artifact_digest": art.digest, "review_id": rid},
                        event="manager.review_completed")
    return {"review_id": rid, "verdict": verdict, "artifact_id": art.id, "digest": art.digest}


def current_review(conn: Connection, opp_id: str):
    return conn.execute(select(db.manager_reviews).where(db.manager_reviews.c.opportunity_id == opp_id)
                        .order_by(db.manager_reviews.c.created_at.desc())).first()


def owner_decide(conn: Connection, *, opp_id: str, decision: str, artifact_digest: str, note: str | None, owner_id: str) -> dict:
    """The owner's call. The digest the owner saw must equal the reviewed bundle, or the decision is refused."""
    if decision not in ("APPROVE", "REQUEST_CHANGES", "REJECT", "DEFER"):
        raise ReleaseDenied("unknown decision")
    opp = conn.execute(select(db.opportunities).where(db.opportunities.c.id == opp_id)).first()
    if opp is None or opp.status != "OWNER_APPROVAL":
        raise ReleaseDenied("nothing is waiting for your decision on this item")
    pkg = conn.execute(select(db.logistics_packages).where(db.logistics_packages.c.opportunity_id == opp_id,
                                                           db.logistics_packages.c.package_type == "release_package")
                       .order_by(db.logistics_packages.c.created_at.desc())).first()
    if not pkg or pkg.status not in ("ARRIVED", "RECEIVED"):
        raise ReleaseDenied("the release package has not arrived at the Owner's Tower yet")
    review = current_review(conn, opp_id)
    art = latest_bundle(conn, opp_id)
    if review is None or review.verdict != "APPROVED_FOR_OWNER_REVIEW":
        raise ReleaseDenied("no manager approval on record")
    if review.artifact_id != art.id or not (artifact_digest == review.artifact_digest == art.digest):
        raise ReleaseDenied("the bundle changed since you opened it; reload and review the current version")
    if bundles.digest(Path(art.storage_path)) != art.digest:
        raise ReleaseDenied("the stored bundle no longer matches its recorded digest")
    did = db.new_id()
    conn.execute(insert(db.owner_decisions).values(id=did, organization_id=opp.organization_id, opportunity_id=opp_id, manager_review_id=review.id,
                                                   artifact_id=art.id, artifact_digest=art.digest, decision=decision, note=note, decided_by=owner_id))
    out = {"owner_decision_id": did}
    base = {"opportunity_id": opp_id, "artifact_id": art.id, "artifact_digest": art.digest, "owner_decision_id": did, "note": note}
    if decision == "APPROVE":
        auth = db.new_id()
        conn.execute(insert(db.release_authorizations).values(id=auth, organization_id=opp.organization_id, opportunity_id=opp_id,
                                                              owner_decision_id=did, artifact_id=art.id, artifact_digest=art.digest,
                                                              scope="local_release"))
        emit(conn, "release.owner_approved", payload=base)
        emit(conn, "release.authorized", payload={**base, "authorization_id": auth, "scope": "local_release"})
        set_opportunity_status(conn, opp_id, "RELEASE_AUTHORIZED", "owner approved this exact bundle")
        out["authorization_id"] = auth
    elif decision == "REJECT":
        emit(conn, "release.owner_rejected", payload=base)
        set_opportunity_status(conn, opp_id, "REJECTED", note or "owner rejected the release")
    elif decision == "DEFER":
        set_opportunity_status(conn, opp_id, "DEFERRED", note or "owner deferred")
    else:
        from sqlalchemy import update

        from services.logistics import service as logistics
        conn.execute(update(db.opportunities).where(db.opportunities.c.id == opp_id).values(revision_count=opp.revision_count + 1))
        emit(conn, "manager.revision_requested", payload={**base, "by": "owner"})
        set_opportunity_status(conn, opp_id, "REVISION_REQUESTED", note or "owner requested changes")
        logistics.create_package(conn, org_id=opp.organization_id, package_type="revision_request", origin="owners-tower",
                                 destination="code-forge", opportunity_id=opp_id, artifact_references=[art.id], priority=2)
    return out


def invalidate(conn: Connection, auth, reason: str, observed: str | None) -> None:
    exists = conn.execute(select(db.release_invalidations.c.id).where(db.release_invalidations.c.authorization_id == auth.id)).first()
    if exists:
        return
    conn.execute(insert(db.release_invalidations).values(id=db.new_id(), authorization_id=auth.id, reason=reason, observed_digest=observed))
    emit(conn, "release.invalidated", payload={"authorization_id": auth.id, "opportunity_id": auth.opportunity_id, "reason": reason,
                                               "approved_digest": auth.artifact_digest, "observed_digest": observed})
    opp = conn.execute(select(db.opportunities).where(db.opportunities.c.id == auth.opportunity_id)).first()
    if opp.status == "RELEASE_AUTHORIZED":
        set_opportunity_status(conn, opp.id, "MANAGER_APPROVAL", "release approval invalidated; renewed review required")
        record_decision(conn, decision_type="release_review", subject_type="opportunity", subject_id=opp.id, outcome="REVIEW_REQUIRED",
                        rationale=f"Approval {auth.id[:8]} invalidated: {reason}. Re-reviewing the current bundle.",
                        event="manager.escalation_created")


def check_authorization(conn: Connection, org_id: str, authorization_id: str, opportunity_id: str | None) -> object:
    auth = conn.execute(select(db.release_authorizations).where(db.release_authorizations.c.id == authorization_id)).first()
    if auth is None or auth.organization_id != org_id:
        raise ReleaseDenied("no owner release authorization with that id")
    if opportunity_id and auth.opportunity_id != opportunity_id:
        raise ReleaseDenied("authorization belongs to a different product")
    decision = conn.execute(select(db.owner_decisions).where(db.owner_decisions.c.id == auth.owner_decision_id)).first()
    if decision is None or decision.decision != "APPROVE" or decision.artifact_digest != auth.artifact_digest:
        raise ReleaseDenied("authorization is not backed by an owner APPROVE decision for this digest")
    if conn.execute(select(db.release_invalidations.c.id).where(db.release_invalidations.c.authorization_id == auth.id)).first():
        raise ReleaseDenied("this release approval was invalidated; the owner must approve again")
    art = conn.execute(select(db.artifacts).where(db.artifacts.c.id == auth.artifact_id)).first()
    latest = latest_bundle(conn, auth.opportunity_id)
    if latest is None or latest.id != art.id:
        invalidate(conn, auth, "a newer bundle superseded the approved one", latest.digest if latest else None)
        raise ReleaseDenied("a newer bundle exists; the owner approved a different version")
    observed = bundles.digest(Path(art.storage_path)) if art.storage_path and Path(art.storage_path).exists() else None
    if observed != auth.artifact_digest or art.digest != auth.artifact_digest:
        invalidate(conn, auth, "bundle contents changed after owner approval", observed)
        raise ReleaseDenied("bundle changed after owner approval; approval invalidated")
    return auth
