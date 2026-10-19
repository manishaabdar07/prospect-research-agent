from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from app.deps import require_email_configured
from app.main import app
from app.models import (
    Company,
    EmailDraft,
    EmailDraftStatus,
    Prospect,
    ProspectSource,
    ProspectStatus,
    RoleBucket,
    Seniority,
)


def _make_prospect(db, *, status, email="jane@acme.example", with_draft=True) -> Prospect:
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
        email=email,
        source=ProspectSource.csv,
        ingested_at=datetime.utcnow(),
        status=status,
    )
    db.add(prospect)
    if with_draft:
        db.add(
            EmailDraft(
                prospect_id="pr-1",
                subject="Quick question",
                body="Hello there",
                claims_used=["fd-1"],
                disqualify=False,
                status=EmailDraftStatus.DRAFTED,
            )
        )
    db.commit()
    return prospect


def _bypass_email_configured():
    app.dependency_overrides[require_email_configured] = lambda: None


def _restore_email_configured():
    app.dependency_overrides.pop(require_email_configured, None)


def test_send_email_400_when_not_drafted(client, db_session):
    _make_prospect(db_session, status=ProspectStatus.QUALIFIED, with_draft=False)
    _bypass_email_configured()
    try:
        resp = client.post("/api/prospects/pr-1/send-email")
    finally:
        _restore_email_configured()

    assert resp.status_code == 400


def test_send_email_400_when_recipient_blank(client, db_session):
    _make_prospect(db_session, status=ProspectStatus.EMAIL_DRAFTED, email=None)
    _bypass_email_configured()
    try:
        resp = client.post("/api/prospects/pr-1/send-email")
    finally:
        _restore_email_configured()

    assert resp.status_code == 400


def test_send_email_503_when_email_not_configured(client, db_session):
    _make_prospect(db_session, status=ProspectStatus.EMAIL_DRAFTED)
    # Deliberately do NOT bypass require_email_configured -- real dependency
    # runs against the actual (unconfigured-in-test-env) settings.
    resp = client.post("/api/prospects/pr-1/send-email")
    assert resp.status_code == 503


@patch("app.routers.prospects.get_email_service")
def test_send_email_success_updates_status_and_blocks_resend(mock_get_service, client, db_session):
    mock_service = mock_get_service.return_value
    _make_prospect(db_session, status=ProspectStatus.EMAIL_DRAFTED)
    _bypass_email_configured()
    try:
        resp = client.post("/api/prospects/pr-1/send-email")
        assert resp.status_code == 200
        assert resp.json()["status"] == "SENT"
        mock_service.send.assert_called_once_with(
            to="jane@acme.example", subject="Quick question", body="Hello there"
        )

        db_session.expire_all()
        prospect = db_session.get(Prospect, "pr-1")
        draft = db_session.get(EmailDraft, "pr-1")
        assert prospect.status == ProspectStatus.EMAIL_SENT
        assert draft.status == EmailDraftStatus.SENT
        assert draft.sent_at is not None

        # Resend attempt: status is no longer EMAIL_DRAFTED -> rejected.
        resp2 = client.post("/api/prospects/pr-1/send-email")
        assert resp2.status_code == 400
    finally:
        _restore_email_configured()
