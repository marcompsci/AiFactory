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
                _engine = create_engine(url, pool_pre_ping=True)
        return _engine


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
    seed(engine)


def seed(engine: Engine) -> None:
    data = load_seed()
    org_id = data["organization_id"]
    settings = get_settings()
    with engine.begin() as conn:
        if conn.execute(select(organizations.c.id).where(organizations.c.id == org_id)).first():
            return
        conn.execute(insert(organizations).values(id=org_id, name="AI Civilization", daily_budget_usd=settings.daily_budget_usd))
        conn.execute(insert(projects).values(id=data["project_id"], organization_id=org_id, name="Sample project",
                                             allowed_tools=sorted({t for a in data["agents"] for t in a["tools"]})))
        conn.execute(insert(repositories).values(id="7e8f9a0b-1c2d-4e3f-8a9b-0c1d2e3f4a5b", organization_id=org_id,
                                                 project_id=data["project_id"], provider="local", full_name="sample/calc"))
        for a in data["agents"]:
            conn.execute(insert(agents).values(
                id=a["id"], organization_id=org_id, key=a["key"], name=a["name"], role=a["role"],
                home_district=a["home_district"], avatar=a["avatar"], model_provider=a["model"]["provider"],
                model_name=a["model"]["model"], max_usd_per_mission=a["limits"]["max_usd_per_mission"],
                max_concurrent_tasks=a["limits"]["max_concurrent_tasks"],
            ))
            for t in a["tools"]:
                conn.execute(insert(agent_capabilities).values(agent_id=a["id"], tool_name=t))
            conn.execute(insert(agent_positions).values(agent_id=a["id"], organization_id=org_id, district=a["home_district"]))
