from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent.loop import AgentRunResult
from app.database import Base
from app.models import Company, Prospect, ProspectSource, ProspectStatus, RoleBucket, Seniority
from app.stages import stage3_agent


def _seed(session, *, prospect_id="pr-1") -> None:
    company = Company(company_id="co-1", name="Acme Co", domain=None, headcount=50, city="Pune", industry_raw="")
    session.add(company)
    prospect = Prospect(
        prospect_id=prospect_id,
        company_id="co-1",
        full_name="Jane Doe",
        title_raw="IT Manager",
        role_bucket=RoleBucket.IT,
        seniority=Seniority.OTHER,
        linkedin_url=None,
        email="jane@acme.example",
        source=ProspectSource.csv,
        ingested_at=datetime.utcnow(),
        status=ProspectStatus.QUALIFIED,
    )
    session.add(prospect)
    session.commit()


def test_run_research_job_crash_sets_error_not_disqualified(monkeypatch, tmp_path):
    """run_research_job's own DB session is independent of the test's
    db_session fixture (it opens its own SessionLocal()), so this test points
    the whole app at a throwaway sqlite file instead."""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    monkeypatch.setattr(stage3_agent, "SessionLocal", TestSessionLocal)

    session = TestSessionLocal()
    try:
        _seed(session)
    finally:
        session.close()

    with patch("app.stages.stage3_agent.run_research_agent", side_effect=RuntimeError("llm call failed")):
        stage3_agent.run_research_job("pr-1")

    session = TestSessionLocal()
    try:
        prospect = session.get(Prospect, "pr-1")
        assert prospect.status == ProspectStatus.ERROR
        assert prospect.last_error is not None
        assert "llm call failed" in prospect.last_error
        assert prospect.last_error_at is not None
    finally:
        session.close()
        engine.dispose()


def test_run_research_job_agent_error_exit_sets_error_not_disqualified(monkeypatch, tmp_path):
    """The agent loop itself can conclude terminal_reason=ERROR (e.g. too
    many consecutive tool errors, such as a target site blocking every fetch
    with 403s) while still returning normally (no exception) with
    hook_strength=0. That's a system failure, not a business judgment that
    this prospect is a bad fit -- it must land on ERROR (visible, retryable),
    not silently look identical to a real 'no hook found' DISQUALIFIED."""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    monkeypatch.setattr(stage3_agent, "SessionLocal", TestSessionLocal)

    session = TestSessionLocal()
    try:
        _seed(session)
    finally:
        session.close()

    fake_result = AgentRunResult(
        findings=[],
        hook_strength=0,
        terminal_reason="ERROR",
        agent_notes="Stopped: too many consecutive tool errors.",
        tool_calls_used=7,
    )
    with patch("app.stages.stage3_agent.run_research_agent", return_value=fake_result):
        stage3_agent.run_research_job("pr-1")

    session = TestSessionLocal()
    try:
        prospect = session.get(Prospect, "pr-1")
        assert prospect.status == ProspectStatus.ERROR
        assert prospect.last_error == "Stopped: too many consecutive tool errors."
        assert prospect.last_error_at is not None
    finally:
        session.close()
        engine.dispose()


def test_run_research_job_no_hook_found_still_sets_disqualified(monkeypatch, tmp_path):
    """A clean business conclusion that there's no usable hook (terminal_reason
    NO_HOOK or BUDGET_EXHAUSTED, not ERROR) must still route to DISQUALIFIED,
    unaffected by the ERROR-vs-DISQUALIFIED distinction above."""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    monkeypatch.setattr(stage3_agent, "SessionLocal", TestSessionLocal)

    session = TestSessionLocal()
    try:
        _seed(session)
    finally:
        session.close()

    fake_result = AgentRunResult(
        findings=[], hook_strength=0, terminal_reason="NO_HOOK",
        agent_notes="Concluded no usable hook.", tool_calls_used=5,
    )
    with patch("app.stages.stage3_agent.run_research_agent", return_value=fake_result):
        stage3_agent.run_research_job("pr-1")

    session = TestSessionLocal()
    try:
        prospect = session.get(Prospect, "pr-1")
        assert prospect.status == ProspectStatus.DISQUALIFIED
        assert prospect.last_error is None
    finally:
        session.close()
        engine.dispose()
