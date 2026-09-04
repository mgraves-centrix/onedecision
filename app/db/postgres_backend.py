"""PostgreSQL backend — the deployment target.

What this backend adds beyond "the same tables somewhere else":

* **Correct concurrency for the audit chain.** Appending an entry means reading
  the current head hash and inserting a successor. With more than one writer
  that is a read-modify-write race, and a lost race forks the chain. A
  transaction-scoped advisory lock serializes appenders, and a `UNIQUE`
  constraint on `prev_hash` is the backstop if one ever slips through.
* **Atomic event de-duplication.** `INSERT ... ON CONFLICT DO NOTHING RETURNING`
  replaces the select-then-insert that only looked safe under a single writer.
* **Exact-decimal money.** `NUMERIC`, coerced to float at the adapter boundary so
  no `Decimal` leaks into the domain.
* **Pooling**, because a serverless runtime that opens a connection per
  invocation will exhaust a database long before it exhausts anything else.
"""

from __future__ import annotations

import logging
from typing import Any

from app.db.base import Cursor, IntegrityError, Params, Row, chunk_statements, to_pyformat

logger = logging.getLogger(__name__)

# Any 64-bit constant works; it only has to be stable across processes.
AUDIT_CHAIN_LOCK_KEY = 0x0D1_C1_5104

TABLES_IN_DROP_ORDER = (
    "audit_log",
    "decision_cards",
    "exceptions",
    "policies",
    "work_orders",
    "dispositions",
    "return_cases",
    "kit_components",
    "parts_catalog",
    "kit_catalog",
    "schema_migrations",
)


class PostgresCursor:
    def __init__(self, rows: list[Row] | None) -> None:
        self._rows = rows or []
        self._i = 0

    def fetchone(self) -> Row | None:
        if self._i >= len(self._rows):
            return None
        row = self._rows[self._i]
        self._i += 1
        return row

    def fetchall(self) -> list[Row]:
        rows = self._rows[self._i :]
        self._i = len(self._rows)
        return rows


class PostgresConnection:
    def __init__(self, raw: Any, backend: "PostgresBackend") -> None:
        self._raw = raw
        self._backend = backend

    def execute(self, sql: str, params: Params = ()) -> Cursor:
        import psycopg

        try:
            with self._raw.cursor() as cur:
                cur.execute(to_pyformat(sql), tuple(params) if params else None)
                rows = cur.fetchall() if cur.description else []
            return PostgresCursor(rows)
        except (psycopg.errors.IntegrityError, psycopg.errors.RaiseException) as exc:
            self._raw.rollback()
            raise IntegrityError(str(exc).strip()) from exc

    def executescript(self, sql: str) -> None:
        with self._raw.cursor() as cur:
            for statement in chunk_statements(sql):
                cur.execute(statement)

    def begin(self) -> None:
        """psycopg opens a transaction implicitly on first execute."""

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._backend.release(self._raw)

    def lock_audit_chain(self) -> None:
        """Serialize audit appenders for the rest of this transaction."""
        with self._raw.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (AUDIT_CHAIN_LOCK_KEY,))


class PostgresBackend:
    name = "postgres"

    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 10,
                 connect_timeout: int = 10, application_name: str = "onedecision") -> None:
        self.dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._connect_timeout = connect_timeout
        self._application_name = application_name
        self._pool: Any | None = None

    # ------------------------------------------------------------------ pool
    def _ensure_pool(self) -> Any:
        if self._pool is None:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool

            self._pool = ConnectionPool(
                conninfo=self.dsn,
                min_size=self._min_size,
                max_size=self._max_size,
                timeout=self._connect_timeout,
                kwargs={
                    "row_factory": dict_row,
                    "autocommit": False,
                    "application_name": self._application_name,
                },
                open=True,
                name="onedecision",
            )
            self._pool.wait(timeout=self._connect_timeout)
        return self._pool

    def connect(self) -> PostgresConnection:
        raw = self._ensure_pool().getconn()
        return PostgresConnection(raw, self)

    def release(self, raw: Any) -> None:
        if self._pool is not None:
            try:
                raw.rollback()
            except Exception:  # the connection is going back to the pool regardless
                logger.debug("rollback on release failed", exc_info=True)
            self._pool.putconn(raw)

    def shutdown(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    # ---------------------------------------------------------------- schema
    def drop_all(self) -> None:
        conn = self.connect()
        try:
            for table in TABLES_IN_DROP_ORDER:
                conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
            conn.execute("DROP FUNCTION IF EXISTS audit_log_append_only() CASCADE")
            conn.commit()
        finally:
            conn.close()

    def describe(self) -> str:
        redacted = self.dsn
        if "@" in redacted:
            head, tail = redacted.split("@", 1)
            scheme = head.split("://", 1)[0] if "://" in head else ""
            user = head.split("://", 1)[-1].split(":", 1)[0]
            redacted = f"{scheme}://{user}:***@{tail}"
        return f"postgres · {redacted} (pool {self._min_size}-{self._max_size})"

    def adapt(self, value: Any) -> Any:
        return value
