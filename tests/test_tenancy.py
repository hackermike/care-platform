"""Tenant isolation.

`CLAUDE.md`: a missing tenant scope is a data-leak bug, not a style nit. These
tests exist to make that failure mode loud.
"""
import pytest
from sqlalchemy.exc import IntegrityError

from app.models.tenant import Tenant
from app.models.user import ROLE_ADMIN, ROLE_THERAPIST, User
from app.tenancy import CrossTenantError, TenantScope, subdomain_for
from tests.conftest import make_tenant, make_user


@pytest.fixture
def two_tenants(db):
    a = make_tenant(db, slug="alpha", name="Alpha Network")
    b = make_tenant(db, slug="beta", name="Beta Collective")
    make_user(db, a, "a1@example.com", ROLE_THERAPIST)
    make_user(db, a, "a2@example.com", ROLE_THERAPIST)
    make_user(db, b, "b1@example.com", ROLE_THERAPIST)
    return a, b


def test_query_returns_only_the_scoped_tenants_rows(db, two_tenants):
    alpha, beta = two_tenants
    assert TenantScope(db, alpha).query(User).count() == 2
    assert TenantScope(db, beta).query(User).count() == 1


def test_get_does_not_reach_across_tenants(db, two_tenants):
    alpha, beta = two_tenants
    other = TenantScope(db, beta).query(User).first()
    # Alpha's scope must not see Beta's user, even by explicit primary key.
    assert TenantScope(db, alpha).get(User, other.id) is None


def test_add_stamps_the_tenant_id(db, two_tenants):
    alpha, _ = two_tenants
    scope = TenantScope(db, alpha)
    user = scope.add(User(email="new@example.com", role=ROLE_THERAPIST))
    scope.commit()
    assert user.tenant_id == alpha.id


def test_add_rejects_a_foreign_tenant_id(db, two_tenants):
    alpha, beta = two_tenants
    scope = TenantScope(db, alpha)
    with pytest.raises(CrossTenantError):
        scope.add(User(tenant_id=beta.id, email="x@example.com", role=ROLE_THERAPIST))


def test_querying_a_model_without_tenant_id_is_refused(db, two_tenants):
    alpha, _ = two_tenants
    # Tenant itself is not tenant-owned; scoping it is a category error and
    # should fail loudly rather than silently returning everything.
    with pytest.raises(CrossTenantError):
        TenantScope(db, alpha).query(Tenant)


def test_email_may_repeat_across_tenants(db, two_tenants):
    """The same person can be a client of one network and a therapist in another."""
    alpha, beta = two_tenants
    make_user(db, beta, "a1@example.com", ROLE_THERAPIST)
    assert db.query(User).filter(User.email == "a1@example.com").count() == 2


def test_email_is_unique_within_a_tenant(db, two_tenants):
    alpha, _ = two_tenants
    with pytest.raises(IntegrityError):
        make_user(db, alpha, "a1@example.com", ROLE_THERAPIST)
    db.rollback()


def test_admin_counts_are_tenant_scoped(client, db, two_tenants):
    """The admin dashboard must count its own network only."""
    alpha, _ = two_tenants
    # Dev tenant resolution maps requests to DEV_DEFAULT_TENANT_SLUG ('demo').
    alpha.slug = "demo"
    admin = make_user(db, alpha, "admin@example.com", ROLE_ADMIN)
    db.commit()

    from tests.conftest import login

    login(client, admin.email)
    r = client.get("/admin")
    assert r.status_code == 200
    # Alpha has 3 users (2 therapists + this admin); Beta's 1 must not appear.
    assert ">3<" in r.text.replace(" ", "").replace("\n", "")


class TestSubdomainResolution:
    def test_extracts_the_tenant_label(self, monkeypatch):
        from app import config

        monkeypatch.setattr(config, "TENANT_HOST_SUFFIX", "example.com")
        assert subdomain_for("acme.example.com") == "acme"
        assert subdomain_for("acme.example.com:8000") == "acme"

    def test_ignores_hosts_outside_the_suffix(self, monkeypatch):
        from app import config

        monkeypatch.setattr(config, "TENANT_HOST_SUFFIX", "example.com")
        assert subdomain_for("acme.evil.com") is None
        assert subdomain_for("example.com") is None

    def test_rejects_nested_labels(self, monkeypatch):
        """Only a single leading label names a tenant."""
        from app import config

        monkeypatch.setattr(config, "TENANT_HOST_SUFFIX", "example.com")
        assert subdomain_for("a.b.example.com") is None

    def test_no_suffix_configured_means_no_subdomain_tenants(self, monkeypatch):
        from app import config

        monkeypatch.setattr(config, "TENANT_HOST_SUFFIX", "")
        assert subdomain_for("acme.example.com") is None


class TestScopedAggregates:
    """Counting must not be the one operation that escapes the tenant boundary."""

    def test_a_column_query_is_scoped(self, db, two_tenants):
        alpha, beta = two_tenants
        rows = TenantScope(db, alpha).query(User.email).all()
        assert {r[0] for r in rows} == {"a1@example.com", "a2@example.com"}

    def test_an_aggregate_is_scoped(self, db, two_tenants):
        from sqlalchemy import func

        alpha, beta = two_tenants
        scoped = TenantScope(db, alpha).query(
            User.tenant_id, func.count(User.id)
        ).group_by(User.tenant_id).all()
        assert scoped == [(alpha.id, 2)]

    def test_scoping_is_taken_from_the_first_entity(self, db, two_tenants):
        from sqlalchemy import func

        alpha, _ = two_tenants
        # func.count() carries no tenant, so the first entity must be the one
        # that decides — otherwise this query would silently span tenants.
        total = TenantScope(db, alpha).query(User.id, func.count(User.id)).group_by(
            User.id
        ).count()
        assert total == 2

    def test_an_unscoped_first_entity_is_refused(self, db, two_tenants):
        alpha, _ = two_tenants
        with pytest.raises(CrossTenantError):
            TenantScope(db, alpha).query(Tenant.name)

    def test_an_empty_query_is_refused(self, db, two_tenants):
        alpha, _ = two_tenants
        with pytest.raises(CrossTenantError):
            TenantScope(db, alpha).query()
