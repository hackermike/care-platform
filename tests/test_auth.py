"""Login, logout, lockout, and session lifecycle."""
from datetime import timedelta

from app.models.audit import (
    ACTION_LOGIN_FAILED,
    ACTION_LOGIN_SUCCEEDED,
    ACTION_LOGOUT,
    AuditLog,
)
from app.models.session import UserSession
from app.models.user import User
from app.timeutil import utcnow
from tests.conftest import PASSWORD, csrf_token_from, login


def test_login_page_renders_tenant_brand(client, tenant, db):
    tenant.brand_name = "Riverside Counseling"
    db.commit()
    r = client.get("/login")
    assert r.status_code == 200
    assert "Riverside Counseling" in r.text


def test_successful_login_redirects_to_role_surface(client, therapist):
    r = login(client, therapist.email)
    assert r.status_code == 303
    assert r.headers["location"] == "/app"
    assert client.cookies.get("care_session")


def test_admin_and_client_land_on_their_own_surfaces(client, admin):
    r = login(client, admin.email)
    assert r.headers["location"] == "/admin"


def test_client_role_lands_on_portal(client, clinician_client):
    r = login(client, clinician_client.email)
    assert r.headers["location"] == "/portal"


def test_wrong_password_is_rejected(client, therapist):
    r = login(client, therapist.email, "not-the-password")
    assert r.status_code == 401
    assert not client.cookies.get("care_session")


def test_failure_message_does_not_reveal_whether_the_account_exists(client, therapist):
    unknown = login(client, "nobody@example.com", "whatever")
    client.cookies.clear()
    wrong = login(client, therapist.email, "wrong")
    assert unknown.status_code == wrong.status_code == 401
    # Identical wording, so the form cannot be used to enumerate accounts.
    assert "Email or password is incorrect." in unknown.text
    assert "Email or password is incorrect." in wrong.text


def test_inactive_user_cannot_sign_in(client, db, therapist):
    therapist.is_active = False
    db.commit()
    assert login(client, therapist.email).status_code == 401


def test_lockout_after_repeated_failures(client, db, therapist):
    from app import config

    for _ in range(config.LOGIN_MAX_ATTEMPTS):
        client.cookies.clear()
        login(client, therapist.email, "wrong")

    db.expire_all()
    locked = db.get(User, therapist.id)
    assert locked.locked_until is not None

    # Even the correct password is refused while locked.
    client.cookies.clear()
    r = login(client, therapist.email, PASSWORD)
    assert r.status_code == 401
    assert "Too many failed attempts" in r.text


def test_logout_revokes_the_session(client, db, therapist):
    login(client, therapist.email)
    page = client.get("/app")
    r = client.post(
        "/logout",
        data={"csrf_token": csrf_token_from(page.text)},
        follow_redirects=False,
    )
    assert r.status_code == 303

    session = db.query(UserSession).one()
    assert session.revoked_at is not None
    # And the surface is no longer reachable.
    assert client.get("/app", follow_redirects=False).status_code == 303


def test_expired_session_is_not_accepted(client, db, therapist):
    login(client, therapist.email)
    session = db.query(UserSession).one()
    session.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    assert client.get("/app", follow_redirects=False).status_code == 303


def test_idle_session_times_out(client, db, therapist):
    from app import config

    login(client, therapist.email)
    session = db.query(UserSession).one()
    session.last_seen_at = utcnow() - timedelta(
        minutes=config.SESSION_IDLE_TIMEOUT_MINUTES + 1
    )
    db.commit()
    assert client.get("/app", follow_redirects=False).status_code == 303


def test_session_token_is_not_stored_in_the_clear(client, db, therapist):
    login(client, therapist.email)
    raw = client.cookies.get("care_session")
    session = db.query(UserSession).one()
    assert session.token_hash != raw
    assert raw not in session.token_hash


def test_auth_events_are_audited(client, db, therapist):
    login(client, therapist.email, "wrong")
    client.cookies.clear()
    login(client, therapist.email)
    page = client.get("/app")
    client.post("/logout", data={"csrf_token": csrf_token_from(page.text)})

    actions = [a.action for a in db.query(AuditLog).order_by(AuditLog.id).all()]
    assert ACTION_LOGIN_FAILED in actions
    assert ACTION_LOGIN_SUCCEEDED in actions
    assert ACTION_LOGOUT in actions


def test_next_parameter_cannot_redirect_offsite(client, therapist):
    page = client.get("/login")
    r = client.post(
        "/login",
        data={
            "email": therapist.email,
            "password": PASSWORD,
            "csrf_token": csrf_token_from(page.text),
            "next": "https://evil.example.com/steal",
        },
        follow_redirects=False,
    )
    assert r.headers["location"] == "/app"


def test_next_parameter_allows_relative_paths(client, therapist):
    page = client.get("/login")
    r = client.post(
        "/login",
        data={
            "email": therapist.email,
            "password": PASSWORD,
            "csrf_token": csrf_token_from(page.text),
            "next": "/app",
        },
        follow_redirects=False,
    )
    assert r.headers["location"] == "/app"
