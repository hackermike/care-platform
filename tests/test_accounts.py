"""Invitations and password recovery.

These routes are public by necessity — a locked-out user cannot authenticate to
ask for help — which makes them the most exposed surface on the platform.
"""
from datetime import timedelta

import pytest

from app.models.account_token import PURPOSE_INVITE, PURPOSE_RESET, AccountToken
from app.models.session import UserSession
from app.models.user import ROLE_THERAPIST, User
from app.security.passwords import verify_password
from app.security.tokens import hash_token
from app.services import accounts
from app.timeutil import utcnow
from tests.conftest import PASSWORD, csrf_token_from, login, make_tenant, make_user

NEW_PASSWORD = "a-much-longer-passphrase"


@pytest.fixture
def account(db):
    tenant = make_tenant(db, slug="demo", name="Riverside Counseling")
    user = make_user(db, tenant, "dr@example.com", ROLE_THERAPIST)
    return {"tenant": tenant, "user": user}


def request_reset(client, email):
    page = client.get("/forgot")
    return client.post(
        "/forgot",
        data={"email": email, "csrf_token": csrf_token_from(page.text)},
    )


def issued_secret(db, user, purpose=PURPOSE_RESET):
    """Mint a token directly — the email body is not the unit under test."""
    result = accounts.issue(db, user, purpose)
    db.commit()
    return result.secret


def submit_password(client, purpose, secret, password, confirmation=None):
    page = client.get(f"/{purpose}/{secret}")
    return client.post(
        f"/{purpose}/{secret}",
        data={
            "password": password,
            "confirmation": confirmation if confirmation is not None else password,
            "csrf_token": csrf_token_from(page.text),
        },
        follow_redirects=False,
    )


class TestRequestingAReset:
    def test_a_known_address_issues_a_token(self, client, db, account):
        request_reset(client, account["user"].email)
        assert db.query(AccountToken).count() == 1

    def test_an_unknown_address_issues_nothing(self, client, db, account):
        request_reset(client, "stranger@example.com")
        assert db.query(AccountToken).count() == 0

    def test_the_response_is_identical_either_way(self, client, db, account):
        """Any variation turns this form into 'is this person a client here?'"""
        known = request_reset(client, account["user"].email)
        unknown = request_reset(client, "stranger@example.com")
        assert known.status_code == unknown.status_code == 200
        assert known.text == unknown.text

    def test_an_inactive_account_issues_nothing(self, client, db, account):
        account["user"].is_active = False
        db.commit()
        request_reset(client, account["user"].email)
        assert db.query(AccountToken).count() == 0

    def test_live_tokens_are_capped(self, client, db, account):
        """Bounds mailbox flooding — silently, since a 'limit reached' message
        would confirm the account exists."""
        for _ in range(accounts.MAX_LIVE_RESET_TOKENS + 3):
            request_reset(client, account["user"].email)
        assert db.query(AccountToken).count() == accounts.MAX_LIVE_RESET_TOKENS

    def test_the_request_is_audited(self, client, db, account):
        from app.models.audit import AuditLog

        request_reset(client, account["user"].email)
        entries = db.query(AuditLog).filter(
            AuditLog.resource_type == "account_token"
        ).all()
        assert len(entries) == 1
        assert "reset requested" in entries[0].detail


class TestTokenStorage:
    def test_the_secret_is_never_stored(self, db, account):
        secret = issued_secret(db, account["user"])
        token = db.query(AccountToken).one()
        assert token.token_hash != secret
        assert secret not in token.token_hash
        assert token.token_hash == hash_token(secret)

    def test_secrets_are_unique(self, db, account):
        first = issued_secret(db, account["user"])
        second = issued_secret(db, account["user"])
        assert first != second

    def test_an_unknown_purpose_is_refused(self, db, account):
        with pytest.raises(accounts.AccountError):
            accounts.issue(db, account["user"], "something-else")


class TestUsingALink:
    def test_a_valid_link_sets_the_password(self, client, db, account):
        secret = issued_secret(db, account["user"])
        r = submit_password(client, "reset", secret, NEW_PASSWORD)
        assert r.status_code == 303
        assert r.headers["location"] == "/login"

        db.expire_all()
        user = db.get(User, account["user"].id)
        assert verify_password(NEW_PASSWORD, user.password_hash)

    def test_the_new_password_actually_works(self, client, db, account):
        secret = issued_secret(db, account["user"])
        submit_password(client, "reset", secret, NEW_PASSWORD)
        client.cookies.clear()
        r = login(client, account["user"].email, NEW_PASSWORD)
        assert r.status_code == 303

    def test_the_old_password_stops_working(self, client, db, account):
        secret = issued_secret(db, account["user"])
        submit_password(client, "reset", secret, NEW_PASSWORD)
        client.cookies.clear()
        assert login(client, account["user"].email, PASSWORD).status_code == 401

    def test_a_link_cannot_be_reused(self, client, db, account):
        secret = issued_secret(db, account["user"])
        submit_password(client, "reset", secret, NEW_PASSWORD)
        r = client.get(f"/reset/{secret}")
        assert r.status_code == 404
        assert "no longer valid" in r.text

    def test_a_sibling_link_is_burned_too(self, client, db, account):
        """A second reset email sitting in the same mailbox must not be
        replayable after the first has been used."""
        first = issued_secret(db, account["user"])
        second = issued_secret(db, account["user"])
        submit_password(client, "reset", first, NEW_PASSWORD)
        assert client.get(f"/reset/{second}").status_code == 404

    def test_an_expired_link_is_refused(self, client, db, account):
        secret = issued_secret(db, account["user"])
        token = db.query(AccountToken).one()
        token.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
        assert client.get(f"/reset/{secret}").status_code == 404

    def test_an_unknown_link_is_refused(self, client, account):
        assert client.get("/reset/not-a-real-token").status_code == 404

    def test_a_reset_token_cannot_be_used_as_an_invite(self, client, db, account):
        """Purpose is checked, so the longer-lived invite flow cannot be reached
        with a short-lived reset token or vice versa."""
        secret = issued_secret(db, account["user"], PURPOSE_RESET)
        assert client.get(f"/invite/{secret}").status_code == 404

    def test_another_tenants_token_is_refused(self, client, db, account):
        elsewhere = make_tenant(db, slug="elsewhere", name="Elsewhere")
        stranger = make_user(db, elsewhere, "x@example.com", ROLE_THERAPIST)
        secret = issued_secret(db, stranger)
        # Requests resolve to "demo"; this token belongs to another tenant.
        assert client.get(f"/reset/{secret}").status_code == 404


class TestSessionsAreRevoked:
    def test_resetting_signs_out_every_other_device(self, client, db, account):
        """If the reset is a response to a compromise, leaving the attacker's
        session alive defeats the whole exercise."""
        login(client, account["user"].email)
        assert db.query(UserSession).filter(
            UserSession.revoked_at.is_(None)
        ).count() == 1

        secret = issued_secret(db, account["user"])
        submit_password(client, "reset", secret, NEW_PASSWORD)

        db.expire_all()
        assert db.query(UserSession).filter(
            UserSession.revoked_at.is_(None)
        ).count() == 0

    def test_the_existing_session_stops_working(self, client, db, account):
        login(client, account["user"].email)
        assert client.get("/app", follow_redirects=False).status_code == 200
        secret = issued_secret(db, account["user"])
        submit_password(client, "reset", secret, NEW_PASSWORD)
        assert client.get("/app", follow_redirects=False).status_code == 303


class TestPasswordRules:
    def test_a_mismatch_is_rejected(self, client, db, account):
        secret = issued_secret(db, account["user"])
        r = submit_password(client, "reset", secret, NEW_PASSWORD, "something-else")
        assert r.status_code == 400
        assert "do not match" in r.text

    def test_a_short_password_is_rejected(self, client, db, account):
        secret = issued_secret(db, account["user"])
        r = submit_password(client, "reset", secret, "short")
        assert r.status_code == 400
        assert str(accounts.MIN_PASSWORD_LENGTH) in r.text

    def test_a_rejected_attempt_does_not_burn_the_link(self, client, db, account):
        secret = issued_secret(db, account["user"])
        submit_password(client, "reset", secret, "short")
        assert client.get(f"/reset/{secret}").status_code == 200

    def test_a_rejected_attempt_does_not_change_the_password(self, client, db, account):
        secret = issued_secret(db, account["user"])
        submit_password(client, "reset", secret, "short")
        db.expire_all()
        assert verify_password(PASSWORD, db.get(User, account["user"].id).password_hash)


class TestInvitations:
    def test_an_invite_sets_a_first_password(self, client, db, account):
        user = make_user(db, account["tenant"], "new@example.com",
                         ROLE_THERAPIST, password=None)
        secret = issued_secret(db, user, PURPOSE_INVITE)
        assert client.get(f"/invite/{secret}").status_code == 200
        r = submit_password(client, "invite", secret, NEW_PASSWORD)
        assert r.status_code == 303

        db.expire_all()
        assert verify_password(NEW_PASSWORD, db.get(User, user.id).password_hash)

    def test_an_account_with_no_password_cannot_sign_in_first(self, client, db, account):
        make_user(db, account["tenant"], "new@example.com", ROLE_THERAPIST,
                  password=None)
        assert login(client, "new@example.com", NEW_PASSWORD).status_code == 401


class TestEmailContent:
    def test_the_message_does_not_mention_care(self, account):
        """A subject line on a lock screen must not disclose that someone is in
        therapy."""
        message = accounts.message_for(
            PURPOSE_RESET, account["tenant"], "https://demo.example/reset/x"
        )
        combined = f"{message.subject} {message.body}".lower()
        for word in ("therapy", "therapist", "appointment", "clinical", "patient"):
            assert word not in combined

    def test_the_message_carries_the_link(self, account):
        link = "https://demo.example/reset/abc"
        assert link in accounts.message_for(PURPOSE_RESET, account["tenant"], link).body

    def test_the_invite_message_states_its_lifetime(self, account):
        message = accounts.message_for(PURPOSE_INVITE, account["tenant"], "x")
        assert "7 days" in message.body


class TestSenderConfiguration:
    def test_dev_uses_the_logging_sender(self, monkeypatch):
        from app import notifications

        monkeypatch.setattr(notifications.config, "IS_DEV", True)
        assert isinstance(notifications.for_environment(), notifications.LoggingSender)

    def test_production_refuses_to_pretend(self, monkeypatch):
        """A silently dropped reset email is indistinguishable from a broken
        account, and the user cannot tell you which."""
        from app import notifications

        monkeypatch.setattr(notifications.config, "IS_DEV", False)
        sender = notifications.for_environment()
        with pytest.raises(notifications.NotificationError):
            sender.send(notifications.Message(to="a@b.c", subject="s", body="b"))
