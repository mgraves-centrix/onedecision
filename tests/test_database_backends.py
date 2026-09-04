"""Guarantees that only mean something on a real database.

SQLite has one writer, so its correctness under concurrency is an accident of
the file lock rather than a property of the code. These tests pin the behavior
that has to hold when several workers share one PostgreSQL instance.
"""

from __future__ import annotations

import threading

import pytest

from app import audit, db
from app.orchestrator import handle_event


# ------------------------------------------------------------------ portability


def test_both_backends_run_the_same_migrations(temp_db):
    applied = db.init_db()
    assert applied == []  # already applied by the seed fixture
    with db.read_only() as conn:
        versions = [r["version"] for r in conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()]
    assert versions == ["0001"]


def test_backend_is_reported_and_never_leaks_the_password(temp_db):
    description = db.describe()
    assert db.backend_name() in description
    assert "localdev" not in description
    if db.backend_name() == "postgres":
        assert ":***@" in description


def test_money_never_arrives_as_decimal(conn):
    """PostgreSQL NUMERIC must be coerced at the adapter boundary."""
    from app.adapters import parts_catalog
    from app.facts import derive_facts

    priced = parts_catalog.lookup_replacement_cost(conn, "CMP-STRAP-NEO")
    assert isinstance(priced["replacement_cost_usd"], float)
    assert priced["replacement_cost_usd"] == 14.00

    facts = derive_facts(conn, "CASE-2001")
    assert isinstance(facts.replacement_cost_usd, float)


def test_booleans_round_trip_as_booleans(conn):
    from app.adapters import returns_system

    case = returns_system.get_return_case(conn, "CASE-2005")
    assert case["new_damage_present"] is True
    components = returns_system.get_expected_components(conn, "NGO-KIT-4100")
    body = next(c for c in components if c["component_id"] == "CMP-BODY-4100")
    assert body["serialized"] is True
    assert body["safety_critical"] is False


# --------------------------------------------------------------- append-only


def test_audit_chain_head_is_unique(conn):
    """Two entries cannot claim the same predecessor.

    This is the constraint that makes a forked chain impossible rather than
    merely unlikely.
    """
    handle_event("CASE-2001", conn=conn)
    row = conn.execute(
        "SELECT prev_hash FROM audit_log ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    with pytest.raises(db.IntegrityError):
        conn.execute(
            """INSERT INTO audit_log (entry_id, trace_id, event_type, actor, payload,
                                      prev_hash, entry_hash, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("aud_forked", "trc_x", "test.fork", "attacker", "{}",
             row["prev_hash"], "deadbeef", "2026-01-01T00:00:00.000+00:00"),
        )


# ------------------------------------------------------------- concurrency


def test_concurrent_audit_appends_keep_the_chain_intact(postgres_only, temp_db):
    """Eight threads appending at once must produce one unbroken chain."""
    errors: list[Exception] = []

    def append(n: int) -> None:
        try:
            with db.session() as conn:
                audit.record(
                    conn,
                    trace_id=f"trc_concurrent_{n}",
                    event_type="test.concurrent_append",
                    actor="worker",
                    payload={"n": n},
                )
        except Exception as exc:  # collected so the assertion reports it
            errors.append(exc)

    threads = [threading.Thread(target=append, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    with db.read_only() as conn:
        chain = audit.verify_chain(conn)
        written = conn.execute(
            "SELECT COUNT(*) AS c FROM audit_log WHERE event_type = 'test.concurrent_append'"
        ).fetchone()["c"]
    assert written == 8
    assert chain.ok, chain.detail


def test_concurrent_duplicate_events_act_once(postgres_only, temp_db, approval_token):
    """The same event arriving on six workers must create one exception."""
    from app.orchestrator import activate_policy, approve_and_teach

    with db.session() as conn:
        first = handle_event("CASE-2001", conn=conn)
        teach = approve_and_teach(conn, first.exception_id, decided_by="tester")
        activate_policy(
            conn, teach.policy_id, approval_token=approval_token, activated_by="tester"
        )

    results: list[str] = []
    errors: list[Exception] = []

    def fire() -> None:
        try:
            result = handle_event("CASE-2002", event_key="evt-shared")
            results.append(result.exception_id)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=fire) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert len(set(results)) == 1, f"expected one exception, got {set(results)}"
    with db.read_only() as conn:
        work_orders = conn.execute(
            "SELECT COUNT(*) AS c FROM work_orders WHERE case_id = 'CASE-2002'"
        ).fetchone()["c"]
        exceptions = conn.execute(
            "SELECT COUNT(*) AS c FROM exceptions WHERE case_id = 'CASE-2002'"
        ).fetchone()["c"]
    assert work_orders == 1, "a duplicate event created a second work order"
    assert exceptions == 1


def test_idempotency_key_survives_concurrent_execution(postgres_only, temp_db):
    """The unique idempotency key is what actually stops a double write."""
    from app.adapters import warehouse

    errors: list[Exception] = []
    created: list[str] = []

    def create() -> None:
        try:
            with db.session() as conn:
                out = warehouse.create_work_order(
                    conn,
                    case_id="CASE-2002",
                    work_order_type="REPLACEMENT_PARTS",
                    component_id="CMP-CAP-BODY",
                    cost_usd=6.50,
                    max_cost_usd=25.0,
                    idempotency_key="fixed-key-for-this-test",
                )
                created.append(out["work_order_id"])
        except db.IntegrityError:
            pass  # the loser of the race; exactly what the constraint is for
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=create) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    with db.read_only() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM work_orders WHERE idempotency_key = ?",
            ("fixed-key-for-this-test",),
        ).fetchone()["c"]
    assert count == 1
    assert len(set(created)) <= 1
