"""Test fixtures.

By default the suite runs against a throwaway SQLite database, so a contributor
needs no external services. **Set `TEST_DATABASE_URL` to run the same suite
against PostgreSQL** — CI does both.

Running both matters more here than it usually would: money is `Numeric(10, 2)`
and timestamps are `DateTime(timezone=True)`, and those are exactly the two types
where SQLite and Postgres disagree. SQLite has no native decimal or timestamp
type and hands back naive datetimes, so a SQLite-only suite would prove very
little about the columns that carry money and appointment times.
"""
import os
import re
import tempfile

import pytest

# Choose the backend *before* anything builds the engine.
_TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
if not _TEST_DB_URL:
    _TEST_DB = os.path.join(tempfile.mkdtemp(prefix="care-test-"), "test.db")
    _TEST_DB_URL = f"sqlite:///{_TEST_DB}"
os.environ["DATABASE_URL"] = _TEST_DB_URL
os.environ.setdefault("APP_ENV", "dev")

RUNNING_ON_POSTGRES = _TEST_DB_URL.startswith("postgresql")

from fastapi.testclient import TestClient  # noqa: E402

import app.models  # noqa: E402,F401 — register models
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import ROLE_ADMIN, ROLE_CLIENT, ROLE_THERAPIST, User  # noqa: E402
from app.security.passwords import hash_password  # noqa: E402

PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
def reset_db():
    """A clean schema per test (create_all, not Alembic — Alembic runs in the app)."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    # Postgres holds connections open between tests; without disposing them a
    # later drop_all can block on an idle transaction.
    if RUNNING_ON_POSTGRES:
        engine.dispose()


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


def make_tenant(db, slug="demo", name="Demo Practice", **kwargs) -> Tenant:
    tenant = Tenant(name=name, slug=slug, is_active=kwargs.pop("is_active", True), **kwargs)
    db.add(tenant)
    db.commit()
    return tenant


def make_user(db, tenant, email, role=ROLE_THERAPIST, password=PASSWORD, **kwargs) -> User:
    user = User(
        tenant_id=tenant.id,
        email=email,
        role=role,
        password_hash=hash_password(password) if password else None,
        **kwargs,
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def tenant(db):
    """The default tenant. Dev tenant resolution maps every request to 'demo'."""
    return make_tenant(db, slug="demo")


@pytest.fixture
def therapist(db, tenant):
    return make_user(db, tenant, "dr@example.com", ROLE_THERAPIST)


@pytest.fixture
def clinician_client(db, tenant):
    return make_user(db, tenant, "patient@example.com", ROLE_CLIENT)


@pytest.fixture
def admin(db, tenant):
    return make_user(db, tenant, "admin@example.com", ROLE_ADMIN)


def csrf_token_from(html: str) -> str:
    """Pull the CSRF token out of a rendered form, as a browser would.

    Reading it from the page rather than un-signing the cookie keeps the tests
    honest: they exercise the same token the user's browser would submit.
    """
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert match, "no CSRF token in rendered page"
    return match.group(1)


def login(client, email, password=PASSWORD):
    """Sign in through the real form, including the CSRF round-trip."""
    page = client.get("/login")
    return client.post(
        "/login",
        data={
            "email": email,
            "password": password,
            "csrf_token": csrf_token_from(page.text),
        },
        follow_redirects=False,
    )
