from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from app.database import Base


class UserSession(Base):
    """A server-side login session.

    Sessions are database rows rather than self-contained signed cookies so that
    revocation is immediate: an admin disabling an account, or a user logging
    out, must end access at once. A stateless JWT cannot promise that, which
    matters when the session guards PHI.

    The cookie carries an opaque token; only its SHA-256 is stored.
    """

    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)

    user = relationship("User")
