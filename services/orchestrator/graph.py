"""Mission orchestration on LangGraph.

Each mission is a LangGraph thread (thread_id = mission id) over this graph:

    START → prepare ──ok──▶ execute ──continue──▶ execute (one checkpoint per wave of parallel tasks)
               │               ├──waiting──▶ await_approval ──decided──▶ execute
               │               │                  └──still pending──▶ await_approval (interrupt again)
               └──terminal──▶ END   └──completed / failed / paused / cancelled──▶ END

* `await_approval` calls `interrupt()`. The graph's position is checkpointed (SQLite file locally, Postgres when
  DATABASE_URL points at Postgres) and resumed with `Command(resume=...)` when the owner grants or rejects.
* After a crash the worker re-enters the same thread; LangGraph resumes from the last completed node.
* The database stays the source of truth for missions, tasks and events. Nodes are idempotent wrappers around the
  runner's steps, so replaying a node after a crash never repeats finished work.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from services.core import db
from services.core.config import get_settings
from services.core.events import transaction

from . import ops
from .plan import PlanError

log = logging.getLogger("aiciv.graph")
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}


class MissionState(TypedDict, total=False):
    mission_id: str
    outcome: str
    waves: int


_saver = None
_saver_lock = threading.Lock()
_saver_key: str | None = None


def checkpointer():
    """One checkpointer per process; recreated if the configured database changes (tests)."""
    global _saver, _saver_key
    url = get_settings().db_url
    with _saver_lock:
        if _saver is not None and _saver_key == url:
            return _saver
        if url.startswith("postgresql"):
            import psycopg
            from langgraph.checkpoint.postgres import PostgresSaver
            from psycopg.rows import dict_row

            conn = psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://"), autocommit=True, prepare_threshold=0, row_factory=dict_row)
            saver = PostgresSaver(conn)
        else:
            from langgraph.checkpoint.sqlite import SqliteSaver

            path = get_settings().data_dir / "langgraph.sqlite"
            saver = SqliteSaver(sqlite3.connect(str(path), check_same_thread=False))
        saver.setup()
        _saver, _saver_key = saver, url
        return saver


def reset_checkpointer() -> None:
    """Tests only."""
    global _saver, _saver_key
    with _saver_lock:
        conn = getattr(_saver, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
        _saver, _saver_key = None, None


def build_graph(runner):
    from .runner import Cancelled

    def prepare(state: MissionState) -> MissionState:
        try:
            m = runner.mission()
            if m.status in ("CREATED", "VALIDATING"):
                runner._validate()
            if runner.mission().status == "PLANNING":
                runner._plan()
            if runner.mission().status == "QUEUED":
                with transaction() as conn:
                    ops.set_mission_status(conn, runner.mission_id, "RUNNING")
            m = runner.mission()
            if m.status in TERMINAL:
                return {"outcome": m.status}
            if m.paused:
                return {"outcome": "PAUSED"}
            return {"outcome": "WAITING_FOR_APPROVAL" if m.status == "WAITING_FOR_APPROVAL" else "ready"}
        except Cancelled:
            runner._wind_down("cancelled")
            return {"outcome": "CANCELLED"}
        except PlanError as exc:
            runner._fail(str(exc))
            return {"outcome": "FAILED"}

    def execute(state: MissionState) -> MissionState:
        try:
            out = runner._wave()
        except Cancelled:
            runner._wind_down("cancelled")
            out = "CANCELLED"
        return {"outcome": out, "waves": state.get("waves", 0) + 1}

    def await_approval(state: MissionState) -> MissionState:
        m = runner.mission()
        if m.status in TERMINAL:
            return {"outcome": m.status}
        if m.status == "WAITING_FOR_APPROVAL":
            # Pauses the graph here until the owner decides; the decision arrives via Command(resume=...).
            interrupt({"mission_id": runner.mission_id, "waiting_for": "approval"})
        if runner.mission().status in TERMINAL:
            return {"outcome": runner.mission().status}
        resumed = runner._resume_after_approval() if runner.mission().status == "WAITING_FOR_APPROVAL" else True
        return {"outcome": "continue" if resumed else "WAITING_FOR_APPROVAL"}

    def after_prepare(state: MissionState) -> str:
        o = state.get("outcome")
        if o == "ready":
            return "execute"
        if o == "WAITING_FOR_APPROVAL":
            return "await_approval"
        return END

    def after_execute(state: MissionState) -> str:
        o = state.get("outcome")
        if o == "continue":
            return "execute"
        if o == "WAITING_FOR_APPROVAL":
            return "await_approval"
        return END

    def after_approval(state: MissionState) -> str:
        o = state.get("outcome")
        if o == "continue":
            return "execute"
        if o == "WAITING_FOR_APPROVAL":
            return "await_approval"
        return END

    g = StateGraph(MissionState)
    g.add_node("prepare", prepare)
    g.add_node("execute", execute)
    g.add_node("await_approval", await_approval)
    g.add_edge(START, "prepare")
    g.add_conditional_edges("prepare", after_prepare, ["execute", "await_approval", END])
    g.add_conditional_edges("execute", after_execute, ["execute", "await_approval", END])
    g.add_conditional_edges("await_approval", after_approval, ["execute", "await_approval", END])
    return g.compile(checkpointer=checkpointer())


def run_mission_graph(runner) -> str:
    m = runner.mission()
    if m is None:
        return "MISSING"
    graph = build_graph(runner)
    cfg = {"configurable": {"thread_id": runner.mission_id}, "recursion_limit": 500}
    snap = graph.get_state(cfg)
    if snap.next:
        if "await_approval" in snap.next and snap.interrupts:
            graph.invoke(Command(resume={"mission_status": m.status}), cfg)  # owner decided (or mission ended)
        else:
            graph.invoke(None, cfg)  # crash recovery: continue from the last checkpoint
    elif m.status not in TERMINAL and not m.paused:
        graph.invoke({"mission_id": runner.mission_id, "waves": 0}, cfg)
    final = runner.mission()
    return "PAUSED" if final.paused and final.status not in TERMINAL else final.status


def graph_state(mission_id: str) -> dict:
    """For the API: where this mission's graph is and how many checkpoints it has."""
    from .runner import MissionRunner

    runner = MissionRunner(mission_id)
    graph = build_graph(runner)
    cfg = {"configurable": {"thread_id": mission_id}}
    snap = graph.get_state(cfg)
    history = list(graph.get_state_history(cfg))
    return {
        "engine": "langgraph",
        "thread_id": mission_id,
        "next": list(snap.next),
        "values": dict(snap.values or {}),
        "interrupts": [i.value for i in (snap.interrupts or ())],
        "checkpoints": len(history),
        "checkpoint_id": (snap.config or {}).get("configurable", {}).get("checkpoint_id"),
        "steps": [{"source": str((h.metadata or {}).get("source")), "step": (h.metadata or {}).get("step"), "next": list(h.next or ()),
                   "outcome": (h.values or {}).get("outcome")} for h in reversed(history)][:200],
    }
