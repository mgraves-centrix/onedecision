"""Test fixtures.

Every test in this suite is hermetic: a fresh temporary SQLite database, the
deterministic `scripted` model provider, and no network. The one live-model
test is marked `integration` and is deselected by default.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Set before any app module reads settings.
os.environ.setdefault("ONEDECISION_MODEL_PROVIDER", "scripted")
os.environ.setdefault("ONEDECISION_APPROVAL_TOKEN", "test-approval-token")


@pytest.fixture(autouse=True)
def temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the app at a throwaway database and seed it from the fixtures."""
    from app import config, db, seed

    target = tmp_path / "onedecision.db"
    monkeypatch.setenv("ONEDECISION_DB_PATH", str(target))
    monkeypatch.setenv("ONEDECISION_MODEL_PROVIDER", "scripted")
    monkeypatch.setenv("ONEDECISION_APPROVAL_TOKEN", "test-approval-token")
    new_settings = config.reload_settings()

    import app.agent.providers as providers
    import app.config as config_module
    import app.policy.guardrails as guardrails
    import app.policy.store as store

    for module in (db, seed, providers, store, guardrails, config_module):
        monkeypatch.setattr(module, "settings", new_settings, raising=False)

    seed.seed(reset=True)
    yield target


@pytest.fixture()
def conn(temp_db):
    from app import db

    connection = db.connect(temp_db)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture()
def approval_token() -> str:
    return "test-approval-token"


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
