"""PostgreSQL (Supabase) support: migrations runner and value adapters.

The application code works with plain values everywhere — ids are strings, timestamps are ISO-8601 UTC strings,
money is float — because the same queries also run on SQLite locally. On Postgres the columns are real `uuid`,
`timestamptz` and `numeric` types (infrastructure/migrations). The adapters below make psycopg hand back the same
plain values, and parameters are sent untyped so Postgres casts them to the column type.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger("aiciv.pg")
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "infrastructure" / "migrations"


def configure_connection(dbapi_conn) -> None:
    """Called for every new pooled connection."""
    from psycopg.adapt import Loader
    from psycopg.types.datetime import TimestamptzLoader

    conn = getattr(dbapi_conn, "driver_connection", dbapi_conn)

    class UuidText(Loader):
        def load(self, data):
            return bytes(data).decode()

    class FloatFromNumeric(Loader):
        def load(self, data):
            return float(bytes(data).decode())

    class IsoTimestamptz(TimestamptzLoader):
        def load(self, data):
            return super().load(data).isoformat()

    conn.adapters.register_loader("uuid", UuidText)
    conn.adapters.register_loader("numeric", FloatFromNumeric)
    conn.adapters.register_loader("timestamptz", IsoTimestamptz)
    with conn.cursor() as cur:
        cur.execute("set time zone 'UTC'")
    if not conn.autocommit:
        conn.commit()


def migration_files() -> list[Path]:
    return sorted(p for p in MIGRATIONS_DIR.glob("*.sql") if re.match(r"^\d{4}_", p.name))


def migrate(engine) -> list[str]:
    """Apply infrastructure/migrations/*.sql in order, once each, recorded in schema_migrations.

    Pending files apply in one transaction (all or nothing); an advisory lock keeps two API processes from
    migrating at once.
    """
    applied_now: list[str] = []
    with engine.begin() as conn:
        conn.exec_driver_sql("select pg_advisory_xact_lock(724242)")
        conn.exec_driver_sql(
            "create table if not exists schema_migrations (version text primary key, applied_at timestamptz not null default now())")
        done = {r[0] for r in conn.exec_driver_sql("select version from schema_migrations")}
        for path in migration_files():
            version = path.stem
            if version in done:
                continue
            log.info("applying migration %s", path.name)
            raw = conn.connection.driver_connection
            with raw.cursor() as cur:
                cur.execute(path.read_text())  # psycopg runs a multi-statement script when it has no parameters
            conn.exec_driver_sql("insert into schema_migrations (version) values (%(v)s)", {"v": version})
            applied_now.append(version)
    return applied_now


def truncate_all(engine) -> None:
    """Tests only: empty every application table (TRUNCATE does not fire the append-only row triggers)."""
    with engine.begin() as conn:
        names = [r[0] for r in conn.exec_driver_sql(
            "select tablename from pg_tables where schemaname = 'public' and tablename not in ('schema_migrations', 'checkpoint_migrations')")]
        if names:
            conn.exec_driver_sql("truncate " + ", ".join(f'"{n}"' for n in names) + " restart identity cascade")
