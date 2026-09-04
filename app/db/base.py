"""Backend-neutral database plumbing.

Application code writes one dialect of SQL — ANSI with `?` placeholders — and
this layer adapts it to whichever backend is configured. The point is not
portability for its own sake: it is that the *same* schema, the same
transactions, and the same tests run against SQLite (zero-setup demo) and
PostgreSQL (the real deployment target), so the two cannot drift.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Protocol, Sequence, runtime_checkable

Row = Mapping[str, Any]
Params = Sequence[Any] | Mapping[str, Any]


class DatabaseError(Exception):
    """Base class for backend-neutral database failures."""


class IntegrityError(DatabaseError):
    """A constraint or trigger rejected the write.

    Raised for unique-key violations and for the append-only audit triggers, so
    callers never have to know which backend produced the error.
    """


def to_pyformat(sql: str) -> str:
    """Rewrite `?` placeholders to `%s`, leaving quoted literals untouched.

    PostgreSQL drivers use pyformat parameters. Doing the rewrite here keeps a
    single dialect of SQL in the application, and skipping quoted strings means
    a `?` inside an error message can never be mistaken for a parameter.
    """
    out: list[str] = []
    in_single = in_double = False
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if in_single:
            if ch == "'":
                if i + 1 < n and sql[i + 1] == "'":
                    out.append("''")
                    i += 2
                    continue
                in_single = False
            out.append(ch)
        elif in_double:
            if ch == '"':
                in_double = False
            out.append(ch)
        elif ch == "'":
            in_single = True
            out.append(ch)
        elif ch == '"':
            in_double = True
            out.append(ch)
        elif ch == "?":
            out.append("%s")
        elif ch == "%":
            # A literal percent must be doubled once the statement carries
            # pyformat parameters.
            out.append("%%")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


@runtime_checkable
class Cursor(Protocol):
    def fetchone(self) -> Row | None: ...
    def fetchall(self) -> list[Row]: ...


@runtime_checkable
class Connection(Protocol):
    """The surface every backend must provide."""

    def execute(self, sql: str, params: Params = ()) -> Cursor: ...
    def executescript(self, sql: str) -> None: ...
    def begin(self) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...
    def lock_audit_chain(self) -> None: ...


@runtime_checkable
class Backend(Protocol):
    name: str

    def connect(self) -> Connection: ...
    def create_schema(self, conn: Connection) -> None: ...
    def drop_all(self) -> None: ...
    def describe(self) -> str: ...
    def shutdown(self) -> None: ...


def migration_files(directory, dialect: str) -> list[tuple[str, str]]:
    """Return `(version, sql)` for every migration for this dialect, in order."""
    out: list[tuple[str, str]] = []
    for path in sorted(directory.glob(f"*.{dialect}.sql")):
        version = path.name.split("_", 1)[0]
        out.append((version, path.read_text()))
    return out


def chunk_statements(script: str) -> list[str]:
    """Split a SQL script into statements.

    A naive split on `;` corrupts three things this schema actually contains:
    semicolons inside `--` comments, inside PL/pgSQL `$$ ... $$` bodies, and
    inside SQLite `CREATE TRIGGER ... BEGIN ... END;` bodies. This walks the
    script instead, tracking quotes, comments, dollar-quoting, and trigger-body
    nesting. Comments are dropped from the emitted statements.
    """
    statements: list[str] = []
    buf: list[str] = []
    i, n = 0, len(script)
    in_single = in_double = in_dollar = False
    in_line_comment = in_block_comment = False
    begin_depth = 0

    def in_trigger() -> bool:
        return "CREATE TRIGGER" in "".join(buf).upper()

    while i < n:
        ch = script[i]
        two = script[i : i + 2]

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
                buf.append(ch)
            i += 1
            continue
        if in_block_comment:
            if two == "*/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_single:
            buf.append(ch)
            if ch == "'":
                if script[i + 1 : i + 2] == "'":
                    buf.append("'")
                    i += 2
                    continue
                in_single = False
            i += 1
            continue
        if in_double:
            buf.append(ch)
            if ch == '"':
                in_double = False
            i += 1
            continue
        if in_dollar:
            if two == "$$":
                in_dollar = False
                buf.append("$$")
                i += 2
                continue
            buf.append(ch)
            i += 1
            continue

        if two == "--":
            in_line_comment = True
            i += 2
            continue
        if two == "/*":
            in_block_comment = True
            i += 2
            continue
        if two == "$$":
            in_dollar = True
            buf.append("$$")
            i += 2
            continue
        if ch == "'":
            in_single = True
            buf.append(ch)
            i += 1
            continue
        if ch == '"':
            in_double = True
            buf.append(ch)
            i += 1
            continue
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (script[j].isalnum() or script[j] == "_"):
                j += 1
            word = script[i:j]
            upper = word.upper()
            if upper == "BEGIN" and in_trigger():
                begin_depth += 1
            elif upper == "END" and begin_depth:
                begin_depth -= 1
            buf.append(word)
            i = j
            continue
        if ch == ";" and begin_depth == 0:
            statements.append("".join(buf).strip())
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return [s for s in statements if s]
