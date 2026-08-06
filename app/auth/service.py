"""Credential verification, lockout, and the audit trail around both."""
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Request
from sqlalchemy.orm import Session

from app import audit, config
from app.models.audit import ACTION_LOGIN_FAILED, ACTION_LOGIN_SUCCEEDED
from app.models.tenant import Tenant
from app.models.user import User
from app.security.passwords import hash_password, needs_rehash, verify_password
from app.timeutil import as_utc, utcnow


@dataclass(frozen=True)
class AuthResult:
    user: User | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.user is not None


# One message for every failure mode. Distinguishing "no such account" from
# "wrong password" turns the login form into an account-enumeration oracle,
# which for a therapy platform leaks who is a client of which network.
GENERIC_FAILURE = "Email or password is incorrect."
LOCKED_FAILURE = "Too many failed attempts. Try again later."


def _is_locked(user: User) -> bool:
    locked_until = as_utc(user.locked_until)
    return locked_until is not None and locked_until > utcnow()


def _register_failure(db: Session, user: User) -> None:
    user.failed_login_count = (user.failed_login_count or 0) + 1
    if user.failed_login_count >= config.LOGIN_MAX_ATTEMPTS:
        user.locked_until = utcnow() + timedelta(minutes=config.LOGIN_LOCKOUT_MINUTES)
        user.failed_login_count = 0
    db.add(user)


def authenticate(
    db: Session,
    tenant: Tenant,
    email: str,
    password: str,
    request: Request | None = None,
) -> AuthResult:
    """Verify credentials within one tenant.

    Scoped to the tenant because email is only unique per tenant — the same
    address may be a client here and a therapist elsewhere.
    """
    normalized = (email or "").strip().lower()
    user = (
        db.query(User)
        .filter(User.tenant_id == tenant.id, User.email == normalized)
        .one_or_none()
    )

    def fail(reason: str, message: str = GENERIC_FAILURE) -> AuthResult:
        audit.record(
            db,
            ACTION_LOGIN_FAILED,
            tenant_id=tenant.id,
            user_id=user.id if user else None,
            detail=reason,
            request=request,
        )
        return AuthResult(user=None, error=message)

    if user is None:
        # Hash anyway, so a missing account does not return measurably faster
        # than a wrong password.
        hash_password(password or "")
        return fail("unknown-email")
    if not user.is_active:
        return fail("inactive-account")
    if _is_locked(user):
        return fail("locked-out", LOCKED_FAILURE)
    if not user.password_hash:
        return fail("no-password-set")
    if not verify_password(password or "", user.password_hash):
        _register_failure(db, user)
        return fail("bad-password")

    # Transparently upgrade hashes made with older Argon2 parameters.
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = utcnow()
    db.add(user)
    audit.record(
        db,
        ACTION_LOGIN_SUCCEEDED,
        tenant_id=tenant.id,
        user_id=user.id,
        request=request,
    )
    return AuthResult(user=user)
