"""Database access.

Production: PostgreSQL (Supabase) with infrastructure/migrations/0001_init.sql applied — set DATABASE_URL.
Local dev and tests: SQLite file under .data/, created from the portable table definitions below.
The column names match the Postgres migration so the same queries run on both.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    insert,
    select,
)
from sqlalchemy.engine import Engine

from .config import get_settings, load_seed

metadata = MetaData()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def _ts() -> list[Column]:
    return [Column("created_at", String, nullable=False, default=utcnow), Column("updated_at", String, nullable=False, default=utcnow, onupdate=utcnow)]


organizations = Table(
    "organizations", metadata,
    Column("id", String(36), primary_key=True),
    Column("name", String, nullable=False),
    Column("daily_budget_usd", Float, nullable=False, default=5.0),
    Column("emergency_stopped", Integer, nullable=False, default=0),
    *_ts(),
)

projects = Table(
    "projects", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("name", String, nullable=False),
    Column("allowed_tools", JSON, nullable=False, default=list),
    Column("created_at", String, nullable=False, default=utcnow),
)

repositories = Table(
    "repositories", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("project_id", String(36), nullable=False),
    Column("provider", String, nullable=False),
    Column("full_name", String, nullable=False),
    Column("default_branch", String, nullable=False, default="main"),
    Column("created_at", String, nullable=False, default=utcnow),
)

agents = Table(
    "agents", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("key", String, nullable=False),
    Column("name", String, nullable=False),
    Column("role", String, nullable=False),
    Column("home_district", String, nullable=False),
    Column("avatar", JSON, nullable=False, default=dict),
    Column("model_provider", String, nullable=False),
    Column("model_name", String, nullable=False),
    Column("execution_state", String, nullable=False, default="IDLE"),
    Column("max_usd_per_mission", Float, nullable=False, default=0.5),
    Column("max_concurrent_tasks", Integer, nullable=False, default=1),
    Column("department_id", String(36)),
    Column("tier", String, nullable=False, default="specialist"),
    *_ts(),
    UniqueConstraint("organization_id", "key"),
)

agent_capabilities = Table(
    "agent_capabilities", metadata,
    Column("agent_id", String(36), primary_key=True),
    Column("tool_name", String, primary_key=True),
)

agent_positions = Table(
    "agent_positions", metadata,
    Column("agent_id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("district", String, nullable=False),
    Column("waypoint", String),
    Column("movement_state", String, nullable=False, default="STATIONARY"),
    Column("updated_at", String, nullable=False, default=utcnow, onupdate=utcnow),
)

missions = Table(
    "missions", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("project_id", String(36), nullable=False),
    Column("repository_id", String(36)),
    Column("title", String, nullable=False),
    Column("prompt", Text, nullable=False),
    Column("status", String, nullable=False),
    Column("execution_mode", String, nullable=False),
    Column("budget_usd", Float, nullable=False, default=1.0),
    Column("spent_usd_estimated", Float, nullable=False, default=0.0),
    Column("idempotency_key", String),
    Column("failure_reason", Text),
    Column("outcome", String),
    Column("paused", Integer, nullable=False, default=0),
    Column("pause_reason", Text),
    Column("kind", String, nullable=False, default="fix_failing_test"),
    Column("opportunity_id", String(36)),
    Column("params", JSON, nullable=False, default=dict),
    Column("created_by", String(36)),
    *_ts(),
    UniqueConstraint("organization_id", "idempotency_key"),
)

tasks = Table(
    "tasks", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("mission_id", String(36), nullable=False, index=True),
    Column("agent_id", String(36), nullable=False),
    Column("key", String, nullable=False),
    Column("title", String, nullable=False),
    Column("district", String, nullable=False),
    Column("status", String, nullable=False, default="PENDING"),
    Column("inputs", JSON, nullable=False, default=dict),
    Column("permitted_tools", JSON, nullable=False, default=list),
    Column("expected_outputs", JSON, nullable=False, default=dict),
    Column("validation", JSON, nullable=False, default=dict),
    Column("outputs", JSON),
    Column("attempt", Integer, nullable=False, default=0),
    Column("max_attempts", Integer, nullable=False, default=2),
    Column("timeout_seconds", Integer, nullable=False, default=120),
    Column("ordinal", Integer, nullable=False),
    *_ts(),
    UniqueConstraint("mission_id", "key"),
)

task_dependencies = Table(
    "task_dependencies", metadata,
    Column("task_id", String(36), primary_key=True),
    Column("depends_on_task_id", String(36), primary_key=True),
)

task_runs = Table(
    "task_runs", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("task_id", String(36), nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("status", String, nullable=False),
    Column("error", Text),
    Column("started_at", String, nullable=False, default=utcnow),
    Column("finished_at", String),
    UniqueConstraint("task_id", "attempt"),
)

agent_messages = Table(
    "agent_messages", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("mission_id", String(36)),
    Column("from_agent_id", String(36)),
    Column("to_agent_id", String(36)),
    Column("kind", String, nullable=False),
    Column("body", Text, nullable=False),
    Column("created_at", String, nullable=False, default=utcnow),
)

events = Table(
    "events", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("sequence", Integer, nullable=False),
    Column("mission_id", String(36), index=True),
    Column("agent_id", String(36)),
    Column("event_type", String, nullable=False),
    Column("schema_version", Integer, nullable=False, default=1),
    Column("correlation_id", String(36), nullable=False),
    Column("execution_mode", String, nullable=False, default="live"),
    Column("payload", JSON, nullable=False, default=dict),
    Column("occurred_at", String, nullable=False, default=utcnow),
    UniqueConstraint("organization_id", "sequence"),
)

event_outbox = Table(
    "event_outbox", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_id", String(36), nullable=False, unique=True),
    Column("organization_id", String(36), nullable=False),
    Column("published_at", String),
    Column("attempts", Integer, nullable=False, default=0),
    Column("last_error", Text),
    Column("created_at", String, nullable=False, default=utcnow),
)

approvals = Table(
    "approvals", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("mission_id", String(36), nullable=False),
    Column("task_id", String(36), nullable=False),
    Column("action", String, nullable=False),
    Column("summary", Text, nullable=False),
    Column("status", String, nullable=False, default="PENDING"),
    Column("decided_by", String(36)),
    Column("decided_at", String),
    Column("created_at", String, nullable=False, default=utcnow),
)

artifacts = Table(
    "artifacts", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("mission_id", String(36)),
    Column("task_id", String(36)),
    Column("agent_id", String(36)),
    Column("kind", String, nullable=False),
    Column("title", String, nullable=False),
    Column("content", Text, nullable=False),
    Column("storage_path", String),
    Column("digest", String),
    Column("opportunity_id", String(36)),
    Column("created_at", String, nullable=False, default=utcnow),
)

tool_executions = Table(
    "tool_executions", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("mission_id", String(36)),
    Column("task_id", String(36)),
    Column("agent_id", String(36), nullable=False),
    Column("tool_name", String, nullable=False),
    Column("arguments", JSON, nullable=False, default=dict),
    Column("status", String, nullable=False),
    Column("exit_code", Integer),
    Column("output_excerpt", Text),
    Column("duration_ms", Integer),
    Column("started_at", String, nullable=False, default=utcnow),
    Column("finished_at", String),
)

usage_records = Table(
    "usage_records", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("mission_id", String(36)),
    Column("agent_id", String(36)),
    Column("provider", String, nullable=False),
    Column("model", String, nullable=False),
    Column("input_tokens", Integer, nullable=False, default=0),
    Column("output_tokens", Integer, nullable=False, default=0),
    Column("estimated_cost_usd", Float, nullable=False, default=0.0),
    Column("provider_reported_cost_usd", Float),
    Column("created_at", String, nullable=False, default=utcnow),
)

memory_entries = Table(
    "memory_entries", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("scope", String, nullable=False),
    Column("mission_id", String(36)),
    Column("agent_id", String(36)),
    Column("trust", String, nullable=False),
    Column("content", Text, nullable=False),
    Column("source", String, nullable=False),
    Column("expires_at", String),
    Column("created_at", String, nullable=False, default=utcnow),
)

# ---------------------------------------------------------------- V4: hierarchy, research, logistics, release
departments = Table(
    "departments", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("key", String, nullable=False),
    Column("name", String, nullable=False),
    Column("district", String, nullable=False),
    Column("supervisor_agent_id", String(36)),
    Column("daily_budget_usd", Float, nullable=False, default=2.0),
    Column("max_concurrent_missions", Integer, nullable=False, default=1),
    Column("created_at", String, nullable=False, default=utcnow),
    UniqueConstraint("organization_id", "key"),
)

agent_reporting_lines = Table(
    "agent_reporting_lines", metadata,
    Column("agent_id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("supervisor_agent_id", String(36)),  # null = reports to the owner
)

agent_reports = Table(
    "agent_reports", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("agent_id", String(36), nullable=False),
    Column("supervisor_agent_id", String(36)),
    Column("mission_id", String(36)),
    Column("task_id", String(36)),
    Column("kind", String, nullable=False),
    Column("body", Text, nullable=False),
    Column("data", JSON, nullable=False, default=dict),
    Column("created_at", String, nullable=False, default=utcnow),
)

manager_decisions = Table(
    "manager_decisions", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("manager_agent_id", String(36), nullable=False),
    Column("decision_type", String, nullable=False),
    Column("subject_type", String, nullable=False),
    Column("subject_id", String(36), nullable=False),
    Column("outcome", String, nullable=False),
    Column("rationale", Text, nullable=False),
    Column("method", String, nullable=False),
    Column("model", String),
    Column("inputs", JSON, nullable=False, default=dict),
    Column("created_at", String, nullable=False, default=utcnow),
)

goal_checkpoints = Table(
    "goal_checkpoints", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("mission_id", String(36), nullable=False),
    Column("status", String, nullable=False),
    Column("findings", JSON, nullable=False, default=list),
    Column("created_at", String, nullable=False, default=utcnow),
)

scheduled_jobs = Table(
    "scheduled_jobs", metadata,
    Column("key", String, primary_key=True),
    Column("interval_seconds", Integer, nullable=False),
    Column("last_run_at", String),
    Column("next_run_at", String, nullable=False, default=utcnow),
    Column("last_result", JSON),
)

market_sources = Table(
    "market_sources", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("key", String, nullable=False),
    Column("name", String, nullable=False),
    Column("access", String, nullable=False),
    Column("terms_url", String),
    Column("rate_limit_per_hour", Integer, nullable=False, default=60),
    Column("daily_query_limit", Integer, nullable=False, default=50),
    UniqueConstraint("organization_id", "key"),
)

research_runs = Table(
    "research_runs", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("source_id", String(36), nullable=False),
    Column("research_agent_id", String(36), nullable=False),
    Column("mission_id", String(36)),
    Column("query", Text, nullable=False),
    Column("query_hash", String, nullable=False, index=True),
    Column("region", String, nullable=False, default="US"),
    Column("status", String, nullable=False),
    Column("data_mode", String, nullable=False),
    Column("error", Text),
    Column("started_at", String, nullable=False, default=utcnow),
    Column("finished_at", String),
)

research_cache = Table(
    "research_cache", metadata,
    Column("key", String, primary_key=True),  # source:query_hash:region
    Column("payload", JSON, nullable=False),
    Column("data_mode", String, nullable=False),
    Column("fetched_at", String, nullable=False, default=utcnow),
    Column("expires_at", String, nullable=False),
)

research_findings = Table(
    "research_findings", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("run_id", String(36), nullable=False),
    Column("source_platform", String, nullable=False),
    Column("title", String, nullable=False),
    Column("summary", Text, nullable=False),
    Column("source_url", String, nullable=False),
    Column("collected_at", String, nullable=False),
    Column("geographic_scope", String, nullable=False),
    Column("data_coverage", String, nullable=False),
    Column("measurement_type", String, nullable=False),
    Column("metrics", JSON, nullable=False, default=dict),
    Column("confidence", String, nullable=False),
    Column("data_mode", String, nullable=False),
    Column("created_at", String, nullable=False, default=utcnow),
)

opportunities = Table(
    "opportunities", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("source_platform", String, nullable=False),
    Column("research_agent_id", String(36), nullable=False),
    Column("research_mission_id", String(36)),
    Column("title", String, nullable=False),
    Column("description", Text, nullable=False),
    Column("evidence", JSON, nullable=False, default=list),
    Column("confidence", String, nullable=False),
    Column("opportunity_score", Float, nullable=False),
    Column("proposed_department", String, nullable=False),
    Column("estimated_effort", String, nullable=False),
    Column("estimated_cost_usd", Float, nullable=False),
    Column("risk_flags", JSON, nullable=False, default=list),
    Column("artifact_references", JSON, nullable=False, default=list),
    Column("spec", JSON, nullable=False, default=dict),  # the approved mission specification (goal-drift baseline)
    Column("status", String, nullable=False),
    Column("data_mode", String, nullable=False),
    Column("production_mission_id", String(36)),
    Column("qa_mission_id", String(36)),
    Column("release_mission_id", String(36)),
    Column("release_artifact_id", String(36)),
    Column("revision_count", Integer, nullable=False, default=0),
    *_ts(),
)

opportunity_scores = Table(
    "opportunity_scores", metadata,
    Column("opportunity_id", String(36), primary_key=True),
    Column("component", String, primary_key=True),
    Column("score", Float, nullable=False),
    Column("weight", Float, nullable=False),
    Column("evidence", JSON, nullable=False, default=list),
)

logistics_nodes = Table(
    "logistics_nodes", metadata,
    Column("id", String, primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("kind", String, nullable=False),
    Column("district", String),
    Column("position", JSON, nullable=False),
)

logistics_routes = Table(
    "logistics_routes", metadata,
    Column("id", String, primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("from_node", String, nullable=False),
    Column("to_node", String, nullable=False),
    Column("length", Float, nullable=False),
    Column("status", String, nullable=False, default="UP"),
)

logistics_packages = Table(
    "logistics_packages", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("opportunity_id", String(36), index=True),
    Column("mission_id", String(36)),
    Column("task_id", String(36)),
    Column("package_type", String, nullable=False),
    Column("priority", Integer, nullable=False, default=5),
    Column("origin_district", String, nullable=False),
    Column("destination_district", String, nullable=False),
    Column("status", String, nullable=False),
    Column("route", JSON, nullable=False, default=list),
    Column("route_started_at", String),
    Column("eta", String),
    Column("current_node", String),
    Column("artifact_references", JSON, nullable=False, default=list),
    Column("attempts", Integer, nullable=False, default=0),
    Column("next_attempt_at", String),
    Column("dispatched_at", String),
    Column("delivered_at", String),
    Column("created_at", String, nullable=False, default=utcnow),
)

package_transitions = Table(
    "package_transitions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("package_id", String(36), nullable=False, index=True),
    Column("from_status", String),
    Column("to_status", String, nullable=False),
    Column("detail", JSON, nullable=False, default=dict),
    Column("created_at", String, nullable=False, default=utcnow),
)

manager_reviews = Table(
    "manager_reviews", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("opportunity_id", String(36), nullable=False),
    Column("artifact_id", String(36), nullable=False),
    Column("artifact_digest", String, nullable=False),
    Column("verdict", String, nullable=False),
    Column("summary", Text, nullable=False),
    Column("method", String, nullable=False),
    Column("model", String),
    Column("created_at", String, nullable=False, default=utcnow),
)

review_checklists = Table(
    "review_checklists", metadata,
    Column("id", String(36), primary_key=True),
    Column("review_id", String(36), nullable=False),
    Column("category", String, nullable=False),
    Column("status", String, nullable=False),
    Column("evidence", Text, nullable=False),
    UniqueConstraint("review_id", "category"),
)

owner_decisions = Table(
    "owner_decisions", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("opportunity_id", String(36), nullable=False),
    Column("manager_review_id", String(36), nullable=False),
    Column("artifact_id", String(36), nullable=False),
    Column("artifact_digest", String, nullable=False),
    Column("decision", String, nullable=False),
    Column("note", Text),
    Column("decided_by", String(36), nullable=False),
    Column("created_at", String, nullable=False, default=utcnow),
)

release_authorizations = Table(
    "release_authorizations", metadata,
    Column("id", String(36), primary_key=True),
    Column("organization_id", String(36), nullable=False),
    Column("opportunity_id", String(36), nullable=False),
    Column("owner_decision_id", String(36), nullable=False, unique=True),
    Column("artifact_id", String(36), nullable=False),
    Column("artifact_digest", String, nullable=False),
    Column("scope", String, nullable=False),
    Column("created_at", String, nullable=False, default=utcnow),
)

release_invalidations = Table(
    "release_invalidations", metadata,
    Column("id", String(36), primary_key=True),
    Column("authorization_id", String(36), nullable=False, index=True),
    Column("reason", Text, nullable=False),
    Column("observed_digest", String),
    Column("created_at", String, nullable=False, default=utcnow),
)

release_executions = Table(
    "release_executions", metadata,
    Column("id", String(36), primary_key=True),
    Column("authorization_id", String(36), nullable=False),
    Column("artifact_digest", String, nullable=False),
    Column("tool_execution_id", String(36)),
    Column("destination", String, nullable=False),
    Column("created_at", String, nullable=False, default=utcnow),
)

APPEND_ONLY_TABLES = ("owner_decisions", "release_authorizations", "release_invalidations")


_engine: Engine | None = None
_engine_lock = threading.Lock()
# Serializes event-sequence allocation inside one process. Postgres additionally enforces
# unique(organization_id, sequence), so a second process would fail loudly rather than reorder.
write_lock = threading.RLock()


def get_engine() -> Engine:
    global _engine
    with _engine_lock:
        if _engine is None:
            url = get_settings().db_url
            if url.startswith("sqlite"):
                _engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

                @event.listens_for(_engine, "connect")
                def _pragmas(dbapi_conn, _):  # pragma: no cover - trivial
                    cur = dbapi_conn.cursor()
                    cur.execute("PRAGMA journal_mode=WAL")
                    cur.execute("PRAGMA foreign_keys=ON")
                    cur.close()
            else:
                from sqlalchemy.engine.interfaces import BindTyping

                from .pg import configure_connection

                if url.startswith("postgresql://") or url.startswith("postgres://"):
                    url = "postgresql+psycopg://" + url.split("://", 1)[1]
                _engine = create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20)
                # Send parameters untyped so Postgres casts ISO strings / id strings to timestamptz / uuid columns.
                _engine.dialect.bind_typing = BindTyping.NONE
                event.listen(_engine, "connect", lambda dbapi_conn, _: configure_connection(dbapi_conn))
        return _engine


from contextlib import contextmanager


@contextmanager
def consistent_read():
    """A connection whose reads all see one point in time, so a snapshot and its event `sequence` agree.
    Postgres: a REPEATABLE READ, read-only transaction. SQLite: writers in this process are held off meanwhile."""
    engine = get_engine()
    if engine.dialect.name == "postgresql":
        with engine.connect().execution_options(isolation_level="REPEATABLE READ", postgresql_readonly=True) as conn:
            with conn.begin():
                yield conn
    else:
        with write_lock, engine.connect() as conn:
            yield conn


def reset_engine() -> None:
    """Tests only."""
    global _engine
    with _engine_lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None


def init_db() -> None:
    engine = get_engine()
    if engine.dialect.name == "sqlite":
        metadata.create_all(engine)
        with engine.begin() as conn:
            for t in APPEND_ONLY_TABLES:  # same guarantee as the Postgres triggers in 0002
                for op in ("UPDATE", "DELETE"):
                    conn.exec_driver_sql(
                        f"CREATE TRIGGER IF NOT EXISTS {t}_no_{op.lower()} BEFORE {op} ON {t} "
                        f"BEGIN SELECT RAISE(ABORT, '{t} is append-only'); END")
    else:
        from .pg import migrate

        migrate(engine)
    seed(engine)


MARKET_SOURCES = [
    ("apple_charts", "Apple public app charts (RSS)", "public", "https://rss.marketingtools.apple.com", 60, 50),
    ("etsy", "Etsy Open API v3", "api_key", "https://www.etsy.com/legal/api", 300, 100),
    ("depop", "Depop partner API", "partner", "https://depop.com/legal", 60, 50),
    ("app_store_connect", "App Store Connect (owner's apps)", "owner_authorized", "https://developer.apple.com/terms", 60, 50),
]


def _ensure(conn, table, key_cols: dict, values: dict) -> bool:
    q = select(*table.c).where(*[table.c[k] == v for k, v in key_cols.items()])
    if conn.execute(q).first():
        return False
    conn.execute(insert(table).values(**key_cols, **values))
    return True


def seed(engine: Engine) -> None:
    """Idempotent: safe on every start, and upgrades a V3 database with the V4 roster and network."""
    from sqlalchemy import update

    from services.logistics.graph import build

    from .config import load_districts

    data = load_seed()
    org_id = data["organization_id"]
    settings = get_settings()
    by_key = {a["key"]: a for a in data["agents"]}
    import os

    def model_of(a: dict) -> str:  # e.g. AICIV_MODEL_GENERAL_MANAGER=claude-opus-5-5 (verify identifiers against Anthropic's model list)
        return os.environ.get(f"AICIV_MODEL_{a['key'].upper()}", a["model"]["model"])
    with engine.begin() as conn:
        _ensure(conn, organizations, {"id": org_id}, {"name": "AI Civilization", "daily_budget_usd": settings.daily_budget_usd})
        all_tools = sorted({t for a in data["agents"] for t in a["tools"]})
        if not _ensure(conn, projects, {"id": data["project_id"]}, {"organization_id": org_id, "name": "Sample project", "allowed_tools": all_tools}):
            conn.execute(update(projects).where(projects.c.id == data["project_id"]).values(allowed_tools=all_tools))
        _ensure(conn, repositories, {"id": "7e8f9a0b-1c2d-4e3f-8a9b-0c1d2e3f4a5b"},
                {"organization_id": org_id, "project_id": data["project_id"], "provider": "local", "full_name": "sample/calc"})
        # Agents first (no department yet), then departments (whose supervisors are agents), then link them —
        # Postgres enforces both foreign keys.
        dept_ids = {dpt["key"]: str(uuid.uuid5(uuid.NAMESPACE_URL, f"aiciv:dept:{dpt['key']}")) for dpt in data.get("departments", [])}
        for a in data["agents"]:
            created = _ensure(conn, agents, {"id": a["id"]}, dict(
                organization_id=org_id, key=a["key"], name=a["name"], role=a["role"], home_district=a["home_district"],
                avatar=a["avatar"], model_provider=a["model"]["provider"], model_name=model_of(a),
                max_usd_per_mission=a["limits"]["max_usd_per_mission"], max_concurrent_tasks=a["limits"]["max_concurrent_tasks"],
                department_id=None, tier=a.get("tier", "specialist")))
            if not created:
                conn.execute(update(agents).where(agents.c.id == a["id"]).values(tier=a.get("tier", "specialist"), model_name=model_of(a)))
            for t in a["tools"]:
                _ensure(conn, agent_capabilities, {"agent_id": a["id"], "tool_name": t}, {})
            _ensure(conn, agent_positions, {"agent_id": a["id"]}, {"organization_id": org_id, "district": a["home_district"]})
        for dpt in data.get("departments", []):
            _ensure(conn, departments, {"id": dept_ids[dpt["key"]]}, {"organization_id": org_id, "key": dpt["key"], "name": dpt["name"],
                                                                     "district": dpt["district"], "supervisor_agent_id": by_key[dpt["supervisor"]]["id"],
                                                                     "daily_budget_usd": dpt["daily_budget_usd"]})
        for a in data["agents"]:
            conn.execute(update(agents).where(agents.c.id == a["id"]).values(department_id=dept_ids.get(a.get("department"))))
            sup = data.get("reporting", {}).get(a["key"])
            _ensure(conn, agent_reporting_lines, {"agent_id": a["id"]},
                    {"organization_id": org_id, "supervisor_agent_id": by_key[sup]["id"] if sup else None})
        for key, name, access, terms, rate, daily in MARKET_SOURCES:
            _ensure(conn, market_sources, {"organization_id": org_id, "key": key},
                    {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"aiciv:source:{key}")), "name": name, "access": access,
                     "terms_url": terms, "rate_limit_per_hour": rate, "daily_query_limit": daily})
        nodes, segs = build(load_districts())
        for n in nodes:  # geometry follows the district config; belt UP/DOWN status is preserved
            if not _ensure(conn, logistics_nodes, {"id": n.id}, {"organization_id": org_id, "kind": n.kind, "district": n.district,
                                                                "position": list(n.position)}):
                conn.execute(update(logistics_nodes).where(logistics_nodes.c.id == n.id).values(position=list(n.position)))
        wanted = {sg.id for sg in segs}
        conn.execute(logistics_routes.delete().where(logistics_routes.c.id.notin_(wanted)))
        for sg in segs:
            if not _ensure(conn, logistics_routes, {"id": sg.id}, {"organization_id": org_id, "from_node": sg.from_node,
                                                                  "to_node": sg.to_node, "length": sg.length, "status": "UP"}):
                conn.execute(update(logistics_routes).where(logistics_routes.c.id == sg.id).values(length=sg.length))
        for key, interval in (("supervisor", 15), ("logistics", 1), ("pipeline", 1)):
            _ensure(conn, scheduled_jobs, {"key": key}, {"interval_seconds": interval, "next_run_at": utcnow()})
