"""Durable mission runner.

All progress lives in the database (missions, tasks, task_runs, approvals, events), so the runner is
restartable: `recover()` on worker start resets interrupted task runs and re-enqueues active missions,
and every handler is written to be safe to re-run (worktree reuse, edit-already-applied detection).

Scheduling: tasks whose dependencies are COMPLETED or SKIPPED run in parallel (bounded pool); each
agent works one task at a time (`max_concurrent_tasks`), enforced with per-agent locks plus the DB state.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait

from sqlalchemy import func, insert, select, update

from services.core import db
from services.core.config import get_settings, load_districts
from services.core.events import emit, transaction
from services.model_gateway.gateway import ModelGateway, ModelRequest, ProviderError
from services.tools.registry import ToolContext

from services.management.hierarchy import submit_report
from services.management import reliability

from . import ops
from .handlers import HANDLERS, NeedsApproval, SkipTask, TaskEnv, TaskError, VerificationFailed
from .studio_handlers import V4_HANDLERS

HANDLERS.update(V4_HANDLERS)
from services.finance.handlers import FINANCE_HANDLERS  # noqa: E402

HANDLERS.update(FINANCE_HANDLERS)
from services.applab.handlers import LAB_HANDLERS  # noqa: E402

HANDLERS.update(LAB_HANDLERS)
from services.factories.handlers import FACTORY_HANDLERS  # noqa: E402

HANDLERS.update(FACTORY_HANDLERS)
from .plan import PlanError, plan_for, validate_prompt

log = logging.getLogger("aiciv.runner")

_agent_locks: dict[str, threading.Lock] = {}
_agent_locks_guard = threading.Lock()
WORKSTATIONS = {w["id"]: d["id"] for d in load_districts() for w in d["workstations"]}
DONE = {"COMPLETED", "SKIPPED"}
TERMINAL_TASK = {"COMPLETED", "SKIPPED", "FAILED", "CANCELLED"}


class Cancelled(Exception):
    pass


def agent_lock(agent_id: str) -> threading.Lock:
    with _agent_locks_guard:
        return _agent_locks.setdefault(agent_id, threading.Lock())


class MissionRunner:
    def __init__(self, mission_id: str, gateway: ModelGateway | None = None) -> None:
        self.mission_id = mission_id
        self.gateway = gateway or ModelGateway()
        self.settings = get_settings()

    # ---------------------------------------------------------------- helpers
    def mission(self):
        with db.get_engine().connect() as conn:
            return ops.mission_row(conn, self.mission_id)

    def tasks(self) -> list:
        with db.get_engine().connect() as conn:
            return conn.execute(select(db.tasks).where(db.tasks.c.mission_id == self.mission_id).order_by(db.tasks.c.ordinal)).fetchall()

    def deps(self) -> dict[str, set[str]]:
        with db.get_engine().connect() as conn:
            rows = conn.execute(select(db.task_dependencies).join(db.tasks, db.tasks.c.id == db.task_dependencies.c.task_id)
                                .where(db.tasks.c.mission_id == self.mission_id)).fetchall()
        out: dict[str, set[str]] = {}
        for r in rows:
            out.setdefault(r.task_id, set()).add(r.depends_on_task_id)
        return out

    def check_cancel(self) -> None:
        m = self.mission()
        if m.status == "CANCELLED":
            raise Cancelled()

    # ---------------------------------------------------------------- lifecycle
    def run(self) -> str:
        """Missions run as LangGraph graphs (checkpointed per mission, approval = interrupt)."""
        from .graph import run_mission_graph
        return run_mission_graph(self)

    def run_direct(self) -> str:
        """The same lifecycle without LangGraph (kept for debugging and as the reference behavior)."""
        m = self.mission()
        if m is None or m.status in ("COMPLETED", "FAILED", "CANCELLED") or m.paused:
            return m.status if m else "MISSING"
        try:
            if m.status in ("CREATED", "VALIDATING"):
                self._validate()
            if self.mission().status == "PLANNING":
                self._plan()
            if self.mission().status == "QUEUED":
                with transaction() as conn:
                    ops.set_mission_status(conn, self.mission_id, "RUNNING")
            if self.mission().status == "WAITING_FOR_APPROVAL":
                if not self._resume_after_approval():
                    return "WAITING_FOR_APPROVAL"
            return self._execute()
        except Cancelled:
            self._wind_down("cancelled")
            return "CANCELLED"
        except PlanError as exc:
            self._fail(str(exc))
            return "FAILED"

    def _validate(self) -> None:
        m = self.mission()
        with transaction() as conn:
            if m.status == "CREATED":
                ops.set_mission_status(conn, self.mission_id, "VALIDATING")
        validate_prompt(m.prompt)
        with db.get_engine().connect() as conn:
            org = conn.execute(select(db.organizations).where(db.organizations.c.id == m.organization_id)).first()
            repo = conn.execute(select(db.repositories).where(db.repositories.c.id == m.repository_id)).first()
            project = conn.execute(select(db.projects).where(db.projects.c.id == m.project_id)).first()
        if org.emergency_stopped:
            raise PlanError("emergency stop is engaged")
        if m.kind == "fix_failing_test" and (repo is None or repo.project_id != m.project_id):
            raise PlanError("repository is not part of this project")
        needed = {t for spec in plan_for(m.kind, m.params) for t in spec.permitted_tools}
        missing = needed - set(project.allowed_tools or [])
        if missing:
            raise PlanError(f"project does not allow tools: {sorted(missing)}")
        if m.budget_usd <= 0:
            raise PlanError("mission budget must be positive")
        with transaction() as conn:
            commander = conn.execute(select(db.agents).where(db.agents.c.key == "commander")).first()
            ops.message(conn, mission_id=self.mission_id, from_agent=commander.id, to_agent=None, kind="status",
                        body=f"Permissions validated for {repo.full_name if repo and m.kind == 'fix_failing_test' else m.kind.replace('_', ' ')}: {len(needed)} tools within project policy.",
                        mode=m.execution_mode, org_id=m.organization_id)
            ops.set_mission_status(conn, self.mission_id, "PLANNING")

    def _plan(self) -> None:
        m = self.mission()
        graph = plan_for(m.kind, m.params)
        with db.get_engine().connect() as conn:
            agents = {a.key: a for a in conn.execute(select(db.agents)).fetchall()}
            existing = conn.execute(select(db.tasks.c.id).where(db.tasks.c.mission_id == self.mission_id)).first()
        rationale = None
        if m.kind != "fix_failing_test":
            rationale = f"Plan: {', '.join(t.title.lower() for t in graph)}."
        elif m.execution_mode == "live":
            try:
                with transaction() as conn:
                    ops.check_budget(conn, self.mission_id, agents["commander"].id, m.organization_id)
                res = self.gateway.complete(ModelRequest(
                    system="You are the Mission Commander of a supervised software team. Be brief and concrete.",
                    prompt=(f"Operator mission: {m.prompt}\nThe plan is fixed as: "
                            + "; ".join(f"{t.key} ({t.agent_key})" for t in graph)
                            + ". In two sentences, tell the team what to watch for."), max_tokens=200),
                    preferred_provider=agents["commander"].model_provider)
                with transaction() as conn:
                    ops.record_usage(conn, org_id=m.organization_id, mission_id=self.mission_id, agent_id=agents["commander"].id,
                                     provider=res.provider, model=res.model, input_tokens=res.input_tokens,
                                     output_tokens=res.output_tokens, estimated_cost_usd=res.estimated_cost_usd)
                rationale = res.text.strip()
            except (ProviderError, ops.BudgetExceeded) as exc:
                rationale = f"Planning note unavailable ({exc}). Proceeding with the validated plan."
        else:
            rationale = "[simulation · templated text] Inspect and reproduce in parallel, fix in an isolated worktree, verify, review, then wait for your approval to publish."
        with transaction() as conn:
            if not existing:
                ids = {}
                for i, spec in enumerate(graph):
                    tid = db.new_id()
                    ids[spec.key] = tid
                    conn.execute(insert(db.tasks).values(
                        id=tid, organization_id=m.organization_id, mission_id=self.mission_id, agent_id=agents[spec.agent_key].id,
                        key=spec.key, title=spec.title, district=spec.district, status="PENDING",
                        inputs={"workstation": spec.workstation, "repository_id": m.repository_id},
                        permitted_tools=spec.permitted_tools, expected_outputs=spec.expected_outputs, validation=spec.validation,
                        attempt=0, max_attempts=spec.max_attempts, timeout_seconds=spec.timeout_seconds, ordinal=i))
                for spec in graph:
                    for d in spec.depends_on:
                        conn.execute(insert(db.task_dependencies).values(task_id=ids[spec.key], depends_on_task_id=ids[d]))
                for spec in graph:
                    emit(conn, "task.assigned", mission_id=self.mission_id, agent_id=agents[spec.agent_key].id,
                         execution_mode=m.execution_mode,
                         payload={"task_id": ids[spec.key], "key": spec.key, "title": spec.title, "district": spec.district,
                                  "depends_on": spec.depends_on})
            ops.message(conn, mission_id=self.mission_id, from_agent=agents["commander"].id, to_agent=None, kind="explanation",
                        body=rationale, mode=m.execution_mode, org_id=m.organization_id)
            ops.set_mission_status(conn, self.mission_id, "QUEUED")

    def _resume_after_approval(self) -> bool:
        waiting = [t for t in self.tasks() if t.status == "WAITING_FOR_APPROVAL"]
        with db.get_engine().connect() as conn:
            decisions = {t.id: conn.execute(select(db.approvals.c.status).where(db.approvals.c.task_id == t.id)
                                            .order_by(db.approvals.c.created_at.desc())).scalar() for t in waiting}
        if any(s == "PENDING" for s in decisions.values()):
            return False
        with transaction() as conn:
            for t in waiting:
                if decisions[t.id] == "REJECTED":
                    ops.set_task_status(conn, t.id, "SKIPPED", outputs={"published": False, "reason": "rejected by reviewer"})
                    ops.set_agent_state(conn, t.agent_id, "CANCELLED", self.mission_id, self.mission().execution_mode)
                else:
                    ops.set_task_status(conn, t.id, "RUNNING")
            ops.set_mission_status(conn, self.mission_id, "RUNNING")
        return True

    def _execute(self) -> str:
        while True:
            out = self._wave()
            if out != "continue":
                return out

    def _wave(self) -> str:
        """One scheduling step: run every ready task in parallel and wait. Returns "continue" or the mission status
        the step ended in. This is the unit LangGraph checkpoints (services/orchestrator/graph.py)."""
        self.check_cancel()
        m = self.mission()
        if m.paused:
            return "PAUSED"
        if m.status != "RUNNING":
            return m.status
        tasks = self.tasks()
        deps = self.deps()
        by_id = {t.id: t for t in tasks}
        failed = [t for t in tasks if t.status == "FAILED"]
        if failed:
            self._fail(f"task '{failed[0].key}' failed after {failed[0].attempt} attempt(s)")
            return "FAILED"
        ready = [t for t in tasks
                 if (t.status == "PENDING" and all(by_id[d].status in DONE for d in deps.get(t.id, ())))
                 or t.status == "RUNNING"]  # RUNNING here = resumed after approval
        if not ready:
            if any(t.status == "WAITING_FOR_APPROVAL" for t in tasks):
                with transaction() as conn:
                    ops.set_mission_status(conn, self.mission_id, "WAITING_FOR_APPROVAL")
                return "WAITING_FOR_APPROVAL"
            if all(t.status in TERMINAL_TASK for t in tasks):
                self._complete()
                return "COMPLETED"
            self._fail("no runnable tasks (dependency failed)")
            return "FAILED"
        pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix=f"m{self.mission_id[:4]}")
        try:
            futures = {pool.submit(self._run_task, t.id): t for t in ready}
            timeout = max(t.timeout_seconds for t in ready) + 30
            done, not_done = wait(futures, timeout=timeout)
            for f in not_done:
                t = futures[f]
                with transaction() as conn:
                    ops.set_task_status(conn, t.id, "FAILED", error=f"timed out after {t.timeout_seconds}s")
            for f in done:
                exc = f.exception()
                if isinstance(exc, Cancelled):
                    raise exc
                if exc:
                    log.exception("task crashed", exc_info=exc)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return "continue"

    # ---------------------------------------------------------------- one task
    def _run_task(self, task_id: str) -> None:
        with db.get_engine().connect() as conn:
            task = conn.execute(select(db.tasks).where(db.tasks.c.id == task_id)).first()
            agent = conn.execute(select(db.agents).where(db.agents.c.id == task.agent_id)).first()
        m = self.mission()
        mode = m.execution_mode
        lock = agent_lock(agent.id)
        resumed = task.status == "RUNNING"
        waited = 0.0
        while not lock.acquire(timeout=1.0):  # agent busy on another mission's task
            self.check_cancel()
            waited += 1
            if waited > task.timeout_seconds:
                with transaction() as conn:
                    ops.set_task_status(conn, task_id, "FAILED", error=f"{agent.name} stayed busy")
                return
        try:
            self.check_cancel()
            run_id = db.new_id()
            with transaction() as conn:
                if not resumed:
                    ops.set_task_status(conn, task_id, "RUNNING")
                run_no = conn.execute(select(func.count()).select_from(db.task_runs).where(db.task_runs.c.task_id == task_id)).scalar() + 1
                conn.execute(insert(db.task_runs).values(id=run_id, organization_id=m.organization_id, task_id=task_id,
                                                         attempt=run_no, status="RUNNING"))
                state = conn.execute(select(db.agents.c.execution_state).where(db.agents.c.id == agent.id)).scalar()
                if state != "WAITING_FOR_APPROVAL":
                    if state not in ("IDLE", "COMPLETED", "FAILED", "CANCELLED"):
                        ops.reset_agent(conn, agent.id, "reassigned after interruption")
                    ops.set_agent_state(conn, agent.id, "ASSIGNED", self.mission_id, mode)
                moving = ops.request_move(conn, agent.id, task.district, task.inputs.get("workstation"), self.mission_id, mode)
            if moving and self.settings.travel_seconds:
                time.sleep(self.settings.travel_seconds)  # cosmetic pacing so the world can animate the walk
            self.check_cancel()
            with transaction() as conn:
                if moving:
                    ops.arrive(conn, agent.id, task.district, task.inputs.get("workstation"), self.mission_id, mode)
                ops.set_agent_state(conn, agent.id, "EXECUTING", self.mission_id, mode)
                submit_report(conn, org_id=m.organization_id, agent_id=agent.id, kind="progress", body=f"Started: {task.title}",
                              mission_id=self.mission_id, task_id=task_id, mode=mode,
                              data={"attempt": task.attempt + (0 if resumed else 1), "estimate_s": task.timeout_seconds})

            env = TaskEnv(ToolContext(self.mission_id, task_id, agent.id, m.organization_id, mode), task, m, agent, self.gateway)
            outcome, outputs, error = "COMPLETED", None, None
            try:
                outputs = HANDLERS[task.key](env)
            except NeedsApproval as na:
                outcome, approval = "WAITING_FOR_APPROVAL", na
            except SkipTask as sk:
                outcome, outputs = "SKIPPED", {**sk.outputs, "reason": sk.reason}
            except VerificationFailed as vf:
                outcome, error = "VERIFY_FAILED", str(vf)
            except ops.BudgetExceeded as be:
                outcome, error = "BUDGET", str(be)
            except TaskError as te:
                outcome, error = "FAILED", str(te)
            self.check_cancel()

            with transaction() as conn:
                now = db.utcnow()
                rep = dict(org_id=m.organization_id, agent_id=agent.id, mission_id=self.mission_id, task_id=task_id, mode=mode)
                if outcome == "COMPLETED":
                    submit_report(conn, kind="completed_package", body=f"Done: {task.title}", data={"outputs_keys": sorted((outputs or {}).keys())}, **rep)
                    ops.set_task_status(conn, task_id, "COMPLETED", outputs=outputs)
                    ops.set_agent_state(conn, agent.id, "COMPLETED", self.mission_id, mode)
                    conn.execute(update(db.task_runs).where(db.task_runs.c.id == run_id).values(status="COMPLETED", finished_at=now))
                elif outcome == "SKIPPED":
                    ops.set_task_status(conn, task_id, "SKIPPED", outputs=outputs)
                    ops.set_agent_state(conn, agent.id, "COMPLETED", self.mission_id, mode)
                    conn.execute(update(db.task_runs).where(db.task_runs.c.id == run_id).values(status="COMPLETED", finished_at=now))
                elif outcome == "WAITING_FOR_APPROVAL":
                    ops.set_task_status(conn, task_id, "WAITING_FOR_APPROVAL")
                    ops.set_agent_state(conn, agent.id, "WAITING_FOR_APPROVAL", self.mission_id, mode)
                    conn.execute(update(db.task_runs).where(db.task_runs.c.id == run_id).values(status="COMPLETED", finished_at=now,
                                                                                                error="paused for approval"))
                    has = conn.execute(select(db.approvals.c.id).where(db.approvals.c.task_id == task_id,
                                                                       db.approvals.c.status == "PENDING")).first()
                    if not has:
                        aid = db.new_id()
                        conn.execute(insert(db.approvals).values(id=aid, organization_id=m.organization_id, mission_id=self.mission_id,
                                                                 task_id=task_id, action=approval.action, summary=approval.summary,
                                                                 status="PENDING"))
                        emit(conn, "approval.requested", mission_id=self.mission_id, agent_id=agent.id, execution_mode=mode,
                             payload={"approval_id": aid, "task_id": task_id, "action": approval.action, "summary": approval.summary})
                elif outcome == "BUDGET":
                    submit_report(conn, kind="resource_request", body=f"Budget reached on {task.title}: {error}", **rep)
                    conn.execute(update(db.task_runs).where(db.task_runs.c.id == run_id).values(status="FAILED", error=error, finished_at=now))
                    ops.set_task_status(conn, task_id, "PENDING", error=error)
                    ops.reset_agent(conn, agent.id, "budget suspension")
                    conn.execute(update(db.missions).where(db.missions.c.id == self.mission_id).values(paused=1, pause_reason=error))
                    emit(conn, "mission.status_changed", mission_id=self.mission_id, execution_mode=mode,
                         payload={"from": "RUNNING", "to": "RUNNING", "paused": True, "pause_reason": error, "suspended_by": "budget"})
                else:
                    # Reporting a failure is information for the supervisor, never a penalty for the agent.
                    submit_report(conn, kind="blocker" if outcome == "FAILED" else "quality_concern", body=f"{task.title}: {(error or '')[:300]}", **rep)
                    run_error = reliability.VERIFY_PREFIX + (error or "") if outcome == "VERIFY_FAILED" else error
                    conn.execute(update(db.task_runs).where(db.task_runs.c.id == run_id).values(status="FAILED", error=run_error, finished_at=now))
                    self._retry_or_fail(conn, task, error or "failed", outcome == "VERIFY_FAILED", agent.id, mode)
        finally:
            lock.release()

    def _retry_or_fail(self, conn, task, error: str, verify_failed: bool, agent_id: str, mode: str) -> None:
        cur = conn.execute(select(db.tasks).where(db.tasks.c.id == task.id)).first()
        repeated = reliability.repeating_failure(conn, task.id)
        if repeated:  # stall counter: the same failure twice in a row, so another identical retry would only burn budget
            from services.management.manager import record_decision
            loop_out = None
            if verify_failed:
                try:
                    loop_out = json.loads(error)
                except json.JSONDecodeError:
                    loop_out = {"output": error}
            ops.set_task_status(conn, task.id, "FAILED", outputs=loop_out,
                                error=f"{reliability.LOOP_PREFIX} {reliability.STALL_LIMIT} times: {reliability._short(repeated)}")
            ops.set_agent_state(conn, agent_id, "FAILED", self.mission_id, mode)
            record_decision(conn, decision_type="escalation", subject_type="task", subject_id=task.id, outcome="loop_stopped",
                            rationale=f"'{task.title}' failed the same way {reliability.STALL_LIMIT} times in a row "
                                      f"(\"{reliability._short(repeated)}\"). Retries stopped; it needs a different approach.",
                            event="manager.loop_detected", org_id=cur.organization_id)
            return
        if verify_failed:
            impl = conn.execute(select(db.tasks).where(db.tasks.c.mission_id == self.mission_id, db.tasks.c.key == "implement")).first()
            try:
                feedback = json.loads(error)
            except json.JSONDecodeError:
                feedback = {"output": error}
            if impl.attempt < impl.max_attempts:
                ops.set_task_status(conn, task.id, "PENDING", outputs=feedback, error="verification failed; sent back to developer")
                ops.set_task_status(conn, impl.id, "PENDING", error="re-opened by QA")
                ops.set_agent_state(conn, agent_id, "FAILED", self.mission_id, mode)
                return
            ops.set_task_status(conn, task.id, "FAILED", outputs=feedback, error="tests still failing after all attempts")
            ops.set_agent_state(conn, agent_id, "FAILED", self.mission_id, mode)
            return
        if cur.attempt < cur.max_attempts:
            ops.set_task_status(conn, task.id, "PENDING", error=f"retrying: {error}")
        else:
            ops.set_task_status(conn, task.id, "FAILED", error=error)
        ops.set_agent_state(conn, agent_id, "FAILED", self.mission_id, mode)

    # ---------------------------------------------------------------- endings
    def _send_agents_home(self, conn, mode: str) -> None:
        for a in conn.execute(select(db.agents)).fetchall():
            busy_elsewhere = conn.execute(select(db.tasks.c.id).where(db.tasks.c.agent_id == a.id, db.tasks.c.mission_id != self.mission_id,
                                                                      db.tasks.c.status.in_(["RUNNING", "WAITING_FOR_APPROVAL"]))).first()
            if busy_elsewhere:
                continue
            if a.execution_state != "IDLE":
                if a.execution_state in ("COMPLETED", "FAILED", "CANCELLED"):
                    ops.set_agent_state(conn, a.id, "IDLE", self.mission_id, mode)
                else:
                    ops.reset_agent(conn, a.id, "mission ended")
            pos = conn.execute(select(db.agent_positions).where(db.agent_positions.c.agent_id == a.id)).first()
            if pos and pos.district != a.home_district:
                ops.request_move(conn, a.id, a.home_district, None, self.mission_id, mode)
                ops.arrive(conn, a.id, a.home_district, None, self.mission_id, mode)

    def _complete(self) -> None:
        tasks = {t.key: t for t in self.tasks()}
        pub = tasks.get("publish")
        if pub is None:
            outcome = "completed"
        else:
            outcome = "published" if pub.status == "COMPLETED" else (
                "no_change" if (pub.outputs or {}).get("reason") == "no change to publish" else "not_published")
        with transaction() as conn:
            mode = ops.mission_row(conn, self.mission_id).execution_mode
            ops.set_mission_status(conn, self.mission_id, "COMPLETED", outcome=outcome)
            reliability.check_objective(conn, self.mission_id)
            reliability.learn_from_mission(conn, self.mission_id)
            self._send_agents_home(conn, mode)

    def _fail(self, reason: str) -> None:
        with transaction() as conn:
            m = ops.mission_row(conn, self.mission_id)
            if m.status in ("COMPLETED", "FAILED", "CANCELLED"):
                return
            for t in conn.execute(select(db.tasks).where(db.tasks.c.mission_id == self.mission_id,
                                                         db.tasks.c.status.in_(["PENDING", "WAITING_FOR_APPROVAL"]))).fetchall():
                ops.set_task_status(conn, t.id, "CANCELLED")
            conn.execute(update(db.approvals).where(db.approvals.c.mission_id == self.mission_id, db.approvals.c.status == "PENDING")
                         .values(status="EXPIRED", decided_at=db.utcnow()))
            if m.status in ("CREATED",):
                ops.set_mission_status(conn, self.mission_id, "CANCELLED", failure_reason=reason)
            else:
                ops.set_mission_status(conn, self.mission_id, "FAILED", failure_reason=reason)
            reliability.learn_from_mission(conn, self.mission_id)
            from services.management import recovery
            try:  # a proposal for you; nothing runs until you approve it. Never let drafting it undo the failure record
                with conn.begin_nested():
                    recovery.propose(conn, self.mission_id)
            except Exception:
                log.exception("could not draft a recovery plan for %s", self.mission_id)
            self._send_agents_home(conn, m.execution_mode)

    def _wind_down(self, reason: str) -> None:
        with transaction() as conn:
            m = ops.mission_row(conn, self.mission_id)
            for t in conn.execute(select(db.tasks).where(db.tasks.c.mission_id == self.mission_id)).fetchall():
                if t.status in ("PENDING", "RUNNING", "WAITING_FOR_APPROVAL"):
                    ops.set_task_status(conn, t.id, "CANCELLED")
            self._send_agents_home(conn, m.execution_mode)


def cancel_mission(mission_id: str, reason: str = "cancelled by operator") -> None:
    with transaction() as conn:
        m = ops.mission_row(conn, mission_id)
        if m is None or m.status in ("COMPLETED", "FAILED", "CANCELLED"):
            return
        conn.execute(update(db.approvals).where(db.approvals.c.mission_id == mission_id, db.approvals.c.status == "PENDING")
                     .values(status="EXPIRED", decided_at=db.utcnow()))
        ops.set_mission_status(conn, mission_id, "CANCELLED", failure_reason=reason)
        # tasks not owned by a live thread are wound down here; live threads see CANCELLED at their next check
        for t in conn.execute(select(db.tasks).where(db.tasks.c.mission_id == mission_id,
                                                     db.tasks.c.status.in_(["PENDING", "WAITING_FOR_APPROVAL"]))).fetchall():
            ops.set_task_status(conn, t.id, "CANCELLED")
            a = conn.execute(select(db.agents).where(db.agents.c.id == t.agent_id)).first()
            if a.execution_state == "WAITING_FOR_APPROVAL":
                ops.set_agent_state(conn, a.id, "CANCELLED", mission_id, m.execution_mode)
