"""Test fixtures. Tests run against a throwaway SQLite database (no Postgres
needed); the app uses Postgres in real environments."""
import os
import tempfile

import pytest

# Point at a temp SQLite DB *before* anything builds the engine.
_TEST_DB = os.path.join(tempfile.mkdtemp(prefix="care-test-"), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"

from fastapi.testclient import TestClient  # noqa: E402

import app.models  # noqa: E402,F401 — register models
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def reset_db():
    """A clean schema per test (create_all, not Alembic — Alembic runs in the app)."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    # Plain instantiation does not trigger the app lifespan, so run_migrations()
    # (which needs Postgres) is not invoked during tests.
    return TestClient(app)
