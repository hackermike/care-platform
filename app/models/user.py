from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import true

from app.database import Base

# The three role surfaces (docs/ARCHITECTURE.md).
ROLE_CLIENT = "client"
ROLE_THERAPIST = "therapist"
ROLE_ADMIN = "admin"
ROLES = (ROLE_CLIENT, ROLE_THERAPIST, ROLE_ADMIN)


class User(Base):
    """A person within one tenant.

    Email is unique *per tenant*, not globally: the same person may be a client
    of one network and a therapist in another, and those are separate accounts
    with separate credentials. A global unique constraint would silently prevent
    that.
    """

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),)

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    email = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    role = Column(String, nullable=False, default=ROLE_THERAPIST)  # one of ROLES
    password_hash = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default=true())

    # Failed-login throttling state (app/config.py sets the thresholds).
    failed_login_count = Column(Integer, nullable=False, default=0, server_default="0")
    locked_until = Column(DateTime(timezone=True), nullable=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    tenant = relationship("Tenant")

    @property
    def display_name(self) -> str:
        return self.full_name or self.email
