from sqlalchemy import Boolean, Column, DateTime, Integer, String, func

from app.database import Base


class Tenant(Base):
    """A single practice/network on the platform. Every tenant-owned row carries a
    tenant_id pointing here — see CLAUDE.md's multi-tenancy rule.

    Branding lives here because the client portal is white-labeled per network
    (docs/DECISIONS.md, 2026-08-06): a client sees their network's name, not the
    platform's.
    """

    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False, unique=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")

    # White-label presentation. brand_name falls back to name when unset.
    brand_name = Column(String, nullable=True)
    brand_color = Column(String, nullable=True)
    logo_url = Column(String, nullable=True)
    support_email = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    @property
    def display_name(self) -> str:
        return self.brand_name or self.name
