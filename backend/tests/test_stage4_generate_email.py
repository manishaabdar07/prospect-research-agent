from __future__ import annotations

from datetime import datetime

from app.models import (
    Company,
    Finding,
    FindingSlot,
    Prospect,
    ProspectSource,
    ProspectStatus,
    RoleBucket,
    Seniority,
)
from app.stages.stage4_generate_email import generate_email

from ._fake_openai import FakeClient, FakeResponse, FakeToolCall

VALID_INPUT = {
    "subject": "Quick question about your new plant line",
    "body": "Hi -- saw you're expanding capacity. Congrats! Curious how you're handling X.",
    "claims_used": ["fd-1"],
    "disqualify": False,
    "disqualify_reason": None,
}


def _make_prospect_with_finding(db) -> Prospect:
    company = Company(company_id="co-1", name="Acme Co", domain=None, headcount=50, city="Pune", industry_raw="")
    db.add(company)
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
        ingested_at=datetime.utcnow(),
        status=ProspectStatus.RESEARCH_COMPLETED,
    )
    db.add(prospect)
    db.add(
        Finding(
            finding_id="fd-1",
            prospect_id="pr-1",
            slot=FindingSlot.WHAT_THEY_MAKE,
            claim="Acme makes widgets.",
            source_url="https://acme.example/about",
            retrieved_at=datetime.utcnow(),
            confidence=0.9,
        )
    )
    db.commit()
    return prospect


def test_generate_email_success(db_session):
    prospect = _make_prospect_with_finding(db_session)
    client = FakeClient([FakeResponse(tool_calls=[FakeToolCall("return_email", VALID_INPUT)])])

    outcome = generate_email(db_session, prospect, client=client)

    assert outcome.status == "DONE"
    assert outcome.draft is not None
    assert outcome.draft.subject == VALID_INPUT["subject"]
    assert client.chat.completions.calls == 1
    db_session.refresh(prospect)
    assert prospect.status == ProspectStatus.EMAIL_DRAFTED


def test_generate_email_self_disqualify(db_session):
    prospect = _make_prospect_with_finding(db_session)
    disqualify_input = {
        "subject": "",
        "body": "",
        "claims_used": [],
        "disqualify": True,
        "disqualify_reason": "Findings too thin.",
    }
    client = FakeClient([FakeResponse(tool_calls=[FakeToolCall("return_email", disqualify_input)])])

    outcome = generate_email(db_session, prospect, client=client)

    assert outcome.status == "DISQUALIFIED"
    assert outcome.draft.disqualify is True
    db_session.refresh(prospect)
    assert prospect.status == ProspectStatus.DISQUALIFIED


def test_generate_email_invalid_then_valid_on_retry(db_session):
    prospect = _make_prospect_with_finding(db_session)
    invalid_input = {**VALID_INPUT, "claims_used": ["fd-does-not-exist"]}
    client = FakeClient(
        [
            FakeResponse(tool_calls=[FakeToolCall("return_email", invalid_input, id_="call_1")]),
            FakeResponse(tool_calls=[FakeToolCall("return_email", VALID_INPUT, id_="call_2")]),
        ]
    )

    outcome = generate_email(db_session, prospect, client=client)

    assert client.chat.completions.calls == 2
    assert outcome.status == "DONE"
    db_session.refresh(prospect)
    assert prospect.status == ProspectStatus.EMAIL_DRAFTED


def test_generate_email_invalid_on_both_attempts_persists_flagged_draft(db_session):
    prospect = _make_prospect_with_finding(db_session)
    invalid_input = {**VALID_INPUT, "claims_used": ["fd-does-not-exist"]}
    client = FakeClient(
        [
            FakeResponse(tool_calls=[FakeToolCall("return_email", invalid_input, id_="call_1")]),
            FakeResponse(tool_calls=[FakeToolCall("return_email", invalid_input, id_="call_2")]),
        ]
    )

    outcome = generate_email(db_session, prospect, client=client)

    assert client.chat.completions.calls == 2
    assert outcome.status == "NEEDS_REVIEW"
    assert outcome.draft is not None
    assert outcome.draft.needs_human_review is True
    assert outcome.draft.claims_used == []  # unknown id filtered out, never persisted
    db_session.refresh(prospect)
    # There IS a draft worth a human looking at -- never silently dropped.
    assert prospect.status == ProspectStatus.EMAIL_DRAFTED


def test_generate_email_api_error_marks_prospect_error_with_no_draft(db_session):
    prospect = _make_prospect_with_finding(db_session)
    client = FakeClient([RuntimeError("connection reset")])

    outcome = generate_email(db_session, prospect, client=client)

    assert outcome.status == "ERROR"
    assert outcome.draft is None
    db_session.refresh(prospect)
    assert prospect.status == ProspectStatus.ERROR
    assert prospect.last_error is not None
    assert prospect.last_error_at is not None

    from app.models import EmailDraft

    assert db_session.get(EmailDraft, prospect.prospect_id) is None
