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
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import models  # noqa: F401  (ensure models are registered on Base.metadata)
from app.database import Base


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session: Session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
