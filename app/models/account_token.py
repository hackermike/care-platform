from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from app.database import Base

# What a token entitles the bearer to do.
PURPOSE_INVITE = "invite"  # first-time password set, for a provisioned account
PURPOSE_RESET = "reset"  # password recovery for an existing account
PURPOSES = (PURPOSE_INVITE, PURPOSE_RESET)


class AccountToken(Base):
    """A single-use, expiring capability sent to a user's email address.

    **The token is the credential.** Anyone holding it can set a password on the
    account, so it is treated exactly like one: 256 bits of entropy, stored only
    as a SHA-256, single-use, and short-lived. A leaked mailbox is already a
    compromise, but a token that stays valid for a month turns one old email into
    a permanent key.

    `consumed_at` rather than deletion, because "this link was already used" is a
    materially different answer from "this link never existed", and an incident
    review needs to tell them apart.
    """

    __tablename__ = "account_tokens"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    purpose = Column(String, nullable=False)
    token_hash = Column(String, nullable=False, unique=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)

    # Who asked for it, so a flood of requests is attributable.
    requested_ip = Column(String, nullable=True)

    user = relationship("User")

    @property
    def is_consumed(self) -> bool:
        return self.consumed_at is not None
