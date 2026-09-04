"""The three views, and the HTTP-level guarantees around them."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(temp_db):
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_inbox_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Exception inbox" in r.text
    assert "CASE-2001" in r.text
    assert "fictional company" in r.text  # the synthetic banner is never hidden


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["audit_chain_ok"] is True


def test_check_in_produces_a_decision_card_view(client):
    r = client.post("/events/CASE-2001", follow_redirects=True)
    assert r.status_code == 200
    assert "Decision card" in r.text
    assert "Approve and teach" in r.text
    assert "Proposed boundaries" in r.text


def test_full_flow_through_the_ui(client, approval_token):
    from app import db
    from app.policy import store

    r = client.post("/events/CASE-2001", follow_redirects=True)
    exception_id = r.url.path.rsplit("/", 1)[-1]

    r = client.post(f"/exceptions/{exception_id}/approve", follow_redirects=True)
    assert r.status_code == 200
    assert "Proposed policy" in r.text
    assert "Replay against" in r.text

    with db.read_only() as conn:
        candidate = store.list_all(conn)[0]
    assert candidate.status == "candidate"

    # Wrong token: refused, and the policy stays inert.
    r = client.post(
        f"/policies/{candidate.policy_id}/activate", data={"approval_token": "wrong"}
    )
    assert r.status_code == 403
    with db.read_only() as conn:
        assert store.get(conn, candidate.policy_id).status == "candidate"

    # Right token: activated.
    r = client.post(
        f"/policies/{candidate.policy_id}/activate",
        data={"approval_token": approval_token},
        follow_redirects=True,
    )
    assert r.status_code == 200
    with db.read_only() as conn:
        assert store.get(conn, candidate.policy_id).status == "active"

    # The next matching case resolves without a decision card.
    r = client.post("/events/CASE-2002", follow_redirects=True)
    assert "Exception inbox" in r.text
    with db.read_only() as conn:
        row = conn.execute(
            "SELECT status FROM exceptions WHERE case_id = 'CASE-2002'"
        ).fetchone()
    assert row["status"] == "resolved"

    # The near-match still escalates.
    client.post("/events/CASE-2003", follow_redirects=True)
    with db.read_only() as conn:
        row = conn.execute(
            "SELECT status FROM exceptions WHERE case_id = 'CASE-2003'"
        ).fetchone()
    assert row["status"] == "escalated"


def test_policies_view_shows_versions_and_audit(client, approval_token):
    client.post("/events/CASE-2001", follow_redirects=True)
    r = client.get("/policies")
    assert r.status_code == 200
    assert "Audit log" in r.text
    assert "hash chain intact" in r.text


def test_reset_restores_the_fixtures(client):
    client.post("/events/CASE-2001", follow_redirects=True)
    from app import db

    with db.read_only() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM exceptions").fetchone()["c"] == 1

    r = client.post("/demo/reset", follow_redirects=True)
    assert r.status_code == 200
    with db.read_only() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM exceptions").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) c FROM return_cases").fetchone()["c"] == 30
