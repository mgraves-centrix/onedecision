"""The in-memory progress channel behind the waiting page.

It exists so a long model call does not look like a hung app. It is advisory:
nothing here may affect what is decided, acted on, or recorded, so the tests
pin both the reporting and that boundary.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app import progress


@pytest.fixture()
def client(temp_db):
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_channel():
    progress.clear()
    yield
    progress.clear()


def test_unknown_key_reads_as_nothing():
    assert progress.read("nope") is None


def test_steps_accumulate_in_order_and_finish():
    progress.start("k", "Working", "Received")
    progress.step("k", "Reading the case")
    progress.step("k", "Pricing the part")
    progress.finish("k")

    state = progress.read("k")
    assert state["label"] == "Working"
    assert [s["text"] for s in state["steps"]] == ["Received", "Reading the case", "Pricing the part"]
    assert state["done"] is True
    assert state["elapsed"] >= 0


def test_a_repeated_step_is_not_repeated_on_screen():
    progress.start("k", "Working")
    progress.step("k", "Reading the case")
    progress.step("k", "Reading the case")
    assert len(progress.read("k")["steps"]) == 1


def test_steps_after_finish_are_dropped():
    progress.start("k", "Working")
    progress.finish("k")
    progress.step("k", "too late")
    assert progress.read("k")["steps"] == []


def test_a_missing_key_is_never_an_error():
    progress.step(None, "ignored")
    progress.finish(None)
    progress.tool_called(None, "get_return_case", ok=True)


def test_the_channel_stays_bounded():
    for i in range(progress.MAX_JOBS * 2):
        progress.start(f"k{i}", "Working")
    live = [i for i in range(progress.MAX_JOBS * 2) if progress.read(f"k{i}")]
    assert len(live) <= progress.MAX_JOBS
    # The survivors are the most recent ones.
    assert f"k{progress.MAX_JOBS * 2 - 1}" in {f"k{i}" for i in live}


def test_tool_calls_are_phrased_as_the_work_they_did():
    progress.start("k", "Working")
    progress.tool_called("k", "get_return_case", ok=True, summary="")
    progress.tool_called("k", "lookup_replacement_cost", ok=False, summary="boom")
    texts = [s["text"] for s in progress.read("k")["steps"]]
    assert texts == ["Reading the return case", "Pricing the missing part — failed"]


def test_an_unmapped_tool_still_reports_something_readable():
    progress.start("k", "Working")
    progress.tool_called("k", "some_new_tool", ok=True)
    assert progress.read("k")["steps"][0]["text"] == "some new tool"


# ------------------------------------------------------------------ over HTTP


def test_check_in_reports_the_steps_it_actually_took(client):
    client.post("/events/CASE-2001", follow_redirects=False)

    state = client.get("/progress/CASE-2001").json()
    assert state["done"] is True
    texts = [s["text"] for s in state["steps"]]
    assert texts[0] == "Check-in received at the dock"
    assert "Asking the agent to investigate" in texts
    assert "Reading the return case" in texts
    assert "Re-deriving every fact from the source systems" in texts
    assert "Running the hard guardrails" in texts


def test_approval_reports_the_steps_it_actually_took(client):
    r = client.post("/events/CASE-2001", follow_redirects=False)
    exception_id = r.headers["location"].rsplit("/", 1)[-1]

    client.post(f"/exceptions/{exception_id}/approve", follow_redirects=False)

    texts = [s["text"] for s in client.get(f"/progress/{exception_id}").json()["steps"]]
    assert texts[0] == "Recording your decision"
    assert "Asking the agent to draft the narrowest policy" in texts
    assert "Validating the draft against the policy schema" in texts
    assert "Replaying it against the labeled history" in texts


def test_an_unknown_key_polls_as_an_empty_wait(client):
    state = client.get("/progress/not-a-real-key").json()
    assert state == {"label": "", "elapsed": 0.0, "done": False, "steps": []}


def test_a_failed_run_still_closes_its_job(client):
    r = client.post("/exceptions/exc_missing/approve", follow_redirects=False)
    assert r.status_code == 400
    assert progress.read("exc_missing")["done"] is True


def test_the_slow_forms_declare_what_to_poll(client):
    assert 'data-wait="CASE-2001"' in client.get("/").text
    assert "/static/waiting.js?v=" in client.get("/").text

    r = client.post("/events/CASE-2001", follow_redirects=False)
    exception_id = r.headers["location"].rsplit("/", 1)[-1]
    assert f'data-wait="{exception_id}"' in client.get(f"/exceptions/{exception_id}").text


def test_resetting_the_demo_clears_the_channel(client):
    progress.start("leftover", "Working")
    client.post("/demo/reset", follow_redirects=False)
    assert progress.read("leftover") is None


def test_elapsed_stops_when_the_run_does():
    progress.start("k", "Working")
    progress.finish("k")
    first = progress.read("k")["elapsed"]
    time.sleep(0.05)
    assert progress.read("k")["elapsed"] == first


def test_approving_lands_on_what_it_produced(client):
    r = client.post("/events/CASE-2001", follow_redirects=False)
    exception_id = r.headers["location"].rsplit("/", 1)[-1]

    approved = client.post(f"/exceptions/{exception_id}/approve", follow_redirects=False)
    assert approved.headers["location"] == f"/exceptions/{exception_id}#candidate"

    # And the page has that section to land on.
    assert 'id="candidate"' in client.get(f"/exceptions/{exception_id}").text
