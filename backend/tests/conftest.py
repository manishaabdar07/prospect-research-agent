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
