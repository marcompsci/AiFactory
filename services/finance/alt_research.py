"""Research, scoring, sandboxed evaluation and reviews for free-alternative investigations (V5.1).

Sources: today only the bundled FIXTURE catalog (`fixtures/alternatives/catalog.json`). Every candidate and every
claim carries a source URL, an as-of marker and `data_mode = fixture`. Real research providers are added only
after their permissions and access are validated.

Sandbox: the strongest candidate is checked against the owner's requirements (real pytest, real results) inside
a disposable workspace run by the same sandbox the agents' tools use (no network where the host allows, scrubbed
environment, CPU/memory limits; the Docker sandbox in production). What runs is a FIXTURE compatibility kit that
models the candidate's documented behavior. Downloaded software is never executed.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.engine import Connection

from services.core import db
from services.core.config import get_settings

ROOT = Path(__file__).parent / "fixtures" / "alternatives"
MAX_CANDIDATES = 5
WEIGHTS = {"compatibility": 0.30, "security": 0.20, "functionality": 0.20, "migration": 0.15, "total_cost": 0.15}
CLAIM_VALUE = {"yes": 1.0, "partial": 0.5, "no": 0.0}


@lru_cache
def catalog() -> dict:
    return json.loads((ROOT / "catalog.json").read_text())


def category_for(vendor: str, item: str) -> str | None:
    text = f"{vendor} {item}".lower()
    return next((cat for key, cat in catalog()["vendor_category"].items() if key in text), None)


def requirements(category: str) -> list[tuple[str, str]]:
    return [tuple(r) for r in catalog()["requirements"].get(category, [])]


# ------------------------------------------------------------------ 5-6: gather candidates with attributed evidence
def gather(conn: Connection, inv) -> int:
    if not inv.category or inv.category not in catalog()["categories"]:
        return 0
    have = {r.slug for r in conn.execute(select(db.alternative_candidates.c.slug).where(db.alternative_candidates.c.investigation_id == inv.id))}
    n = 0
    for c in catalog()["categories"][inv.category]["candidates"][:MAX_CANDIDATES]:
        if c["slug"] in have:
            continue
        cid = db.new_id()
        src = f"fixture://alternatives/{inv.category}/{c['slug']}"
        conn.execute(db.alternative_candidates.insert().values(
            id=cid, organization_id=inv.organization_id, investigation_id=inv.id, slug=c["slug"], name=c["name"], vendor=c["vendor"],
            product_url=c["product_url"], docs_url=c["docs_url"], source_url=src, license=c["license"], license_url=c["license_url"],
            open_source=int(c["open_source"]), pricing=c["pricing"], features=c["features"], claims=c["claims"],
            limitations=c["restrictions"] + ([f"maintenance: {c['maintenance']['activity']}"] if c["maintenance"]["activity"] != "active" else []),
            maintenance=c["maintenance"], estimated_costs={}, evidence_as_of=catalog()["as_of"], confidence="low", data_mode="fixture"))
        claims = [
            ("pricing", f"{c['pricing']['model']}: {c['pricing']['price_minor'] / 100:.2f} per {c['pricing']['interval']}; "
                        f"free tier: {c['pricing']['free_tier_limits']}", src + "#pricing"),
            ("license", f"{c['license']}", c["license_url"] or src),
            ("features", "; ".join(c["features"]), c["docs_url"] or src),
            ("maintenance", f"{c['maintenance']['activity']}: {c['maintenance']['signal']}", src + "#maintenance"),
            ("documentation", f"documentation at {c['docs_url']}", c["docs_url"] or src),
        ] + [("restriction", r, src + "#restrictions") for r in c["restrictions"]]
        for kind, claim, url in claims:
            conn.execute(db.alternative_evidence.insert().values(id=db.new_id(), organization_id=inv.organization_id, candidate_id=cid, kind=kind,
                                                                 claim=claim[:500], source_url=url, as_of=catalog()["as_of"], data_mode="fixture"))
        n += 1
    return n


# ------------------------------------------------------------------ 7-8: score and shortlist
def _yearly(minor: int, interval: str) -> int:
    return minor * 12 if interval == "month" else minor


def score(conn: Connection, inv, packet, assessed_by: str | None) -> list[dict]:
    reqs = [r for r, _ in requirements(inv.category)]
    original_year = _yearly(packet.amount_minor, packet.interval if packet.interval != "one_time" else "year")
    original_3y = original_year * 3
    conn.execute(db.cost_comparisons.delete().where(db.cost_comparisons.c.investigation_id == inv.id))
    conn.execute(db.cost_comparisons.insert().values(
        id=db.new_id(), organization_id=inv.organization_id, investigation_id=inv.id, candidate_id=None, label=f"{packet.vendor} (requested)",
        first_year_minor=original_year, three_year_minor=original_3y, migration_minor=0, notes="terms from the cost review itself",
        data_mode=packet.data_mode))
    cands = conn.execute(select(db.alternative_candidates).where(db.alternative_candidates.c.investigation_id == inv.id)).fetchall()
    rows = []
    for c in cands:
        cat_entry = next(x for x in catalog()["categories"][inv.category]["candidates"] if x["slug"] == c.slug)
        claims = c.claims or {}
        functionality = sum(CLAIM_VALUE.get(claims.get(r, "no"), 0) for r in reqs) / max(1, len(reqs))
        # compatibility weighs the requirements the current workflow depends on: file import and shared libraries
        critical = [r for r in reqs if r in ("figma_import", "shared_libraries", "sentry_sdk_events")] or reqs
        compatibility = sum(CLAIM_VALUE.get(claims.get(r, "no"), 0) for r in critical) / len(critical)
        security = 0.4 + (0.2 if c.open_source else 0) + (0.2 if cat_entry.get("self_host") else 0) \
            + (0.2 if (c.maintenance or {}).get("activity") == "active" else -0.2)
        security = max(0.0, min(1.0, security))
        migration_minor = int(cat_entry.get("migration_minor", 0))
        year = _yearly(int(c.pricing.get("price_minor", 0)), c.pricing.get("interval", "month"))
        three = year * 3 + migration_minor
        migration = max(0.0, min(1.0, 1 - migration_minor / max(1, original_3y + migration_minor)))
        total_cost = max(0.0, min(1.0, 1 - three / max(1, original_3y)))
        parts = {"compatibility": compatibility, "security": security, "functionality": functionality, "migration": migration,
                 "total_cost": total_cost}
        total = round(sum(parts[k] * w for k, w in WEIGHTS.items()), 4)
        conn.execute(db.compatibility_assessments.insert().values(
            id=db.new_id(), organization_id=inv.organization_id, candidate_id=c.id, **{k: round(v, 4) for k, v in parts.items()},
            total_score=total, assessed_by=assessed_by,
            rationale={"claims": claims, "weights": WEIGHTS, "requirements": reqs, "critical": critical,
                       "note": "scored from FIXTURE documentation claims; the sandbox checks the strongest one"}))
        conn.execute(db.cost_comparisons.insert().values(
            id=db.new_id(), organization_id=inv.organization_id, investigation_id=inv.id, candidate_id=c.id, label=c.name,
            first_year_minor=year + migration_minor, three_year_minor=three, migration_minor=migration_minor,
            notes=f"migration estimate is a fixture placeholder; paid tier {c.pricing.get('paid_tier_minor', 0) / 100:.2f}/mo if needed",
            data_mode="fixture"))
        conn.execute(update(db.alternative_candidates).where(db.alternative_candidates.c.id == c.id).values(
            estimated_costs={"first_year_minor": year + migration_minor, "three_year_minor": three, "migration_minor": migration_minor,
                             "original_three_year_minor": original_3y}))
        rows.append({"id": c.id, "name": c.name, "total": total})
    rows.sort(key=lambda r: (-r["total"], r["name"]))
    for i, r in enumerate(rows, start=1):
        conn.execute(update(db.alternative_candidates).where(db.alternative_candidates.c.id == r["id"]).values(rank=i, shortlisted=int(i <= 3)))
    if rows:
        conn.execute(update(db.savings_investigations).where(db.savings_investigations.c.id == inv.id).values(top_candidate_id=rows[0]["id"]))
    return rows[:3]


# ------------------------------------------------------------------ 9: sandboxed evaluation
_RESULT = re.compile(r"^(PASSED|FAILED|ERROR) \S+::(test_\w+)(?: - (.*))?$", re.M)
_SUMMARY = re.compile(r"(\d+) (passed|failed|error|errors)")


def kit_files(slug: str, category: str) -> dict[str, Path]:
    kits = (ROOT / "kits").resolve()
    files = {"kitbase.py": kits / "kitbase.py", "kit.py": kits / f"{slug}.py",
             "test_requirements.py": (ROOT / "requirements" / f"{category}.py").resolve()}
    for name, path in files.items():
        p = path.resolve()
        if not (p.is_file() and (kits in p.parents or (ROOT / "requirements").resolve() in p.parents)):
            raise PermissionError(f"{name}: only bundled compatibility kits may run in the sandbox")
    return files


def run_sandbox(conn_factory, inv, candidate, mission_id: str | None) -> dict:
    """Copies the kit and the requirement tests into a fresh workspace, runs pytest in the sandbox, records exactly
    what happened, and deletes the workspace."""
    from services.tools.sandbox import default_sandbox

    if candidate.data_mode != "fixture":
        raise PermissionError("executing downloaded software is not enabled; only bundled compatibility kits run")
    eval_id = db.new_id()
    sb = default_sandbox()
    argv = ["python", "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider", "test_requirements.py"]
    with conn_factory() as conn:
        conn.execute(db.sandbox_evaluations.insert().values(
            id=eval_id, organization_id=inv.organization_id, investigation_id=inv.id, candidate_id=candidate.id, status="RUNNING",
            sandbox=sb.name, subject=f"FIXTURE compatibility kit for {candidate.name} (not the vendor's software)", command=argv))
    base = get_settings().data_dir / "sandboxes"
    base.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"eval-{eval_id[:8]}-", dir=base))
    status, results, out, code, isolated, dur, kit_sha, err_note = "ERROR", [], "", None, False, 0, None, None
    try:
        files = kit_files(candidate.slug, inv.category)
        h = hashlib.sha256()
        for name, src in sorted(files.items()):
            data = src.read_bytes()
            h.update(name.encode() + b"\0" + data)
            (work / name).write_bytes(data)
        kit_sha = h.hexdigest()
        r = sb.run(argv, work, 60, work)
        out, code, isolated, dur = r.output[-8000:], r.exit_code, r.network_isolated, r.duration_ms
        names = {n: d for n, d in requirements(inv.category)}
        for m in _RESULT.finditer(r.stdout):
            outcome, test, why = m.group(1), m.group(2), (m.group(3) or "").strip()
            req = test.removeprefix("test_")
            results.append({"requirement": req, "description": names.get(req, req), "outcome": outcome.lower(), "detail": why[:300]})
        counts = {k: 0 for k in ("passed", "failed", "error")}
        for n, k in _SUMMARY.findall(r.stdout):
            counts["error" if k.startswith("error") else k] += int(n)
        if r.timed_out:
            status, err_note = "ERROR", "the sandbox run timed out"
        elif code == 0 and counts["passed"] and not counts["failed"]:
            status = "PASSED"
        elif code == 1 and (counts["failed"] or counts["error"]):
            status = "FAILED"
        else:
            status, err_note = "ERROR", f"pytest exit code {code}: the requirements could not be evaluated"
    except PermissionError as exc:
        status, err_note = "ERROR", str(exc)
    finally:
        shutil.rmtree(work, ignore_errors=True)  # disposable
    passed = sum(1 for x in results if x["outcome"] == "passed")
    failed = sum(1 for x in results if x["outcome"] == "failed")
    errors = sum(1 for x in results if x["outcome"] == "error")
    report = (f"# Sandbox evaluation: {candidate.name}\n\nSubject: FIXTURE compatibility kit (not the vendor's software)\n"
              f"Sandbox: {sb.name} · network isolated: {isolated} · kit sha256 {kit_sha}\nStatus: **{status}** ({passed} passed, {failed} failed, "
              f"{errors} errors){' · ' + err_note if err_note else ''}\n\n"
              + "".join(f"- {x['outcome'].upper()} {x['description']}{': ' + x['detail'] if x['detail'] else ''}\n" for x in results)
              + f"\n```\n{out[-4000:]}\n```\n")
    with conn_factory() as conn:
        art = db.new_id()
        conn.execute(db.artifacts.insert().values(id=art, organization_id=inv.organization_id, mission_id=mission_id, task_id=None,
                                                  agent_id=None, kind="test_report", title=f"Sandbox evaluation: {candidate.name}", content=report))
        conn.execute(update(db.sandbox_evaluations).where(db.sandbox_evaluations.c.id == eval_id).values(
            status=status, network_isolated=int(isolated), exit_code=code, passed=passed, failed=failed, errors=errors, results=results,
            output_excerpt=((err_note + "\n") if err_note else "") + out[-4000:], kit_sha256=kit_sha, duration_ms=dur, artifact_id=art,
            finished_at=db.utcnow()))
    return {"evaluation_id": eval_id, "status": status, "passed": passed, "failed": failed, "errors": errors}


# ------------------------------------------------------------------ 10: QA review of the evidence
def qa_review(conn: Connection, inv, reviewer_id: str) -> dict:
    ev = conn.execute(select(db.sandbox_evaluations).where(db.sandbox_evaluations.c.investigation_id == inv.id)
                      .order_by(db.sandbox_evaluations.c.started_at.desc())).first()
    findings = []
    if ev is None:
        verdict, summary = "no_evidence", "No sandbox evaluation was recorded."
    elif ev.status == "ERROR":
        verdict, summary = "evaluation_error", "The evaluation did not run to completion; no conclusion about the candidate."
        findings.append((ev.output_excerpt or "")[:300])
    else:
        failed = [r for r in ev.results or [] if r["outcome"] != "passed"]
        if not ev.kit_sha256 or (ev.passed + ev.failed + ev.errors) != len(ev.results or []):
            verdict, summary = "inconsistent_evidence", "Recorded counts don't match the per-requirement results."
        elif failed:
            verdict = "gaps_found"
            summary = f"{ev.passed} of {len(ev.results)} requirements met; gaps: " + ", ".join(r["description"] for r in failed)
            findings += [f"{r['description']}: {r['detail'] or r['outcome']}" for r in failed]
        else:
            verdict, summary = "meets_requirements", f"All {ev.passed} requirements met in the sandbox."
        if not ev.network_isolated:
            findings.append("network isolation was not available on this host for the run")
        findings.append("evaluated a FIXTURE compatibility kit; confirm with the real product before switching")
    conn.execute(db.investigation_reviews.insert().values(id=db.new_id(), organization_id=inv.organization_id, investigation_id=inv.id,
                                                          stage="qa", reviewer_agent_id=reviewer_id, verdict=verdict, summary=summary,
                                                          findings=findings, method="rules"))
    return {"verdict": verdict, "summary": summary}


# ------------------------------------------------------------------ 11-12: manager recommendation (never an authorization)
def manager_recommendation(conn: Connection, inv) -> dict:
    from . import packets as P

    p = P.get(conn, inv.packet_id)
    top = conn.execute(select(db.alternative_candidates).where(db.alternative_candidates.c.id == inv.top_candidate_id)).first() \
        if inv.top_candidate_id else None
    ev = conn.execute(select(db.sandbox_evaluations).where(db.sandbox_evaluations.c.investigation_id == inv.id)
                      .order_by(db.sandbox_evaluations.c.started_at.desc())).first()
    qa = conn.execute(select(db.investigation_reviews).where(db.investigation_reviews.c.investigation_id == inv.id,
                                                             db.investigation_reviews.c.stage == "qa")
                      .order_by(db.investigation_reviews.c.created_at.desc())).first()
    costs = {c.candidate_id: c for c in conn.execute(select(db.cost_comparisons).where(db.cost_comparisons.c.investigation_id == inv.id))}
    original = costs.get(None)
    top_cost = costs.get(top.id) if top else None
    saving = (original.three_year_minor - top_cost.three_year_minor) if (original and top_cost) else 0
    if top is None or ev is None:
        verdict, headline = "keep_request", "No candidate could be evaluated; the original request is the only tested option."
    elif ev.status == "PASSED" and saving > 0:
        verdict, headline = "consider_alternative", (f"{top.name} met every requirement in the sandbox and would save about "
                                                     f"${saving / 100:,.0f} over three years (fixture pricing).")
    elif ev.status == "FAILED":
        verdict, headline = "keep_request_or_accept_gaps", (f"{top.name} met {ev.passed} of {ev.passed + ev.failed + ev.errors} requirements. "
                                                            f"Buying {p.vendor} keeps them all; switching would save about ${max(saving, 0) / 100:,.0f} "
                                                            "over three years but accept the gaps QA listed.")
    else:
        verdict, headline = "inconclusive", f"The sandbox evaluation of {top.name} did not complete; there is no tested alternative yet."
    return {
        "verdict": verdict, "headline": headline, "authorizes_transaction": False,
        "options": [{"label": f"Buy {p.vendor} as requested", "three_year_minor": original.three_year_minor if original else None,
                     "how": "approve the original request at the Owner's Tower (step-up required)"},
                    *([{"label": f"Switch to {top.name}", "three_year_minor": top_cost.three_year_minor if top_cost else None,
                        "how": "not authorized by this investigation: adopting it needs its own owner approval and is done by you"}] if top else [])],
        "sandbox": None if ev is None else {"status": ev.status, "passed": ev.passed, "failed": ev.failed, "errors": ev.errors,
                                            "results": ev.results, "network_isolated": bool(ev.network_isolated), "subject": ev.subject},
        "qa": None if qa is None else {"verdict": qa.verdict, "summary": qa.summary, "findings": qa.findings},
        "findings": (qa.findings if qa else []),
        "data_mode": "fixture",
    }
