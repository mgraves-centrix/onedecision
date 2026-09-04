"""Test fixtures.

Every test runs against **both** database backends:

* `sqlite` — always, on a throwaway file.
* `postgres` — whenever `ONEDECISION_TEST_DATABASE_URL` points at a reachable
  server, on a schema dropped and rebuilt per test.

Running the identical suite against both is the point: the deployment target and
the zero-setup demo backend cannot drift without a test going red.

Everything here is hermetic — the deterministic `scripted` model provider, no
network to any model, no credentials. The one live-model test is marked
`integration` and is deselected by default.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Set before any app module reads settings.
os.environ.setdefault("ONEDECISION_MODEL_PROVIDER", "scripted")
os.environ.setdefault("ONEDECISION_APPROVAL_TOKEN", "test-approval-token")

TEST_DATABASE_URL = os.environ.get("ONEDECISION_TEST_DATABASE_URL", "").strip()


def _postgres_reachable(dsn: str) -> bool:
    if not dsn:
        return False
    try:
        import psycopg
    except ImportError:
        return False
    try:
        with psycopg.connect(dsn, connect_timeout=3):
            return True
    except Exception:
        return False


POSTGRES_AVAILABLE = _postgres_reachable(TEST_DATABASE_URL)

BACKENDS = ["sqlite"]
if POSTGRES_AVAILABLE:
    BACKENDS.append("postgres")


@pytest.fixture(params=BACKENDS, autouse=True, ids=lambda b: f"db={b}")
def temp_db(request, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the app at a throwaway database and seed it from the fixtures."""
    from app import config, db, seed

    monkeypatch.setenv("ONEDECISION_MODEL_PROVIDER", "scripted")
    monkeypatch.setenv("ONEDECISION_APPROVAL_TOKEN", "test-approval-token")

    if request.param == "postgres":
        monkeypatch.setenv("ONEDECISION_DATABASE_URL", TEST_DATABASE_URL)
        monkeypatch.setenv("ONEDECISION_DB_POOL_MAX", "4")
        target = TEST_DATABASE_URL
    else:
        monkeypatch.delenv("ONEDECISION_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        target = tmp_path / "onedecision.db"
        monkeypatch.setenv("ONEDECISION_DB_PATH", str(target))

    new_settings = config.reload_settings()

    import app.agent.providers as providers
    import app.config as config_module
    import app.policy.guardrails as guardrails
    import app.policy.store as store

    for module in (seed, providers, store, guardrails, config_module):
        monkeypatch.setattr(module, "settings", new_settings, raising=False)

    db.reset_backend()
    seed.seed(reset=True)
    try:
        yield target
    finally:
        if request.param == "postgres":
            db.drop_all()
        db.reset_backend()


@pytest.fixture()
def conn(temp_db):
    from app import db

    connection = db.connect()
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture()
def approval_token() -> str:
    return "test-approval-token"


@pytest.fixture()
def postgres_only(temp_db, request):
    """Skip on the demo backend for tests about real concurrency."""
    from app import db

    if db.backend_name() != "postgres":
        pytest.skip("PostgreSQL-only behavior")


DEMO_CONDITIONS = [
    {"field": "missing_component_count", "operator": "eq", "value": 1},
    {"field": "missing_component_serialized", "operator": "eq", "value": False},
    {"field": "missing_component_safety_critical", "operator": "eq", "value": False},
    {"field": "missing_component_essential", "operator": "eq", "value": False},
    {"field": "serial_match", "operator": "eq", "value": True},
    {"field": "new_damage_present", "operator": "eq", "value": False},
    {"field": "evidence_complete", "operator": "eq", "value": True},
    {"field": "replacement_cost_usd", "operator": "lte", "value": 25.0},
]

DEMO_ACTIONS = [
    {"type": "set_disposition", "disposition": "PARTS_HOLD"},
    {"type": "create_work_order", "work_order_type": "REPLACEMENT_PARTS", "max_cost_usd": 25.0},
    {"type": "close_exception", "resolution_code": "RESOLVED_PARTS_REPLACEMENT"},
]


def demo_policy_payload(**overrides) -> dict:
    payload = {
        "family": "returns.missing_accessory",
        "name": "Single low-cost accessory replacement",
        "description": "Exactly one cheap non-serialized accessory missing, everything else clean.",
        "conditions": [dict(c) for c in DEMO_CONDITIONS],
        "actions": [dict(a) for a in DEMO_ACTIONS],
        "min_confidence": 0.75,
    }
    payload.update(overrides)
    return payload


@pytest.fixture()
def policy_payload():
    return demo_policy_payload
