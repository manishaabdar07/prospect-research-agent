from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Company, Prospect, ProspectSource, ProspectStatus, RoleBucket, Seniority
from app.stages import pipeline_runner


class FakeBackgroundTasks:
    def __init__(self) -> None:
        self.scheduled: list[tuple] = []

    def add_task(self, func, *args, **kwargs) -> None:
        self.scheduled.append((func, args, kwargs))


def _make_prospect(
    db, prospect_id: str, company_id: str, *, headcount=50, city="Pune", status=ProspectStatus.INGESTED
) -> Prospect:
    if db.get(Company, company_id) is None:
        db.add(Company(company_id=company_id, name=company_id, domain=None, headcount=headcount, city=city, industry_raw=""))
    prospect = Prospect(
        prospect_id=prospect_id,
        company_id=company_id,
        full_name=f"Person {prospect_id}",
        title_raw="IT Manager",
        role_bucket=RoleBucket.IT,
        seniority=Seniority.OTHER,
        linkedin_url=None,
        email=None,
        source=ProspectSource.csv,
        ingested_at=datetime.utcnow(),
        status=status,
    )
    db.add(prospect)
    return prospect


def test_qualify_and_launch_pipeline_loops_past_batch_cap(db_session):
    for i in range(25):
        _make_prospect(db_session, f"pr-{i}", f"co-{i}")
    db_session.commit()

    background_tasks = FakeBackgroundTasks()
    result = pipeline_runner.qualify_and_launch_pipeline(
        db_session, background_tasks, batch_cap=20, headcount_min=10, headcount_max=200
    )

    assert len(result.qualified_ids) == 25
    assert result.disqualified_count == 0
    assert len(background_tasks.scheduled) == 25
    scheduled_ids = {args[0] for _func, args, _kwargs in background_tasks.scheduled}
    assert scheduled_ids == set(result.qualified_ids)

    still_ingested = db_session.scalars(select(Prospect).where(Prospect.status == ProspectStatus.INGESTED)).all()
    assert still_ingested == []


def test_qualify_and_launch_pipeline_handles_disqualified_too(db_session):
    _make_prospect(db_session, "pr-good", "co-good")
    _make_prospect(db_session, "pr-bad", "co-bad", headcount=5)  # below min
    db_session.commit()

    background_tasks = FakeBackgroundTasks()
    result = pipeline_runner.qualify_and_launch_pipeline(
        db_session, background_tasks, batch_cap=20, headcount_min=10, headcount_max=200
    )

    assert result.qualified_ids == ["pr-good"]
    assert result.disqualified_count == 1
    assert len(background_tasks.scheduled) == 1


def test_run_full_pipeline_missing_api_key_sets_error_not_stuck_at_qualified(monkeypatch, tmp_path):
    """No manual 'Research' button exists to retry from once the key is
    fixed -- this must be a visible, recoverable ERROR, not a silent
    forever-QUALIFIED dead end."""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    monkeypatch.setattr(pipeline_runner, "SessionLocal", TestSessionLocal)

    session = TestSessionLocal()
    try:
        _make_prospect(session, "pr-1", "co-1", status=ProspectStatus.QUALIFIED)
        session.commit()
    finally:
        session.close()

    with patch("app.stages.pipeline_runner.get_settings") as mock_settings:
        mock_settings.return_value.OPENAI_API_KEY = None
        pipeline_runner.run_full_pipeline_for_prospect("pr-1")

    session = TestSessionLocal()
    try:
        prospect = session.get(Prospect, "pr-1")
        assert prospect.status == ProspectStatus.ERROR
        assert prospect.last_error is not None
        assert "OPENAI_API_KEY" in prospect.last_error
        assert prospect.last_error_at is not None
    finally:
        session.close()
        engine.dispose()
