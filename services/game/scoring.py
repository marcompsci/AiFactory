"""The money game: the agents compete to make the owner the most money, scored only on money that is verified.

What scores (and nothing else does):
  * realized_savings   — an owner-approved, *executed* purchase that cost less per year than what was requested.
                         Evidence: the executed financial approval. Amount: annualized(requested) - annualized(executed).
  * avoided_cost       — the owner rejected a purchase after a free-alternative investigation recommended the
                         alternative. Evidence: the investigation's recommendation and the owner's decision. Amount: the
                         request's annualized cost.
  * attributed_revenue — revenue transactions from a payer the owner explicitly linked to a product the agents built
                         (a revenue link), posted after the link was created. Evidence: the transaction and the link.

Each amount is split equally among the agents that completed work on it (tasks COMPLETED in the missions behind it).
Simulated data scores in a separate, labeled column and never counts as verified. Scores are append-only and
idempotent (one row per source and agent), so re-running the scorer never double counts. Nothing here moves money,
and no agent can write a score: only this scheduled job, from the records above.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.engine import Connection

from services.core import db
from services.core.events import emit
from services.finance.packets import annualize

KINDS = ("realized_savings", "avoided_cost", "attributed_revenue")


def season_for(conn: Connection, org: str, when: str | None = None):
    dt = datetime.fromisoformat(when.replace("Z", "+00:00")) if when else datetime.now(timezone.utc)
    key = f"{dt.year:04d}-{dt.month:02d}"
    row = conn.execute(select(db.game_seasons).where(db.game_seasons.c.organization_id == org, db.game_seasons.c.key == key)).first()
    if row:
        return row
    last = calendar.monthrange(dt.year, dt.month)[1]
    sid = db.new_id()
    conn.execute(db.game_seasons.insert().values(
        id=sid, organization_id=org, key=key, starts_at=datetime(dt.year, dt.month, 1, tzinfo=timezone.utc).isoformat(),
        ends_at=datetime(dt.year, dt.month, last, 23, 59, 59, tzinfo=timezone.utc).isoformat()))
    emit(conn, "game.season_changed", payload={"season": key}, org_id=org)
    return conn.execute(select(db.game_seasons).where(db.game_seasons.c.id == sid)).first()


def _workers(conn: Connection, mission_ids: list[str]) -> list[str]:
    if not mission_ids:
        return []
    rows = conn.execute(select(db.tasks.c.agent_id).where(db.tasks.c.mission_id.in_(mission_ids), db.tasks.c.status == "COMPLETED")).fetchall()
    return sorted({r.agent_id for r in rows})


def _missions_where(conn: Connection, key: str, value: str) -> list[str]:
    # params is JSON on both engines; filtering in Python keeps this portable (volumes are small).
    return [m.id for m in conn.execute(select(db.missions.c.id, db.missions.c.params)) if (m.params or {}).get(key) == value]


def _record(conn: Connection, *, org: str, kind: str, total_minor: int, currency: str, source_type: str, source_id: str, agents: list[str],
            evidence: dict, data_mode: str, when: str | None) -> int:
    if total_minor <= 0 or not agents:
        return 0
    have = {r.agent_id for r in conn.execute(select(db.game_scores.c.agent_id).where(
        db.game_scores.c.organization_id == org, db.game_scores.c.source_type == source_type, db.game_scores.c.source_id == source_id))}
    if have:
        return 0
    season = season_for(conn, org, when)
    share = 1 / len(agents)
    base, rem = divmod(total_minor, len(agents))
    mode = "live" if data_mode == "live" else "simulated"
    for i, aid in enumerate(agents):
        conn.execute(db.game_scores.insert().values(
            id=db.new_id(), organization_id=org, season_id=season.id, agent_id=aid, kind=kind, amount_minor=base + (1 if i < rem else 0),
            currency=currency, share=share, source_type=source_type, source_id=source_id, evidence=evidence, data_mode=mode))
        emit(conn, "game.score_recorded", agent_id=aid, payload={"kind": kind, "season": season.key, "data_mode": mode, "verified": mode == "live"},
             execution_mode="live" if mode == "live" else "simulation", org_id=org)
    return len(agents)


def score_savings(conn: Connection) -> int:
    n = 0
    rows = conn.execute(select(db.financial_approvals).where(db.financial_approvals.c.status == "EXECUTED",
                                                             db.financial_approvals.c.packet_id.isnot(None))).fetchall()
    for a in rows:
        p = conn.execute(select(db.cost_review_packets).where(db.cost_review_packets.c.id == a.packet_id)).first()
        if p is None or a.currency != p.currency:
            continue
        saved = annualize(p.amount_minor, p.interval) - annualize(a.amount_minor, (a.details or {}).get("interval", p.interval))
        if saved <= 0:
            continue
        missions = _missions_where(conn, "packet_id", p.id)
        n += _record(conn, org=a.organization_id, kind="realized_savings", total_minor=saved, currency=a.currency, source_type="financial_approval",
                     source_id=a.id, agents=_workers(conn, missions), data_mode=a.data_mode, when=a.executed_at,
                     evidence={"packet_id": p.id, "vendor": p.vendor, "requested_yearly_minor": annualize(p.amount_minor, p.interval),
                               "executed_option": (a.details or {}).get("option"), "executed_at": a.executed_at,
                               "execution_mode": a.execution_mode})
    return n


def score_avoided(conn: Connection) -> int:
    n = 0
    rows = conn.execute(select(db.savings_investigations).where(db.savings_investigations.c.status == "AWAITING_OWNER")).fetchall()
    for inv in rows:
        if (inv.recommendation or {}).get("verdict") != "consider_alternative":
            continue
        p = conn.execute(select(db.cost_review_packets).where(db.cost_review_packets.c.id == inv.packet_id)).first()
        if p is None or p.status != "REJECTED":
            continue
        # the rejection must be the owner's own decision (recorded in the tamper-evident financial audit chain)
        decided = conn.execute(select(db.financial_audit_events).where(
            db.financial_audit_events.c.subject_id == p.id, db.financial_audit_events.c.action == "packet.status_changed",
            db.financial_audit_events.c.actor_type == "owner").order_by(db.financial_audit_events.c.seq.desc())).first()
        if decided is None or (decided.detail or {}).get("to") != "REJECTED":
            continue
        missions = _missions_where(conn, "investigation_id", inv.id) + _missions_where(conn, "packet_id", p.id)
        n += _record(conn, org=inv.organization_id, kind="avoided_cost", total_minor=annualize(p.amount_minor, p.interval), currency=p.currency,
                     source_type="savings_investigation", source_id=inv.id, agents=_workers(conn, sorted(set(missions))), data_mode=p.data_mode,
                     when=decided.created_at, evidence={"packet_id": p.id, "vendor": p.vendor, "verdict": "consider_alternative",
                                                        "owner_decision": "REJECTED", "audit_event_id": decided.id})
    return n


def score_revenue(conn: Connection) -> int:
    n = 0
    links = conn.execute(select(db.revenue_links).where(db.revenue_links.c.active == 1)).fetchall()
    for link in links:
        opp_missions = [m.id for m in conn.execute(select(db.missions.c.id).where(db.missions.c.opportunity_id == link.opportunity_id))]
        agents = _workers(conn, opp_missions)
        txs = conn.execute(select(db.financial_transactions).where(
            db.financial_transactions.c.organization_id == link.organization_id, db.financial_transactions.c.kind == "revenue",
            db.financial_transactions.c.merchant == link.merchant, db.financial_transactions.c.amount_minor > 0,
            db.financial_transactions.c.posted_at >= link.created_at)).fetchall()
        for t in txs:
            n += _record(conn, org=t.organization_id, kind="attributed_revenue", total_minor=t.amount_minor, currency=t.currency,
                         source_type="financial_transaction", source_id=t.id, agents=agents, data_mode=t.data_mode, when=t.posted_at,
                         evidence={"link_id": link.id, "merchant": link.merchant, "opportunity_id": link.opportunity_id, "posted_at": t.posted_at})
    return n


def tick() -> dict:
    from services.core.events import transaction

    with transaction() as conn:
        return {"savings": score_savings(conn), "avoided": score_avoided(conn), "revenue": score_revenue(conn)}


def leaderboard(conn: Connection, org: str, season_key: str | None = None) -> dict:
    season = season_for(conn, org) if season_key is None else conn.execute(
        select(db.game_seasons).where(db.game_seasons.c.organization_id == org, db.game_seasons.c.key == season_key)).first()
    agents = {a.id: a for a in conn.execute(select(db.agents).where(db.agents.c.organization_id == org))}
    q = select(db.game_scores).where(db.game_scores.c.organization_id == org)
    all_scores = conn.execute(q.order_by(db.game_scores.c.created_at.desc())).fetchall()
    season_scores = [s for s in all_scores if season is not None and s.season_id == season.id]
    tasks = conn.execute(select(db.tasks.c.agent_id, db.tasks.c.updated_at).where(db.tasks.c.status == "COMPLETED")).fetchall()
    xp: dict[str, int] = defaultdict(int)
    days: dict[str, set] = defaultdict(set)
    for t in tasks:
        xp[t.agent_id] += 10
        if t.updated_at:
            days[t.agent_id].add(str(t.updated_at)[:10])
    board = []
    for aid, a in agents.items():
        mine = [s for s in season_scores if s.agent_id == aid]
        verified = sum(s.amount_minor for s in mine if s.data_mode == "live")
        simulated = sum(s.amount_minor for s in mine if s.data_mode != "live")
        by_kind = {k: sum(s.amount_minor for s in mine if s.kind == k and s.data_mode == "live") for k in KINDS}
        lifetime = sum(s.amount_minor for s in all_scores if s.agent_id == aid and s.data_mode == "live")
        level = 1 + int((xp[aid] / 50) ** 0.5)
        board.append({"agent_id": aid, "key": a.key, "name": a.name, "role": a.role, "district": a.home_district, "tier": a.tier,
                      "verified_minor": verified, "simulated_minor": simulated, "by_kind": by_kind, "lifetime_verified_minor": lifetime,
                      "plays": len(mine), "xp": xp[aid], "level": level, "active_days": len(days[aid])})
    board.sort(key=lambda r: (-r["verified_minor"], -r["simulated_minor"], -r["xp"], r["name"]))
    for i, r in enumerate(board, start=1):
        r["rank"] = i
    plays = [{"id": s.id, "agent_id": s.agent_id, "agent": agents[s.agent_id].name if s.agent_id in agents else None, "kind": s.kind,
              "amount_minor": s.amount_minor, "currency": s.currency, "share": s.share, "source_type": s.source_type, "source_id": s.source_id,
              "evidence": s.evidence, "data_mode": s.data_mode, "verified": s.data_mode == "live", "created_at": s.created_at}
             for s in all_scores[:40]]
    seasons = [r.key for r in conn.execute(select(db.game_seasons.c.key).where(db.game_seasons.c.organization_id == org)
                                           .order_by(db.game_seasons.c.key.desc()))]
    return {"season": {"key": season.key, "starts_at": season.starts_at, "ends_at": season.ends_at} if season else None,
            "seasons": seasons, "leaderboard": board, "plays": plays,
            "totals": {"verified_minor": sum(r["verified_minor"] for r in board), "simulated_minor": sum(r["simulated_minor"] for r in board)},
            "rules": __doc__.split("What scores (and nothing else does):", 1)[1].strip()}
