"""The AgentCore Runtime entrypoint, invoked in-process with the offline provider."""

from __future__ import annotations

from app.agentcore import invoke


def test_invoke_accepts_a_case_id():
    result = invoke({"case_id": "CASE-2001"})

    assert "error" not in result
    assert result["case_id"] == "CASE-2001"


def test_invoke_finds_the_case_id_in_a_prompt():
    # The AgentCore SDK examples send {"prompt": "..."} rather than a case ID.
    result = invoke({"prompt": "Investigate case-2001, please"})

    assert "error" not in result
    assert result["case_id"] == "CASE-2001"


def test_invoke_without_a_case_is_an_error_not_a_crash():
    assert "error" in invoke({"prompt": "hello"})
    assert "error" in invoke({})
