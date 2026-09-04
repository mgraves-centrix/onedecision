"""SQLite backend — the zero-setup demo database.

Kept so a judge, a CI runner, or anyone cloning the repository can run the whole
product with no server, no credentials, and no container. It is explicitly a
*demo* backend: single-writer, file-local, and not what a deployment uses.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from app.db.base import Cursor, IntegrityError, Params, Row, chunk_statements


class SqliteCursor:
    def __init__(self, raw: sqlite3.Cursor) -> None:
        self._raw = raw

    def fetchone(self) -> Row | None:
        row = self._raw.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self) -> list[Row]:
        return [dict(r) for r in self._raw.fetchall()]


class SqliteConnection:
    def __init__(self, raw: sqlite3.Connection) -> None:
        self._raw = raw

    def execute(self, sql: str, params: Params = ()) -> Cursor:
        try:
            return SqliteCursor(self._raw.execute(sql, params))
        except sqlite3.IntegrityError as exc:
            raise IntegrityError(str(exc)) from exc

    def executescript(self, sql: str) -> None:
        for statement in chunk_statements(sql):
            self._raw.execute(statement)

    def begin(self) -> None:
        if not self._raw.in_transaction:
            self._raw.execute("BEGIN")

    def commit(self) -> None:
        # The connection runs in autocommit mode, so a statement outside an
        # explicit BEGIN has already been durable; committing again is an error.
        if self._raw.in_transaction:
            self._raw.execute("COMMIT")

    def rollback(self) -> None:
        if self._raw.in_transaction:
            self._raw.execute("ROLLBACK")

    def close(self) -> None:
        self._raw.close()

    def lock_audit_chain(self) -> None:
        """No-op: SQLite serializes writers at the file level already."""


class SqliteBackend:
    name = "sqlite"

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def connect(self) -> SqliteConnection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Strands runs tools on a worker thread, so the connection must cross
        # threads. CPython's sqlite3 is built in serialized mode
        # (sqlite3.threadsafety == 3), which makes this safe at the driver level.
        raw = sqlite3.connect(
            self.path, isolation_level=None, timeout=15.0, check_same_thread=False
        )
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys = ON")
        raw.execute("PRAGMA journal_mode = WAL")
        raw.execute("PRAGMA busy_timeout = 15000")
        return SqliteConnection(raw)

    def drop_all(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(self.path) + suffix)
            if candidate.exists():
                candidate.unlink()

    def describe(self) -> str:
        # Relative when the file lives in the repository, so the value is safe to
        # print into a committed report or a health endpoint.
        from app.config import REPO_ROOT

        try:
            shown = self.path.relative_to(REPO_ROOT)
        except ValueError:
            shown = self.path.name
        return f"sqlite · {shown} (demo backend, single writer)"

    def shutdown(self) -> None:
        """Nothing to release: connections are per-call, not pooled."""

    def adapt(self, value: Any) -> Any:
        return value
