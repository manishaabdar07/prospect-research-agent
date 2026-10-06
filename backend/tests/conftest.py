"""Test fixtures.

Tests use an isolated in-memory SQLite database per test rather than the
Postgres instance the app uses at runtime -- this keeps `pytest` runnable
with zero external services, which matters for the stage1/stage2/record_finding
unit tests explicitly called out in the spec as not needing API keys or a
live Postgres. The ORM avoids any Postgres-only column types (see
app/models.py), so behavior is equivalent for what these tests exercise.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401  (ensure models are registered on Base.metadata)
from app.database import Base, get_db
from app.main import app
from app.models import QualificationCampaign, QualificationCriteria

# Mirrors alembic/versions/0004_qualification_campaigns.py's seed data --
# `Base.metadata.create_all()` (below) creates the tables but does not run
# migration data seeds, so tests that exercise Stage 2 qualify need to seed
# these explicitly to get the same default behavior production starts with.
PUNE_METRO_ALLOWLIST = [
    "pune", "pimpri-chinchwad", "chakan", "hinjewadi", "talegaon", "ranjangaon",
    "chikhali", "wagholi", "hadapsar", "baner", "kharadi", "bhosari", "manjari", "shirwal",
]


def seed_default_qualification_criteria(
    db: Session, *, headcount_min: int = 10, headcount_max: int = 200
) -> QualificationCampaign:
    """Seeds one active "Default" campaign with the same 4 criteria the
    original hardcoded Stage 2 logic checked, all mandatory=True (which
    reproduces the old ALL-mode behavior exactly). Returns the campaign so a
    test can add more criteria to it or create additional campaigns."""
    campaign = QualificationCampaign(name="Default", is_active=True, min_optional_matches=None)
    db.add(campaign)
    db.flush()
    db.add_all(
        [
            QualificationCriteria(
                campaign_id=campaign.id, name="Headcount Band", criterion_type="RANGE", field="company.headcount",
                configuration={"min": headcount_min, "max": headcount_max}, enabled=True, mandatory=True, priority=10,
            ),
            QualificationCriteria(
                campaign_id=campaign.id, name="City Allowlist", criterion_type="LIST", field="company.city",
                configuration={"allowed_values": PUNE_METRO_ALLOWLIST}, enabled=True, mandatory=True, priority=20,
            ),
            QualificationCriteria(
                campaign_id=campaign.id, name="Exclusion List", criterion_type="EXCLUSION_LIST", field=None,
                configuration={}, enabled=True, mandatory=True, priority=30,
            ),
            QualificationCriteria(
                campaign_id=campaign.id, name="Duplicate Check", criterion_type="DUPLICATE_CHECK", field=None,
                configuration={}, enabled=True, mandatory=True, priority=40,
            ),
        ]
    )
    db.commit()
    return campaign


@pytest.fixture()
def db_session():
    # StaticPool: a plain sqlite ":memory:" engine hands each new thread its
    # own, separate, empty database by default -- fine for a single-threaded
    # test, but TestClient (see the `client` fixture) dispatches requests to
    # a worker thread, which would otherwise see "no such table". StaticPool
    # keeps every connection, from any thread, pointed at the same one.
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session: Session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session):
    """A FastAPI TestClient wired to the same in-memory db_session, so a test
    can call the HTTP API and then assert directly on ORM objects afterward."""

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
