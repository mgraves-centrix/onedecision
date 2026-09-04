"""Database access.

One public surface, two backends:

* **postgres** — the deployment target. Selected by setting
  `ONEDECISION_DATABASE_URL`.
* **sqlite** — the zero-setup demo backend. The default, so the product runs
  from a fresh clone with no server and no credentials.

Application code never imports a driver. It calls `session()` / `read_only()`,
writes ANSI SQL with `?` placeholders, and reads rows as mappings. Both backends
run the same migrations and the same test suite, so they cannot quietly drift.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app import config
from app.db.base import (
    Backend,
    Connection,
    Cursor,
    DatabaseError,
    IntegrityError,
    Row,
    migration_files,
)
from app.db.postgres_backend import PostgresBackend
from app.db.sqlite_backend import SqliteBackend

__all__ = [
    "Connection",
    "Cursor",
    "DatabaseError",
    "IntegrityError",
    "Row",
    "backend",
    "backend_name",
    "connect",
    "describe",
    "drop_all",
    "init_db",
    "read_only",
    "reset_backend",
    "session",
]

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_backend: Backend | None = None
_backend_key: tuple | None = None
_lock = threading.Lock()


def _settings_key(settings) -> tuple:
    return (
        settings.database_url or "",
        str(settings.db_path),
        settings.db_pool_min_size,
        settings.db_pool_max_size,
    )


def backend() -> Backend:
    """The configured backend, rebuilt if the settings changed."""
    global _backend, _backend_key
    settings = config.get_settings()
    key = _settings_key(settings)
    with _lock:
        if _backend is None or _backend_key != key:
            if _backend is not None:
                _backend.shutdown()
            if settings.database_url:
                _backend = PostgresBackend(
                    settings.database_url,
                    min_size=settings.db_pool_min_size,
                    max_size=settings.db_pool_max_size,
                    connect_timeout=settings.db_connect_timeout_seconds,
                )
            else:
                _backend = SqliteBackend(settings.db_path)
            _backend_key = key
        return _backend


def reset_backend() -> None:
    """Drop the cached backend and release its pool. Used by tests and shutdown."""
    global _backend, _backend_key
    with _lock:
        if _backend is not None:
            _backend.shutdown()
        _backend = None
        _backend_key = None


def backend_name() -> str:
    return backend().name


def describe() -> str:
    return backend().describe()


def db_path() -> Path:
    """The SQLite file. Meaningless when PostgreSQL is configured."""
    return config.get_settings().db_path


def connect() -> Connection:
    return backend().connect()


# ------------------------------------------------------------------ migrations

MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TEXT NOT NULL
)
"""


def init_db() -> list[str]:
    """Apply every unapplied migration for the configured backend.

    Migrations are plain SQL, one file per version per dialect, applied in order
    and recorded in `schema_migrations`. Every statement in a version runs inside
    one transaction, so a failed migration leaves nothing half-applied.
    """
    from datetime import datetime, timezone

    active = backend()
    conn = active.connect()
    applied: list[str] = []
    try:
        conn.execute(MIGRATIONS_TABLE)
        conn.commit()
        done = {
            row["version"] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        for version, sql in migration_files(MIGRATIONS_DIR, active.name):
            if version in done:
                continue
            conn.begin()
            try:
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (version, datetime.now(timezone.utc).isoformat(timespec="seconds")),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            applied.append(version)
        return applied
    finally:
        conn.close()


def drop_all() -> None:
    """Destroy all local state. Only `seed --reset` and the tests call this."""
    backend().drop_all()


# ----------------------------------------------------------------- sessions


@contextmanager
def session() -> Iterator[Connection]:
    """A read-write transaction. Commits on success, rolls back on any error."""
    conn = connect()
    try:
        conn.begin()
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def read_only() -> Iterator[Connection]:
    """A connection for reads. Never commits."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
