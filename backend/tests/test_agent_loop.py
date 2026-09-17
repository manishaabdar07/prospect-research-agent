"""Stage 3 loop mechanics, exercised against a fake OpenAI client.

Uses the REAL handle_tool_call() (citation-integrity rule included) so this
proves the OpenAI tool_calls <-> handle_tool_call wiring end-to-end, not just
the loop's own bookkeeping. Only true external dependencies (search/fetch)
are monkeypatched -- no real network call, ever.
"""
from __future__ import annotations

from app.agent import tools as agent_tools
from app.agent.loop import run_research_agent
from app.models import Company, Prospect, ProspectSource, RoleBucket, Seniority
from app.search import SearchResult

from ._fake_openai import FakeClient, FakeResponse, FakeToolCall


def _make_prospect_and_company() -> tuple[Prospect, Company]:
    company = Company(
        company_id="co-1", name="Acme Co", domain=None, headcount=50, city="Pune", industry_raw="manufacturing"
    )
    prospect = Prospect(
        prospect_id="pr-1",
        company_id="co-1",
        full_name="Jane Doe",
        title_raw="IT Manager",
        role_bucket=RoleBucket.IT,
        seniority=Seniority.OTHER,
        linkedin_url=None,
        email="jane@acme.example",
        source=ProspectSource.csv,
    )
    return prospect, company


def test_run_research_agent_happy_path_via_tool_calls(monkeypatch):
    prospect, company = _make_prospect_and_company()

    monkeypatch.setattr(
        agent_tools,
        "run_search",
        lambda query: [SearchResult(title="Acme news", url="https://acme.example/news", snippet="Acme expands plant")],
    )
    monkeypatch.setattr(agent_tools, "fetch_and_extract", lambda url: "Acme is expanding its Pune plant this year.")

    client = FakeClient(
        [
            FakeResponse(tool_calls=[FakeToolCall("search", {"query": "Acme Co Pune"}, id_="call_1")]),
            FakeResponse(tool_calls=[FakeToolCall("fetch", {"url": "https://acme.example/news"}, id_="call_2")]),
            FakeResponse(
                tool_calls=[
                    FakeToolCall(
                        "record_finding",
                        {
                            "slot": "CHANGE_SIGNAL",
                            "claim": "Acme is expanding its Pune plant.",
                            "source_url": "https://acme.example/news",
                            "confidence": 0.8,
                        },
                        id_="call_3",
                    )
                ]
            ),
            FakeResponse(
                tool_calls=[
                    FakeToolCall(
                        "submit_findings",
                        {"hook_strength": 3, "terminal_reason": "SUFFICIENT", "notes": "Found a real expansion signal."},
                        id_="call_4",
                    )
                ]
            ),
        ]
    )

    result = run_research_agent(prospect, company, client=client)

    assert result.terminal_reason == "SUFFICIENT"
    assert result.hook_strength == 3
    assert len(result.findings) == 1
    assert result.findings[0].source_url == "https://acme.example/news"
    assert result.tool_calls_used == 4
    assert client.chat.completions.calls == 4


def test_run_research_agent_stops_on_consecutive_tool_errors():
    prospect, company = _make_prospect_and_company()

    def bad_finding_call(id_: str) -> FakeToolCall:
        # Citing a URL never fetched in this session -- a real, code-level
        # rejection (the citation-integrity rule in agent/tools.py), not a
        # scripted test double for an error.
        return FakeToolCall(
            "record_finding",
            {
                "slot": "CHANGE_SIGNAL",
                "claim": "Something.",
                "source_url": "https://never-fetched.example/",
                "confidence": 0.5,
            },
            id_=id_,
        )

    client = FakeClient(
        [
            FakeResponse(tool_calls=[bad_finding_call("call_1")]),
            FakeResponse(tool_calls=[bad_finding_call("call_2")]),
        ]
    )

    result = run_research_agent(prospect, company, client=client)

    assert result.terminal_reason == "ERROR"
    assert "consecutive" in result.agent_notes
    assert result.findings == []
    assert client.chat.completions.calls == 2
