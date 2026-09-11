"""The request each hosted model provider would send.

Both hosted providers are otherwise exercised only by the opt-in live test, so a
malformed request went unnoticed until someone ran it against a real endpoint.
These build the request locally: no network, no credentials, no spend.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.agent.providers import resolve_model
from app.config import get_settings

MESSAGES = [{"role": "user", "content": [{"text": "hello"}]}]


def _settings(provider: str):
    return dataclasses.replace(get_settings(), model_provider=provider)


def test_anthropic_request_has_max_tokens_and_no_temperature(monkeypatch):
    pytest.importorskip("anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    model = resolve_model(_settings("anthropic"))

    request = model.format_request(MESSAGES)

    assert request["max_tokens"] == 2048
    assert "temperature" not in request


def test_bedrock_request_has_no_temperature():
    model = resolve_model(_settings("bedrock"))

    request = model.format_request(MESSAGES)

    assert "temperature" not in request["inferenceConfig"]
