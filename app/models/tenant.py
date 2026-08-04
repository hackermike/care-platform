from sqlalchemy import Column, DateTime, Integer, String, func

from app.database import Base


class Tenant(Base):
    """A single practice/network on the platform. Every tenant-owned row carries a
    tenant_id pointing here — see CLAUDE.md's multi-tenancy rule."""

    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
