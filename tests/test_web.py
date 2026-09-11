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


def test_every_page_links_a_versioned_stylesheet(client):
    # The version changes with app.css, so a browser fetches the new stylesheet
    # after an update instead of reusing a stale cached copy.
    for path in ("/", "/policies", "/dashboard"):
        assert "/static/app.css?v=" in client.get(path).text


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


def test_the_demo_token_is_discoverable_while_the_placeholder_is_in_use(
    client, monkeypatch
):
    """A judge must be able to finish the flow without reading the source.

    The hackathon requires the project to be usable "free of charge and without
    any restriction" for evaluation. An undocumented password field at the
    activation step is exactly such a restriction.
    """
    from app import config
    import app.main as main

    # The suite normally overrides the token; this test is about the shipped
    # default a judge would actually meet on a fresh clone.
    monkeypatch.setenv("ONEDECISION_APPROVAL_TOKEN", config.DEFAULT_APPROVAL_TOKEN)
    monkeypatch.setattr(main, "settings", config.reload_settings())

    r = client.post("/events/CASE-2001", follow_redirects=True)
    exception_id = r.url.path.rsplit("/", 1)[-1]
    r = client.post(f"/exceptions/{exception_id}/approve", follow_redirects=True)

    assert "Demo token:" in r.text
    assert config.DEFAULT_APPROVAL_TOKEN in r.text
    assert "ONEDECISION_APPROVAL_TOKEN" in r.text


def test_the_demo_token_hint_disappears_once_a_real_token_is_set(client, monkeypatch):
    """The hint is a demo affordance, not a credential leak."""
    from app import config
    import app.main as main

    r = client.post("/events/CASE-2001", follow_redirects=True)
    exception_id = r.url.path.rsplit("/", 1)[-1]

    monkeypatch.setenv("ONEDECISION_APPROVAL_TOKEN", "a-real-operator-secret")
    monkeypatch.setattr(main, "settings", config.reload_settings())

    r = client.post(f"/exceptions/{exception_id}/approve", follow_redirects=True)
    assert "Demo token:" not in r.text
    assert "a-real-operator-secret" not in r.text


# ------------------------------------------------------------ configuration


def test_dotenv_is_loaded_so_the_readme_instruction_works(tmp_path, monkeypatch):
    """The README tells a judge to copy .env.example to .env, so it must be read."""
    from app.config import load_dotenv

    env_file = tmp_path / ".env"
    env_file.write_text(
        "# a comment\n"
        "export ONEDECISION_TEST_PLAIN=plain\n"
        'ONEDECISION_TEST_QUOTED="has spaces"\n'
        "ONEDECISION_TEST_PRESET=from_file\n"
        "\n"
        "not-a-pair\n"
    )
    monkeypatch.setenv("ONEDECISION_TEST_PRESET", "from_environment")
    # Register the names as absent before the loader sets them, so teardown
    # removes them. Deleting them afterward would make monkeypatch record the
    # loaded values as the originals and restore them into the next test.
    for name in ("ONEDECISION_TEST_PLAIN", "ONEDECISION_TEST_QUOTED"):
        monkeypatch.delenv(name, raising=False)

    loaded = load_dotenv(env_file)

    import os

    assert os.environ["ONEDECISION_TEST_PLAIN"] == "plain"
    assert os.environ["ONEDECISION_TEST_QUOTED"] == "has spaces"
    # A real environment variable must win, so a stray file cannot override a
    # deployment's configuration.
    assert os.environ["ONEDECISION_TEST_PRESET"] == "from_environment"
    assert "ONEDECISION_TEST_PRESET" not in loaded
    # Names are returned, never values, so progress output cannot leak a secret.
    assert loaded == ["ONEDECISION_TEST_PLAIN", "ONEDECISION_TEST_QUOTED"]


def test_a_missing_dotenv_is_not_an_error(tmp_path):
    from app.config import load_dotenv

    assert load_dotenv(tmp_path / "does-not-exist") == []


def test_dotenv_is_gitignored():
    """A real .env must never be committable."""
    import subprocess

    from app.config import REPO_ROOT

    result = subprocess.run(
        ["git", "check-ignore", "-q", ".env"], cwd=REPO_ROOT, capture_output=True
    )
    assert result.returncode == 0, ".env is NOT gitignored"
