"""AI Civilization HTTP API (FastAPI).

Run:  uvicorn services.api.main:app --port 8000      (from the repo root)
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, insert, select, update

from services.core import db
from services.core.auth import Principal, authenticate, mutation_limiter
from services.core.config import get_settings, load_districts, load_seed
from services.core.events import emit, events_after, transaction
from services.core.realtime import Broadcaster, OutboxPublisher
from services.memory import store as memory
from services.orchestrator import ops
from services.orchestrator.plan import PlanError, validate_prompt
from services.orchestrator.runner import cancel_mission
from services.tools.sandbox import _unshare_available
from services.management.scheduler import Scheduler
from services.model_gateway.gateway import ModelGateway
from services.workers.worker import MissionWorker

logging.basicConfig(level=os.environ.get("AICIV_LOG_LEVEL", "INFO"),
                    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}')
log = logging.getLogger("aiciv.api")
logging.getLogger("httpx").setLevel(logging.WARNING)


class State:
    broadcaster: Broadcaster
    publisher: OutboxPublisher
    worker: MissionWorker
    scheduler: "Scheduler"


state = State()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    state.broadcaster = Broadcaster()
    state.publisher = OutboxPublisher(state.broadcaster)
    state.publisher.start()
    gateway = getattr(app.state, "gateway", None)
    state.worker = MissionWorker(gateway)
    state.scheduler = Scheduler(state.worker.enqueue, gateway if gateway is not None else ModelGateway())
    state.worker.on_finish = state.scheduler.poke
    recovered = state.worker.recover()
    if recovered:
        log.info("recovered missions: %s", recovered)
    state.scheduler.start()
    yield
    state.scheduler.stop()
    state.publisher.stop()
    state.worker.shutdown()
    state.scheduler.join(timeout=5)
    state.publisher.join(timeout=5)


app = FastAPI(title="AI Civilization API", version="0.4.0", lifespan=lifespan)
from services.api.v4 import router as v4_router  # noqa: E402

app.include_router(v4_router)
from services.api.finance import router as finance_router  # noqa: E402

app.include_router(finance_router)
from services.api.applab import router as applab_router  # noqa: E402

app.include_router(applab_router)
from services.api.game import router as game_router  # noqa: E402

app.include_router(game_router)
from services.api.overview import router as overview_router  # noqa: E402

app.include_router(overview_router)
from services.api.factories import router as factories_router  # noqa: E402

app.include_router(factories_router)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().allowed_origins, allow_credentials=False,
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                   allow_headers=["authorization", "content-type", "last-event-id", "x-step-up"])


@app.middleware("http")
async def dev_mode_is_local_only(request: Request, call_next):
    s = get_settings()
    if s.dev_auth and os.environ.get("AICIV_ALLOW_REMOTE_DEV") != "1":
        host = request.client.host if request.client else "127.0.0.1"
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = host in ("localhost", "testclient")
        if not local:
            return JSONResponse({"detail": "dev mode accepts localhost only; set AICIV_API_TOKEN to allow remote clients"}, 403)
    return await call_next(request)


def principal(request: Request) -> Principal:
    return authenticate(request)


def operator(request: Request) -> Principal:
    p = authenticate(request)
    p.require("operator")
    mutation_limiter.check(f"{p.user_id}")
    return p


def admin(request: Request) -> Principal:
    p = authenticate(request)
    p.require("admin")
    return p


def _rows(rows) -> list[dict]:
    return [dict(r._mapping) for r in rows]


# ------------------------------------------------------------------ read models

@app.get("/api/health")
def health(p: Principal = Depends(principal)):
    s = get_settings()
    with db.get_engine().connect() as conn:
        org = conn.execute(select(db.organizations).where(db.organizations.c.id == p.organization_id)).first()
        backlog = conn.execute(select(func.count()).select_from(db.event_outbox).where(db.event_outbox.c.published_at.is_(None))).scalar()
        seq = conn.execute(select(func.max(db.events.c.sequence))).scalar() or 0
    return {
        "status": "ok",
        "database": db.get_engine().dialect.name,
        "auth_mode": p.mode,
        "execution_mode": "live" if s.model_available else "simulation",
        "providers": [n for n, k in (("anthropic", s.anthropic_api_key), ("openai", s.openai_api_key)) if k],
        "sandbox": os.environ.get("AICIV_SANDBOX", "process"),
        "network_isolation": _unshare_available() if os.environ.get("AICIV_SANDBOX") != "docker" else True,
        "outbox_backlog": backlog,
        "publisher_alive": state.publisher.is_alive(),
        "realtime_subscribers": state.broadcaster.subscriber_count,
        "supabase_broadcast": state.publisher.supabase is not None,
        "emergency_stopped": bool(org.emergency_stopped),
        "latest_sequence": seq,
    }


@app.get("/api/snapshot")
def snapshot(p: Principal = Depends(principal)):
    with db.consistent_read() as conn:
        seq = conn.execute(select(func.max(db.events.c.sequence)).where(db.events.c.organization_id == p.organization_id)).scalar() or 0
        agents = _rows(conn.execute(select(db.agents, db.agent_positions.c.district, db.agent_positions.c.waypoint,
                                           db.agent_positions.c.movement_state)
                                    .join(db.agent_positions, db.agent_positions.c.agent_id == db.agents.c.id)
                                    .where(db.agents.c.organization_id == p.organization_id)))
        caps = _rows(conn.execute(select(db.agent_capabilities)))
        for a in agents:
            a["tools"] = sorted(c["tool_name"] for c in caps if c["agent_id"] == a["id"])
        missions = _rows(conn.execute(select(db.missions).where(db.missions.c.organization_id == p.organization_id)
                                      .order_by(db.missions.c.created_at.desc()).limit(25)))
        approvals = _rows(conn.execute(select(db.approvals).where(db.approvals.c.organization_id == p.organization_id,
                                                                  db.approvals.c.status == "PENDING")))
        repos = _rows(conn.execute(select(db.repositories).where(db.repositories.c.organization_id == p.organization_id)))
        org = conn.execute(select(db.organizations).where(db.organizations.c.id == p.organization_id)).first()
        today = ops.spent_today(conn, p.organization_id)
        lines = {r.agent_id: r.supervisor_agent_id for r in conn.execute(select(db.agent_reporting_lines))}
        for a in agents:
            a["supervisor_agent_id"] = lines.get(a["id"])
        depts = _rows(conn.execute(select(db.departments).where(db.departments.c.organization_id == p.organization_id)))
        opps = _rows(conn.execute(select(db.opportunities.c.id, db.opportunities.c.title, db.opportunities.c.status, db.opportunities.c.opportunity_score,
                                         db.opportunities.c.confidence, db.opportunities.c.data_mode, db.opportunities.c.updated_at)
                                  .where(db.opportunities.c.organization_id == p.organization_id).order_by(db.opportunities.c.created_at.desc()).limit(25)))
        from services.logistics import service as logistics_svc
        load = logistics_svc.load_by_segment(conn)
        routes = _rows(conn.execute(select(db.logistics_routes)))
        for r in routes:
            r["load"] = load.get(r["id"], 0)
        logistics = {"nodes": _rows(conn.execute(select(db.logistics_nodes))), "routes": routes,
                     "packages": _rows(conn.execute(select(db.logistics_packages).where(db.logistics_packages.c.status.in_(
                         ["QUEUED", "IN_TRANSIT", "ARRIVED", "DELIVERY_FAILED"])))),
                     "belt_speed": logistics_svc.belt_speed(), "server_time": db.utcnow()}
    return {"sequence": seq, "agents": agents, "missions": missions, "approvals": approvals, "repositories": repos,
            "departments": depts, "opportunities": opps, "logistics": logistics,
            "districts": load_districts(), "emergency_stopped": bool(org.emergency_stopped),
            "costs": {"today_estimated_usd": round(today, 6), "daily_budget_usd": org.daily_budget_usd, "is_estimate": True},
            "execution_mode": "live" if get_settings().model_available else "simulation"}


@app.get("/api/events")
def list_events(after: int = 0, mission_id: str | None = None, limit: int = Query(500, le=2000), p: Principal = Depends(principal)):
    with db.get_engine().connect() as conn:
        return {"events": events_after(conn, after, limit, p.organization_id, mission_id)}


@app.get("/api/stream")
async def stream(request: Request, after: int | None = None, p: Principal = Depends(principal)):
    """SSE: replays from the database after `after` / Last-Event-ID, then streams live envelopes."""
    last = after if after is not None else int(request.headers.get("last-event-id") or 0)
    sub = state.broadcaster.subscribe()

    async def gen():
        nonlocal last
        try:
            with db.get_engine().connect() as conn:
                backlog = events_after(conn, last, 2000, p.organization_id)
            for e in backlog:
                last = e["sequence"]
                yield f"id: {e['sequence']}\nevent: envelope\ndata: {json.dumps(e)}\n\n"
            yield "event: ready\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    e = await asyncio.wait_for(sub[1].get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if e["organization_id"] != p.organization_id or e["sequence"] <= last:
                    continue  # authorization filter + dedupe
                last = e["sequence"]
                yield f"id: {e['sequence']}\nevent: envelope\ndata: {json.dumps(e)}\n\n"
        finally:
            state.broadcaster.unsubscribe(sub)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class MissionIn(BaseModel):
    prompt: str = Field(min_length=8, max_length=4000)
    title: str | None = Field(default=None, max_length=120)
    repository_id: str | None = None
    budget_usd: float | None = Field(default=None, gt=0, le=50)
    idempotency_key: str | None = Field(default=None, max_length=100)


@app.post("/api/missions", status_code=201)
def create_mission(body: MissionIn, p: Principal = Depends(operator)):
    s = get_settings()
    seed = load_seed()
    try:
        prompt = validate_prompt(body.prompt)
    except PlanError as exc:
        raise HTTPException(422, str(exc)) from exc
    with transaction() as conn:
        if body.idempotency_key:
            dup = conn.execute(select(db.missions).where(db.missions.c.organization_id == p.organization_id,
                                                         db.missions.c.idempotency_key == body.idempotency_key)).first()
            if dup:
                return dict(dup._mapping)
        org = conn.execute(select(db.organizations).where(db.organizations.c.id == p.organization_id)).first()
        if org.emergency_stopped:
            raise HTTPException(409, "emergency stop is engaged")
        repo_id = body.repository_id or conn.execute(select(db.repositories.c.id).where(
            db.repositories.c.organization_id == p.organization_id)).scalar()
        mid = db.new_id()
        mode = "live" if s.model_available else "simulation"
        row = dict(id=mid, organization_id=p.organization_id, project_id=seed["project_id"], repository_id=repo_id,
                   title=(body.title or prompt.split(".")[0])[:120], prompt=prompt, status="CREATED", execution_mode=mode,
                   budget_usd=body.budget_usd or s.default_mission_budget_usd, spent_usd_estimated=0.0,
                   idempotency_key=body.idempotency_key, created_by=p.user_id, paused=0)
        conn.execute(insert(db.missions).values(**row))
        emit(conn, "mission.created", mission_id=mid, execution_mode=mode,
             payload={"title": row["title"], "prompt": prompt, "budget_usd": row["budget_usd"], "execution_mode": mode})
    state.worker.enqueue(mid)
    with db.get_engine().connect() as conn:
        return dict(ops.mission_row(conn, mid)._mapping)


@app.get("/api/missions")
def list_missions(p: Principal = Depends(principal)):
    with db.get_engine().connect() as conn:
        return {"missions": _rows(conn.execute(select(db.missions).where(db.missions.c.organization_id == p.organization_id)
                                               .order_by(db.missions.c.created_at.desc()).limit(100)))}


def _mission_or_404(conn, mission_id: str, p: Principal):
    m = ops.mission_row(conn, mission_id)
    if m is None or m.organization_id != p.organization_id:
        raise HTTPException(404, "mission not found")
    return m


@app.get("/api/missions/{mission_id}")
def get_mission(mission_id: str, p: Principal = Depends(principal)):
    with db.get_engine().connect() as conn:
        m = _mission_or_404(conn, mission_id, p)
        tasks = _rows(conn.execute(select(db.tasks).where(db.tasks.c.mission_id == mission_id).order_by(db.tasks.c.ordinal)))
        ids = [t["id"] for t in tasks]
        deps = _rows(conn.execute(select(db.task_dependencies).where(db.task_dependencies.c.task_id.in_(ids)))) if ids else []
        runs = _rows(conn.execute(select(db.task_runs).where(db.task_runs.c.task_id.in_(ids)).order_by(db.task_runs.c.started_at))) if ids else []
        msgs = _rows(conn.execute(select(db.agent_messages).where(db.agent_messages.c.mission_id == mission_id).order_by(db.agent_messages.c.created_at)))
        tools = _rows(conn.execute(select(db.tool_executions).where(db.tool_executions.c.mission_id == mission_id).order_by(db.tool_executions.c.started_at)))
        arts = _rows(conn.execute(select(db.artifacts.c.id, db.artifacts.c.kind, db.artifacts.c.title, db.artifacts.c.agent_id,
                                         db.artifacts.c.created_at).where(db.artifacts.c.mission_id == mission_id)))
        approvals = _rows(conn.execute(select(db.approvals).where(db.approvals.c.mission_id == mission_id)))
        usage = _rows(conn.execute(select(db.usage_records).where(db.usage_records.c.mission_id == mission_id)))
    return {"mission": dict(m._mapping), "tasks": tasks, "dependencies": deps, "task_runs": runs, "messages": msgs,
            "tool_executions": tools, "artifacts": arts, "approvals": approvals, "usage": usage}


@app.post("/api/missions/{mission_id}/cancel")
def cancel(mission_id: str, p: Principal = Depends(operator)):
    with db.get_engine().connect() as conn:
        _mission_or_404(conn, mission_id, p)
    cancel_mission(mission_id)
    state.worker.enqueue(mission_id)  # lets a graph paused at an approval interrupt reach END
    return {"ok": True}


@app.get("/api/missions/{mission_id}/graph")
def mission_graph(mission_id: str, p: Principal = Depends(principal)):
    """The LangGraph view of a mission: current node, pending interrupts and checkpoint history."""
    from services.orchestrator.graph import graph_state
    with db.get_engine().connect() as conn:
        _mission_or_404(conn, mission_id, p)
    return graph_state(mission_id)


@app.post("/api/missions/{mission_id}/pause")
def pause(mission_id: str, p: Principal = Depends(operator)):
    with transaction() as conn:
        m = _mission_or_404(conn, mission_id, p)
        if m.status in ("COMPLETED", "FAILED", "CANCELLED"):
            raise HTTPException(409, f"mission is {m.status}")
        conn.execute(update(db.missions).where(db.missions.c.id == mission_id).values(paused=1, pause_reason="paused by operator"))
        emit(conn, "mission.status_changed", mission_id=mission_id, execution_mode=m.execution_mode,
             payload={"from": m.status, "to": m.status, "paused": True, "pause_reason": "paused by operator"})
    return {"ok": True, "note": "tasks already running finish their current step; no new tasks start"}


@app.post("/api/missions/{mission_id}/resume")
def resume(mission_id: str, p: Principal = Depends(operator)):
    with transaction() as conn:
        m = _mission_or_404(conn, mission_id, p)
        if not m.paused:
            return {"ok": True}
        conn.execute(update(db.missions).where(db.missions.c.id == mission_id).values(paused=0, pause_reason=None))
        emit(conn, "mission.status_changed", mission_id=mission_id, execution_mode=m.execution_mode,
             payload={"from": m.status, "to": m.status, "paused": False})
    state.worker.enqueue(mission_id)
    return {"ok": True}


class BudgetIn(BaseModel):
    budget_usd: float = Field(gt=0, le=50)


@app.patch("/api/missions/{mission_id}/budget")
def set_budget(mission_id: str, body: BudgetIn, p: Principal = Depends(admin)):
    with transaction() as conn:
        _mission_or_404(conn, mission_id, p)
        conn.execute(update(db.missions).where(db.missions.c.id == mission_id).values(budget_usd=body.budget_usd))
    return {"ok": True}


def _decide(approval_id: str, p: Principal, granted: bool):
    with transaction() as conn:
        a = conn.execute(select(db.approvals).where(db.approvals.c.id == approval_id)).first()
        if a is None or a.organization_id != p.organization_id:
            raise HTTPException(404, "approval not found")
        if a.status != "PENDING":
            raise HTTPException(409, f"approval already {a.status}")
        m = ops.mission_row(conn, a.mission_id)
        conn.execute(update(db.approvals).where(db.approvals.c.id == approval_id).values(
            status="GRANTED" if granted else "REJECTED", decided_by=p.user_id, decided_at=db.utcnow()))
        emit(conn, "approval.granted" if granted else "approval.rejected", mission_id=a.mission_id, execution_mode=m.execution_mode,
             payload={"approval_id": approval_id, "task_id": a.task_id, "action": a.action, "decided_by": p.user_id})
    state.worker.enqueue(a.mission_id)
    return {"ok": True}


@app.post("/api/approvals/{approval_id}/grant")
def grant(approval_id: str, p: Principal = Depends(operator)):
    return _decide(approval_id, p, True)


@app.post("/api/approvals/{approval_id}/reject")
def reject(approval_id: str, p: Principal = Depends(operator)):
    return _decide(approval_id, p, False)


@app.get("/api/artifacts/{artifact_id}")
def get_artifact(artifact_id: str, p: Principal = Depends(principal)):
    with db.get_engine().connect() as conn:
        a = conn.execute(select(db.artifacts).where(db.artifacts.c.id == artifact_id)).first()
    if a is None or a.organization_id != p.organization_id:
        raise HTTPException(404, "artifact not found")
    return dict(a._mapping)


@app.get("/api/agents/{agent_id}")
def get_agent(agent_id: str, p: Principal = Depends(principal)):
    with db.get_engine().connect() as conn:
        a = conn.execute(select(db.agents).where(db.agents.c.id == agent_id)).first()
        if a is None or a.organization_id != p.organization_id:
            raise HTTPException(404, "agent not found")
        tasks = _rows(conn.execute(select(db.tasks.c.id, db.tasks.c.mission_id, db.tasks.c.key, db.tasks.c.title, db.tasks.c.status,
                                          db.tasks.c.updated_at).where(db.tasks.c.agent_id == agent_id)
                                   .order_by(db.tasks.c.updated_at.desc()).limit(30)))
        tools = _rows(conn.execute(select(db.tool_executions).where(db.tool_executions.c.agent_id == agent_id)
                                   .order_by(db.tool_executions.c.started_at.desc()).limit(30)))
        msgs = _rows(conn.execute(select(db.agent_messages).where(db.agent_messages.c.from_agent_id == agent_id)
                                  .order_by(db.agent_messages.c.created_at.desc()).limit(30)))
        usage = conn.execute(select(func.coalesce(func.sum(db.usage_records.c.estimated_cost_usd), 0.0),
                                    func.coalesce(func.sum(db.usage_records.c.input_tokens), 0),
                                    func.coalesce(func.sum(db.usage_records.c.output_tokens), 0))
                             .where(db.usage_records.c.agent_id == agent_id)).first()
        caps = [r.tool_name for r in conn.execute(select(db.agent_capabilities.c.tool_name).where(db.agent_capabilities.c.agent_id == agent_id))]
        pos = conn.execute(select(db.agent_positions).where(db.agent_positions.c.agent_id == agent_id)).first()
        audit = _rows(conn.execute(select(db.events.c.sequence, db.events.c.event_type, db.events.c.occurred_at, db.events.c.payload,
                                          db.events.c.execution_mode).where(db.events.c.agent_id == agent_id)
                                   .order_by(db.events.c.sequence.desc()).limit(50)))
    return {"agent": {**dict(a._mapping), "tools": sorted(caps), "position": dict(pos._mapping) if pos else None},
            "tasks": tasks, "tool_executions": tools, "messages": msgs, "audit": audit,
            "usage": {"estimated_cost_usd": round(float(usage[0]), 6), "input_tokens": int(usage[1]), "output_tokens": int(usage[2]),
                      "is_estimate": True}}


@app.get("/api/memory")
def search_memory(q: str = "", trust: str | None = None, p: Principal = Depends(principal)):
    with db.get_engine().connect() as conn:
        return {"entries": memory.search(conn, p.organization_id, q, trust=trust)}


@app.delete("/api/memory/{memory_id}")
def delete_memory(memory_id: str, p: Principal = Depends(admin)):
    with transaction() as conn:
        if not memory.forget(conn, p.organization_id, memory_id):
            raise HTTPException(404, "memory not found")
    return {"ok": True}


@app.get("/api/costs")
def costs(p: Principal = Depends(principal)):
    with db.get_engine().connect() as conn:
        by_agent = _rows(conn.execute(select(db.usage_records.c.agent_id, db.usage_records.c.provider, db.usage_records.c.model,
                                             func.sum(db.usage_records.c.input_tokens).label("input_tokens"),
                                             func.sum(db.usage_records.c.output_tokens).label("output_tokens"),
                                             func.sum(db.usage_records.c.estimated_cost_usd).label("estimated_cost_usd"))
                                      .where(db.usage_records.c.organization_id == p.organization_id)
                                      .group_by(db.usage_records.c.agent_id, db.usage_records.c.provider, db.usage_records.c.model)))
        tools = _rows(conn.execute(select(db.tool_executions.c.tool_name, func.count().label("calls"),
                                          func.sum(db.tool_executions.c.duration_ms).label("total_ms"))
                                   .where(db.tool_executions.c.organization_id == p.organization_id)
                                   .group_by(db.tool_executions.c.tool_name)))
        org = conn.execute(select(db.organizations).where(db.organizations.c.id == p.organization_id)).first()
        today = ops.spent_today(conn, p.organization_id)
    return {"today_estimated_usd": round(today, 6), "daily_budget_usd": org.daily_budget_usd, "by_agent_model": by_agent,
            "tool_time": tools, "note": "Estimated from token counts and the configured price table; not a provider invoice."}


class StopIn(BaseModel):
    engaged: bool


@app.post("/api/emergency-stop")
def emergency_stop(body: StopIn, p: Principal = Depends(admin)):
    with transaction() as conn:
        conn.execute(update(db.organizations).where(db.organizations.c.id == p.organization_id).values(emergency_stopped=int(body.engaged)))
        emit(conn, "system.emergency_stop", payload={"engaged": body.engaged, "by": p.user_id})
        active = [r.id for r in conn.execute(select(db.missions.c.id).where(
            db.missions.c.organization_id == p.organization_id,
            db.missions.c.status.in_(["CREATED", "VALIDATING", "PLANNING", "QUEUED", "RUNNING", "WAITING_FOR_APPROVAL"])))]
    if body.engaged:
        for mid in active:
            cancel_mission(mid, "emergency stop")
    return {"ok": True, "cancelled": active if body.engaged else []}
