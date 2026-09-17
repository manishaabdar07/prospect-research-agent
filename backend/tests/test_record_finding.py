"""Unit tests for the single most important rule in the system:
record_finding MUST reject any source_url not fetched via `fetch` earlier in
the same agent session, via a tool_result error -- not an exception.

Exercised directly against app/agent/tools.py::handle_tool_call, with no
OpenAI API key and no network calls, by manipulating AgentSession state
the same way app/agent/loop.py would after a successful `fetch` call.
"""
from __future__ import annotations

from app.agent.tools import AgentSession, handle_tool_call


def test_record_finding_rejects_uncited_url():
    session = AgentSession()

    text, is_error = handle_tool_call(
        session,
        "record_finding",
        {
            "slot": "WHAT_THEY_MAKE",
            "claim": "They manufacture precision-machined automotive components.",
            "source_url": "https://example.com/about",
            "confidence": 0.8,
        },
    )

    assert is_error is True
    assert "fetch" in text.lower()
    assert session.findings == []  # nothing appended on rejection


def test_record_finding_accepts_previously_fetched_url():
    session = AgentSession()
    session.fetched_urls.add("https://example.com/about")

    text, is_error = handle_tool_call(
        session,
        "record_finding",
        {
            "slot": "WHAT_THEY_MAKE",
            "claim": "They manufacture precision-machined automotive components.",
            "source_url": "https://example.com/about",
            "confidence": 0.8,
        },
    )

    assert is_error is False
    assert len(session.findings) == 1
    assert session.findings[0].source_url == "https://example.com/about"


def test_record_finding_rejects_invalid_slot():
    session = AgentSession()
    session.fetched_urls.add("https://example.com/about")

    text, is_error = handle_tool_call(
        session,
        "record_finding",
        {
            "slot": "NOT_A_REAL_SLOT",
            "claim": "Something.",
            "source_url": "https://example.com/about",
            "confidence": 0.5,
        },
    )

    assert is_error is True
    assert session.findings == []


def test_record_finding_rejects_confidence_out_of_range():
    session = AgentSession()
    session.fetched_urls.add("https://example.com/about")

    text, is_error = handle_tool_call(
        session,
        "record_finding",
        {
            "slot": "HR_SIGNAL",
            "claim": "They are hiring.",
            "source_url": "https://example.com/about",
            "confidence": 1.5,
        },
    )

    assert is_error is True
    assert session.findings == []


def test_record_finding_rejects_overlong_claim():
    session = AgentSession()
    session.fetched_urls.add("https://example.com/about")
    long_claim = " ".join(["word"] * 50)

    text, is_error = handle_tool_call(
        session,
        "record_finding",
        {
            "slot": "CHANGE_SIGNAL",
            "claim": long_claim,
            "source_url": "https://example.com/about",
            "confidence": 0.5,
        },
    )

    assert is_error is True
    assert session.findings == []


def test_record_finding_does_not_leak_fetch_state_across_sessions():
    """A fresh AgentSession (i.e. a new research run) must not inherit a
    previous run's fetched URLs -- each run's citations must be grounded in
    that run's own fetches."""
    old_session = AgentSession()
    old_session.fetched_urls.add("https://example.com/about")

    new_session = AgentSession()
    text, is_error = handle_tool_call(
        new_session,
        "record_finding",
        {
            "slot": "WHAT_THEY_MAKE",
            "claim": "They manufacture things.",
            "source_url": "https://example.com/about",
            "confidence": 0.8,
        },
    )

    assert is_error is True
    assert new_session.findings == []


def test_fetch_tool_rejects_linkedin_urls():
    session = AgentSession()

    text, is_error = handle_tool_call(session, "fetch", {"url": "https://www.linkedin.com/in/someone"})

    assert is_error is True
    assert "linkedin" in text.lower()
    assert "https://www.linkedin.com/in/someone" not in session.fetched_urls
