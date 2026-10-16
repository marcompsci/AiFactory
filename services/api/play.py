"""V6 playable town API: the owner's avatar and position, talking to agent NPCs, and confirm-to-run proposals.

Talking never changes anything by itself. An actionable request comes back as a proposal; only POST
/proposals/{id}/confirm runs it, through the same functions (and checks) as the mission and research endpoints. Proposals
expire after 15 minutes, and walking away, closing the game or reconnecting never confirms one.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import insert, select, update

from services.core import db
from services.core.auth import Principal, authenticate, mutation_limiter
from services.core.events import transaction
from services.play import npc

router = APIRouter(prefix="/api/play")

MAPS = ("town", "nexus-spire", "data-observatory", "code-forge")
HAIR = ("spiky", "short", "buzz", "curly", "long", "bun", "afro", "bald")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def member(request: Request) -> Principal:
    return authenticate(request)


def operator(request: Request) -> Principal:
    p = authenticate(request)
    p.require("operator")
    mutation_limiter.check(p.user_id)
    return p


class Look(BaseModel):
    skin: str = "#E8B48A"
    hair_style: str = Field(default="spiky", pattern="^(" + "|".join(HAIR) + ")$")
    hair: str = "#1E1B22"
    shirt: str = "#B8BCC6"
    pants: str = "#25252E"
    shoes: str = "#F2F2F2"
    glasses: bool = True

    @field_validator("skin", "hair", "shirt", "pants", "shoes")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not HEX.match(v):
            raise ValueError("colors are #RRGGBB")
        return v.upper()


class PlayerIn(BaseModel):
    name: str = Field(default="Owner", min_length=1, max_length=24)
    look: Look = Field(default_factory=Look)
    map: str = Field(default="town", pattern="^(" + "|".join(MAPS) + ")$")
    x: float = Field(default=0, ge=0, le=256)
    y: float = Field(default=0, ge=0, le=256)
    facing: str = Field(default="down", pattern="^(down|up|left|right)$")


class TalkIn(BaseModel):
    agent_id: str = Field(min_length=36, max_length=36)
    text: str = Field(default="", max_length=2000)


def _agent(conn, agent_id: str, org: str):
    a = conn.execute(select(db.agents).where(db.agents.c.id == agent_id, db.agents.c.organization_id == org)).first()
    if a is None:
        raise HTTPException(404, "agent not found")
    return a


def _expire(conn, org: str, user: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(update(db.play_proposals).where(db.play_proposals.c.organization_id == org, db.play_proposals.c.user_id == user,
                                                 db.play_proposals.c.status == "PENDING", db.play_proposals.c.expires_at < now)
                 .values(status="EXPIRED", decided_at=now))


def _say(conn, p: Principal, agent_id: str, speaker: str, text: str, proposal_id: str | None = None) -> dict:
    row = dict(id=db.new_id(), organization_id=p.organization_id, user_id=p.user_id, agent_id=agent_id, speaker=speaker,
               text=text[:8000], proposal_id=proposal_id, created_at=db.utcnow())
    conn.execute(insert(db.play_messages).values(**row))
    return row


@router.get("/state")
def get_state(p: Principal = Depends(member)):
    with db.get_engine().connect() as conn:
        row = conn.execute(select(db.play_players.c.data).where(db.play_players.c.organization_id == p.organization_id,
                                                                db.play_players.c.user_id == p.user_id)).first()
        pending = [dict(r._mapping) for r in conn.execute(select(db.play_proposals).where(
            db.play_proposals.c.organization_id == p.organization_id, db.play_proposals.c.user_id == p.user_id,
            db.play_proposals.c.status == "PENDING", db.play_proposals.c.expires_at >= datetime.now(timezone.utc).isoformat()))]
    return {"player": row.data if row else None, "default": PlayerIn().model_dump(), "pending_proposals": pending}


@router.put("/state")
def put_state(body: PlayerIn, p: Principal = Depends(operator)):
    data = body.model_dump()
    with transaction() as conn:
        found = conn.execute(select(db.play_players.c.id).where(db.play_players.c.organization_id == p.organization_id,
                                                                db.play_players.c.user_id == p.user_id)).scalar()
        if found:
            conn.execute(update(db.play_players).where(db.play_players.c.id == found).values(data=data, updated_at=db.utcnow()))
        else:
            conn.execute(insert(db.play_players).values(id=db.new_id(), organization_id=p.organization_id, user_id=p.user_id, data=data))
    return {"player": data}


@router.get("/conversations/{agent_id}")
def conversation(agent_id: str, p: Principal = Depends(member)):
    with db.get_engine().connect() as conn:
        _agent(conn, agent_id, p.organization_id)
        msgs = [dict(r._mapping) for r in conn.execute(select(db.play_messages).where(
            db.play_messages.c.organization_id == p.organization_id, db.play_messages.c.user_id == p.user_id,
            db.play_messages.c.agent_id == agent_id).order_by(db.play_messages.c.created_at.desc()).limit(60))][::-1]
        ids = [m["proposal_id"] for m in msgs if m["proposal_id"]]
        props = {r.id: dict(r._mapping) for r in conn.execute(select(db.play_proposals).where(db.play_proposals.c.id.in_(ids)))} if ids else {}
    now = datetime.now(timezone.utc).isoformat()
    for pr in props.values():
        if pr["status"] == "PENDING" and pr["expires_at"] < now:
            pr["status"] = "EXPIRED"
    return {"messages": msgs, "proposals": props}


@router.post("/talk")
def talk(body: TalkIn, p: Principal = Depends(operator)):
    with transaction() as conn:
        agent = _agent(conn, body.agent_id, p.organization_id)
        _expire(conn, p.organization_id, p.user_id)
        if body.text.strip():
            _say(conn, p, agent.id, "owner", body.text.strip())
        reply = npc.respond(conn, org=p.organization_id, user=p.user_id, agent=agent, text=body.text)
        msg = _say(conn, p, agent.id, "npc", reply.text, reply.proposal["id"] if reply.proposal else None)
    return {"reply": reply.text, "message": msg, "proposal": reply.proposal, "suggestions": reply.suggestions}


def _proposal(conn, pid: str, p: Principal):
    pr = conn.execute(select(db.play_proposals).where(db.play_proposals.c.id == pid)).first()
    if pr is None or pr.organization_id != p.organization_id or pr.user_id != p.user_id:
        raise HTTPException(404, "proposal not found")
    return pr


def _run(pr, p: Principal) -> dict:
    """Runs the action through the regular endpoints' functions, so permissions and validation are identical."""
    from services.api import main, v4
    if pr.kind == "create_mission":
        m = main.create_mission(main.MissionIn(prompt=pr.params["prompt"], idempotency_key=f"play:{pr.id}"), p)
        return {"mission_id": m["id"], "title": m["title"], "execution_mode": m["execution_mode"]}
    if pr.kind == "start_research":
        r = v4.start_research(v4.ResearchIn(**pr.params), p)
        with db.get_engine().connect() as conn:
            m = conn.execute(select(db.missions.c.title, db.missions.c.execution_mode).where(db.missions.c.id == r["mission_id"])).first()
        return {"mission_id": r["mission_id"], "title": m.title, "execution_mode": m.execution_mode}
    if pr.kind == "cancel_mission":
        main.cancel(pr.params["mission_id"], p)
        return {"mission_id": pr.params["mission_id"], "cancelled": True}
    raise HTTPException(400, "unknown proposal")


@router.post("/proposals/{pid}/confirm")
def confirm(pid: str, p: Principal = Depends(operator)):
    now = datetime.now(timezone.utc).isoformat()
    with transaction() as conn:
        pr = _proposal(conn, pid, p)
        if pr.status == "PENDING" and pr.expires_at < now:
            conn.execute(update(db.play_proposals).where(db.play_proposals.c.id == pid).values(status="EXPIRED", decided_at=now))
            raise HTTPException(409, "this offer expired; ask again")
        if pr.status != "PENDING":
            raise HTTPException(409, f"proposal already {pr.status}")
        claimed = conn.execute(update(db.play_proposals).where(db.play_proposals.c.id == pid, db.play_proposals.c.status == "PENDING")
                               .values(status="CONFIRMED", decided_at=now)).rowcount
        if not claimed:
            raise HTTPException(409, "proposal already decided")
    try:
        result = _run(pr, p)
        status, text = "CONFIRMED", _done_text(pr.kind, result)
    except HTTPException as exc:
        result, status = {"error": str(exc.detail)}, "FAILED"
        text = f"I couldn't start that: {exc.detail}."
    with transaction() as conn:
        conn.execute(update(db.play_proposals).where(db.play_proposals.c.id == pid).values(status=status, result=result))
        msg = _say(conn, p, pr.agent_id, "npc", text, pid)
    return {"status": status, "result": result, "message": msg}


def _done_text(kind: str, r: dict) -> str:
    if kind == "cancel_mission":
        return "Done: the mission is cancelled. Anything already running stops at its next step."
    sim = " It's running in simulation because no AI model is connected, so treat its output as a rehearsal." if r.get("execution_mode") == "simulation" else ""
    return f"Started \"{r.get('title', 'the mission')}\". Follow it in the journal; I'll show my status as I work.{sim}"


@router.post("/proposals/{pid}/decline")
def decline(pid: str, p: Principal = Depends(operator)):
    with transaction() as conn:
        pr = _proposal(conn, pid, p)
        if pr.status != "PENDING":
            raise HTTPException(409, f"proposal already {pr.status}")
        conn.execute(update(db.play_proposals).where(db.play_proposals.c.id == pid).values(status="DECLINED", decided_at=db.utcnow()))
        _say(conn, p, pr.agent_id, "npc", "Okay, I won't do that.", pid)
    return {"status": "DECLINED"}


@router.get("/districts/{district}")
def district_activity(district: str, p: Principal = Depends(member)):
    """What's happening in one building right now, from the records: tasks in progress there, who's inside, and
    packages coming and going. Read-only."""
    from services.core.config import load_districts

    if district not in {d["id"] for d in load_districts()}:
        raise HTTPException(404, "unknown district")
    org = p.organization_id
    with db.get_engine().connect() as conn:
        tasks = [dict(r._mapping) for r in conn.execute(
            select(db.tasks.c.id, db.tasks.c.title, db.tasks.c.status, db.tasks.c.updated_at, db.tasks.c.agent_id,
                   db.missions.c.id.label("mission_id"), db.missions.c.title.label("mission"), db.missions.c.execution_mode,
                   db.agents.c.name.label("agent"))
            .join(db.missions, db.missions.c.id == db.tasks.c.mission_id)
            .join(db.agents, db.agents.c.id == db.tasks.c.agent_id)
            .where(db.tasks.c.organization_id == org, db.tasks.c.district == district,
                   db.tasks.c.status.in_(("PENDING", "RUNNING", "WAITING_FOR_APPROVAL")),
                   db.missions.c.status.notin_(("COMPLETED", "FAILED", "CANCELLED")))
            .order_by(db.tasks.c.updated_at.desc()).limit(20))]
        recent = [dict(r._mapping) for r in conn.execute(
            select(db.tasks.c.title, db.tasks.c.status, db.tasks.c.updated_at, db.agents.c.name.label("agent"))
            .join(db.agents, db.agents.c.id == db.tasks.c.agent_id)
            .where(db.tasks.c.organization_id == org, db.tasks.c.district == district, db.tasks.c.status.in_(("COMPLETED", "FAILED")))
            .order_by(db.tasks.c.updated_at.desc()).limit(5))]
        present = [dict(r._mapping) for r in conn.execute(
            select(db.agents.c.id, db.agents.c.name, db.agents.c.role, db.agents.c.execution_state)
            .join(db.agent_positions, db.agent_positions.c.agent_id == db.agents.c.id)
            .where(db.agents.c.organization_id == org, db.agent_positions.c.district == district).order_by(db.agents.c.name))]
        pk = db.logistics_packages.c
        packages = [dict(r._mapping) for r in conn.execute(
            select(pk.id, pk.package_type, pk.status, pk.origin_district, pk.destination_district, pk.eta)
            .where(pk.organization_id == org, pk.status.in_(("QUEUED", "IN_TRANSIT", "ARRIVED", "DELIVERY_FAILED")),
                   (pk.origin_district == district) | (pk.destination_district == district))
            .order_by(pk.created_at.desc()).limit(10))]
    return {"district": district, "tasks": tasks, "recent": recent, "agents": present, "packages": packages}
