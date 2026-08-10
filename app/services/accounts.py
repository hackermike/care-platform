"""Invitations and password recovery.

Two rules shape everything here:

1. **A token is a credential.** It is generated with 256 bits of entropy, stored
   only as a SHA-256, single-use, and short-lived. Looking one up is a hash
   lookup, never a scan, so there is no timing signal to exploit.
2. **Requesting a reset must reveal nothing.** The response for an unknown
   address is identical to the response for a known one. On a therapy platform,
   confirming that an address has an account discloses that a named person is a
   client of a named network — which is the disclosure this whole system exists
   to prevent.
"""
from dataclasses import dataclass
from datetime import timedelta

from app.auth.sessions import revoke_all_for_user
from app.models.account_token import (
    PURPOSE_INVITE,
    PURPOSE_RESET,
    AccountToken,
)
from app.models.tenant import Tenant
from app.models.user import User
from app.security.passwords import hash_password
from app.security.tokens import hash_token, new_token
from app.timeutil import as_utc, utcnow

# An invitation is expected to sit in an inbox until someone gets to it; a reset
# is a response to an immediate need. Different windows, for different reasons.
INVITE_TTL_HOURS = 168  # 7 days
RESET_TTL_HOURS = 1

MIN_PASSWORD_LENGTH = 12

# How many live reset tokens one account may have before requests are ignored.
# Bounds mailbox flooding without giving the flooder any feedback.
MAX_LIVE_RESET_TOKENS = 3


class AccountError(Exception):
    """The request cannot be honoured, in a way the user should be told about."""


@dataclass(frozen=True)
class IssuedToken:
    token: AccountToken
    secret: str  # the raw value for the link; never persisted


def _ttl_hours(purpose: str) -> int:
    return INVITE_TTL_HOURS if purpose == PURPOSE_INVITE else RESET_TTL_HOURS


def _live_tokens(db, user_id: int, purpose: str) -> list[AccountToken]:
    now = utcnow()
    return [
        t
        for t in db.query(AccountToken)
        .filter(
            AccountToken.user_id == user_id,
            AccountToken.purpose == purpose,
            AccountToken.consumed_at.is_(None),
        )
        .all()
        if as_utc(t.expires_at) > now
    ]


def issue(db, user: User, purpose: str, *, ip: str | None = None) -> IssuedToken:
    """Mint a token for `user`. The raw secret is returned and never stored."""
    if purpose not in (PURPOSE_INVITE, PURPOSE_RESET):
        raise AccountError(f"Unknown token purpose: {purpose!r}")

    secret = new_token()
    token = AccountToken(
        tenant_id=user.tenant_id,
        user_id=user.id,
        purpose=purpose,
        token_hash=hash_token(secret),
        expires_at=utcnow() + timedelta(hours=_ttl_hours(purpose)),
        requested_ip=ip,
    )
    db.add(token)
    return IssuedToken(token=token, secret=secret)


def request_reset(db, tenant: Tenant, email: str, *, ip: str | None = None):
    """Issue a reset token if the address belongs to an active account.

    Returns the token when one was issued and `None` otherwise. **The caller must
    respond identically either way** — that is the whole point, and the reason
    this returns a value rather than sending the mail itself.
    """
    normalized = (email or "").strip().lower()
    user = (
        db.query(User)
        .filter(User.tenant_id == tenant.id, User.email == normalized)
        .one_or_none()
    )
    if user is None or not user.is_active:
        return None
    # Bound how many live links one mailbox can accumulate. Silently, because
    # telling the requester they have hit a limit confirms the account exists.
    if len(_live_tokens(db, user.id, PURPOSE_RESET)) >= MAX_LIVE_RESET_TOKENS:
        return None
    return issue(db, user, PURPOSE_RESET, ip=ip)


def lookup(db, tenant: Tenant, secret: str, purpose: str) -> AccountToken | None:
    """Find a live token by its raw secret.

    Returns None for unknown, consumed, expired, wrong-purpose, or another
    tenant's token — the caller cannot distinguish these, and should not.
    """
    if not secret:
        return None
    token = (
        db.query(AccountToken)
        .filter(AccountToken.token_hash == hash_token(secret))
        .one_or_none()
    )
    if token is None:
        return None
    if token.purpose != purpose or token.tenant_id != tenant.id:
        return None
    if token.is_consumed or as_utc(token.expires_at) <= utcnow():
        return None
    return token


def validate_password(password: str, confirmation: str) -> str:
    if password != confirmation:
        raise AccountError("The two passwords do not match.")
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise AccountError(
            f"Use at least {MIN_PASSWORD_LENGTH} characters. A long passphrase is "
            "easier to remember and harder to guess than a short complex one."
        )
    return password


def consume(db, token: AccountToken, password: str) -> User:
    """Set the account's password and burn the token.

    Every other session for the user is revoked. If the reset was a response to a
    compromise, leaving the attacker's session alive would defeat the entire
    exercise — and the user has no way to know it is still there.

    Sibling tokens are consumed too, so a second reset link sitting in the same
    mailbox cannot be replayed later.
    """
    user = db.get(User, token.user_id)
    if user is None:
        raise AccountError("This account no longer exists.")

    user.password_hash = hash_password(password)
    user.failed_login_count = 0
    user.locked_until = None
    db.add(user)

    now = utcnow()
    token.consumed_at = now
    db.add(token)
    for sibling in _live_tokens(db, user.id, token.purpose):
        sibling.consumed_at = now
        db.add(sibling)

    revoke_all_for_user(db, user.id)
    return user


def link_for(base_url: str, purpose: str, secret: str) -> str:
    path = "/invite" if purpose == PURPOSE_INVITE else "/reset"
    return f"{base_url.rstrip('/')}{path}/{secret}"


def message_for(purpose: str, tenant: Tenant, link: str):
    """The email body.

    Says as little as possible. It does not name the recipient, describe their
    relationship to the practice, or mention care — a subject line visible on a
    lock screen should not disclose that someone is in therapy.
    """
    from app.notifications import Message

    if purpose == PURPOSE_INVITE:
        subject = f"Set up your {tenant.display_name} account"
        body = (
            f"An account has been created for you at {tenant.display_name}.\n\n"
            f"Set your password: {link}\n\n"
            f"This link expires in {INVITE_TTL_HOURS // 24} days and can be used "
            "once.\n\nIf you were not expecting this, you can ignore it."
        )
    else:
        subject = f"Reset your {tenant.display_name} password"
        body = (
            f"Someone asked to reset the password for this address at "
            f"{tenant.display_name}.\n\n"
            f"Reset it here: {link}\n\n"
            f"This link expires in {RESET_TTL_HOURS} hour and can be used once. "
            "If you did not ask for this, you can ignore it — nothing has "
            "changed."
        )
    return Message(to="", subject=subject, body=body)


__all__ = [
    "AccountError",
    "INVITE_TTL_HOURS",
    "IssuedToken",
    "MAX_LIVE_RESET_TOKENS",
    "MIN_PASSWORD_LENGTH",
    "RESET_TTL_HOURS",
    "consume",
    "issue",
    "link_for",
    "lookup",
    "message_for",
    "request_reset",
    "validate_password",
]
