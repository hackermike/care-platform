"""Client-state vs. therapist-licensure checking (docs/DECISIONS.md)."""
from datetime import timedelta

import pytest

from app import licensure
from app.models.provider import TherapistLicense, TherapistProfile
from app.models.user import ROLE_THERAPIST
from app.timeutil import utcnow
from tests.conftest import make_tenant, make_user


@pytest.fixture
def therapist(db):
    tenant = make_tenant(db, slug="demo")
    user = make_user(db, tenant, "dr@example.com", ROLE_THERAPIST)
    profile = TherapistProfile(tenant_id=tenant.id, user_id=user.id, name="Alex Reed")
    db.add(profile)
    db.flush()
    return profile


def add_license(db, therapist, state, expires_on=None):
    licence = TherapistLicense(
        tenant_id=therapist.tenant_id,
        therapist_id=therapist.id,
        state=state,
        expires_on=expires_on,
    )
    db.add(licence)
    db.commit()
    db.refresh(therapist)
    return licence


def test_licensed_in_the_clients_state(db, therapist):
    add_license(db, therapist, "CA")
    assert licensure.check(therapist, "CA")


def test_not_licensed_in_the_clients_state(db, therapist):
    add_license(db, therapist, "CA")
    result = licensure.check(therapist, "NY")
    assert not result
    assert result.reason == licensure.NOT_LICENSED


def test_state_comparison_ignores_case_and_padding(db, therapist):
    add_license(db, therapist, "CA")
    assert licensure.check(therapist, " ca ")


def test_unknown_client_state_fails_closed(db, therapist):
    """Guessing would assert compliance the platform cannot vouch for."""
    add_license(db, therapist, "CA")
    result = licensure.check(therapist, None)
    assert not result
    assert result.reason == licensure.UNKNOWN_CLIENT_STATE


def test_a_therapist_with_no_licences_is_refused(db, therapist):
    assert not licensure.check(therapist, "CA")


def test_expired_licence_is_refused(db, therapist):
    add_license(db, therapist, "CA", expires_on=utcnow() - timedelta(days=1))
    result = licensure.check(therapist, "CA")
    assert not result
    assert result.reason == licensure.LICENSE_EXPIRED


def test_unexpired_licence_is_accepted(db, therapist):
    add_license(db, therapist, "CA", expires_on=utcnow() + timedelta(days=30))
    assert licensure.check(therapist, "CA")


def test_licence_without_an_expiry_is_treated_as_current(db, therapist):
    """Networks do not always record expiry; refusing those would block real
    practice."""
    add_license(db, therapist, "CA", expires_on=None)
    assert licensure.check(therapist, "CA")


def test_licensed_states_excludes_expired(db, therapist):
    add_license(db, therapist, "CA")
    add_license(db, therapist, "NY", expires_on=utcnow() - timedelta(days=1))
    add_license(db, therapist, "OR", expires_on=utcnow() + timedelta(days=10))
    assert licensure.licensed_states(therapist) == ["CA", "OR"]


def test_a_state_may_only_be_licensed_once_per_therapist(db, therapist):
    from sqlalchemy.exc import IntegrityError

    add_license(db, therapist, "CA")
    with pytest.raises(IntegrityError):
        add_license(db, therapist, "CA")
    db.rollback()
