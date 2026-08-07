"""Server-side session lifecycle.

Two independent timeouts, both required for a system holding PHI:

* **idle** — a session unused for SESSION_IDLE_TIMEOUT_MINUTES dies, so an
  unattended browser stops being a way in.
* **absolute** — a session older than SESSION_ABSOLUTE_TIMEOUT_HOURS dies
  regardless of activity, bounding how long a stolen token stays useful.
"""
from datetime import timedelta

from fastapi import Request
from sqlalchemy.orm import Session

from app import config
from app.audit import client_ip
from app.models.session import UserSession
from app.models.user import User
from app.security.tokens import hash_token, new_token
from app.timeutil import as_utc, hours_from_now, utcnow

_MAX_USER_AGENT = 500


def create_session(db: Session, user: User, request: Request | None = None) -> str:
    """Open a session for `user` and return the raw token for the cookie.

    Only the token's hash is persisted; the raw value exists in the response
    cookie and nowhere else.
    """
    raw = new_token()
    user_agent = request.headers.get("user-agent") if request is not None else None
    now = utcnow()
    db.add(
        UserSession(
            tenant_id=user.tenant_id,
            user_id=user.id,
            token_hash=hash_token(raw),
            last_seen_at=now,
            expires_at=hours_from_now(config.SESSION_ABSOLUTE_TIMEOUT_HOURS),
            ip_address=client_ip(request),
            user_agent=user_agent[:_MAX_USER_AGENT] if user_agent else None,
        )
    )
    return raw


def _is_live(session: UserSession) -> bool:
    now = utcnow()
    if session.revoked_at is not None:
        return False
    if as_utc(session.expires_at) <= now:
        return False
    idle_deadline = as_utc(session.last_seen_at) + timedelta(
        minutes=config.SESSION_IDLE_TIMEOUT_MINUTES
    )
    return idle_deadline > now


def load_session(db: Session, raw_token: str) -> UserSession | None:
    """Look up a live session by raw token, refreshing its idle clock.

    Returns None for unknown, revoked, expired, or idle-timed-out tokens — the
    caller cannot distinguish these, and should not.
    """
    if not raw_token:
        return None
    session = (
        db.query(UserSession)
        .filter(UserSession.token_hash == hash_token(raw_token))
        .one_or_none()
    )
    if session is None or not _is_live(session):
        return None
    session.last_seen_at = utcnow()
    return session


def revoke(db: Session, session: UserSession) -> None:
    session.revoked_at = utcnow()
    db.add(session)


def revoke_all_for_user(db: Session, user_id: int) -> int:
    """End every live session for a user. Returns how many were revoked.

    Used when an account is deactivated or a password changes — the point of
    server-side sessions is that this takes effect immediately.
    """
    now = utcnow()
    live = (
        db.query(UserSession)
        .filter(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .all()
    )
    for session in live:
        session.revoked_at = now
        db.add(session)
    return len(live)
