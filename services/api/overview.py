"""One call for the dashboard frame (top stats bar and bottom panels). Every number comes from the database;
money only for owners and admins, and labeled simulated when it is."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select

from services.core import db
from services.core.auth import Principal, authenticate
from services.finance.permissions import FINANCE_READ_ROLES

router = APIRouter(prefix="/api")

# research → manager → production → QA → bank → owner, as in the city's conveyor
STAGES = [("research", "Research", ("data-observatory",)), ("manager", "Manager", ("nexus-spire",)),
          ("production", "Build", ("code-forge", "vision-quarter")), ("qa", "QA", ("sentinel-citadel",)),
          ("bank", "Bank", ("central-bank",)), ("owner", "Owner", ("owners-tower",))]
OPP_FLOW = ["RESEARCHED", "MANAGER_REVIEW", "ROUTED", "DEPARTMENT_ACCEPTED", "IN_PRODUCTION", "QUALITY_REVIEW", "MANAGER_APPROVAL",
            "OWNER_APPROVAL", "RELEASE_AUTHORIZED"]
LAB_FLOW = ["RESEARCHING", "ANALYZING", "MANAGER_REVIEW", "AWAITING_OWNER", "DONE"]
INV_FLOW = ["REQUESTED", "RESEARCHING", "EVALUATING", "TESTING", "MANAGER_REVIEW", "AWAITING_OWNER"]


def member(request: Request) -> Principal:
    return authenticate(request)


@router.get("/overview")
def overview(p: Principal = Depends(member)):
    org = p.organization_id
    today = datetime.now(timezone.utc).date().isoformat()
    with db.get_engine().connect() as conn:
        agents_total = conn.execute(select(func.count()).select_from(db.agents).where(db.agents.c.organization_id == org)).scalar()
        running = conn.execute(select(db.tasks.c.agent_id).where(db.tasks.c.organization_id == org, db.tasks.c.status == "RUNNING")).fetchall()
        done_today = conn.execute(select(func.count()).select_from(db.tasks).where(
            db.tasks.c.organization_id == org, db.tasks.c.status == "COMPLETED", db.tasks.c.updated_at >= today)).scalar()
        queued = conn.execute(select(func.count()).select_from(db.tasks).where(
            db.tasks.c.organization_id == org, db.tasks.c.status.in_(("PENDING", "READY", "WAITING_APPROVAL")))).scalar()

        projects = []
        for o in conn.execute(select(db.opportunities).where(db.opportunities.c.organization_id == org,
                                                             db.opportunities.c.status.in_(OPP_FLOW[:-1]))
                              .order_by(db.opportunities.c.updated_at.desc()).limit(6)):
            projects.append({"kind": "product", "id": o.id, "title": o.title, "status": o.status,
                             "progress": (OPP_FLOW.index(o.status) + 1) / len(OPP_FLOW)})
        lab_rows = conn.execute(select(db.lab_cycles.c.id, db.lab_cycles.c.status, db.lab_repositories.c.full_name)
                                .join(db.lab_repositories, db.lab_repositories.c.id == db.lab_cycles.c.repository_id)
                                .where(db.lab_cycles.c.organization_id == org, db.lab_cycles.c.status.in_(LAB_FLOW[:-1]))
                                .order_by(db.lab_cycles.c.created_at.desc()).limit(4)).fetchall()
        for r in lab_rows:
            projects.append({"kind": "app_lab", "id": r.id, "title": f"App Lab: {r.full_name}", "status": r.status,
                             "progress": (LAB_FLOW.index(r.status) + 1) / len(LAB_FLOW)})
        inv_rows = conn.execute(select(db.savings_investigations.c.id, db.savings_investigations.c.status, db.cost_review_packets.c.vendor)
                                .join(db.cost_review_packets, db.cost_review_packets.c.id == db.savings_investigations.c.packet_id)
                                .where(db.savings_investigations.c.organization_id == org,
                                       db.savings_investigations.c.status.in_(INV_FLOW[:-1]))).fetchall()
        for r in inv_rows:
            projects.append({"kind": "investigation", "id": r.id, "title": f"Free alternative to {r.vendor}", "status": r.status,
                             "progress": (INV_FLOW.index(r.status) + 1) / len(INV_FLOW)})

        moving = conn.execute(select(db.logistics_packages.c.destination_district, func.count()).where(
            db.logistics_packages.c.organization_id == org, db.logistics_packages.c.status.notin_(("RECEIVED", "DELIVERY_FAILED")))
            .group_by(db.logistics_packages.c.destination_district)).fetchall()
        by_dest = {d: n for d, n in moving}
        conveyor = [{"id": k, "label": label, "in_transit": sum(by_dest.get(d, 0) for d in dists)} for k, label, dists in STAGES]

        waiting = conn.execute(select(func.count()).select_from(db.lab_proposals).where(
            db.lab_proposals.c.organization_id == org, db.lab_proposals.c.status == "AWAITING_OWNER")).scalar()
        out = {"now": datetime.now(timezone.utc).isoformat(), "agents": {"total": agents_total, "working": len({r.agent_id for r in running})},
               "tasks": {"running": len(running), "queued": queued, "completed_today": done_today},
               "projects": {"active": len(projects), "items": projects[:8]}, "conveyor": conveyor,
               "lab_waiting": waiting, "finance": None}
        if p.role in FINANCE_READ_ROLES:
            from services.finance import dashboard

            d = dashboard.build(conn, org)
            f = d.get("last_30_days") or {}
            out["finance"] = {
                "has_data": d["has_data"], "simulated": d["simulated"], "cash_minor": d.get("available_cash_minor"),
                "revenue_30d_minor": f.get("revenue_gross_minor"),
                "expenses_30d_minor": (f.get("operating_expenses_minor") or 0) + (f.get("fees_minor") or 0) if f else None,
                "tax_reserve_minor": (d.get("tax") or {}).get("reserve_minor"),
                "surplus_30d_minor": f.get("net_profit_estimate_minor"), "surplus_label": d["labels"]["profit"],
            }
    return out
