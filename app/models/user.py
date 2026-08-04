from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from app.database import Base

# The three role surfaces. Real auth/permissions are still to build.
ROLES = ("client", "therapist", "admin")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    email = Column(String, nullable=False)
    role = Column(String, nullable=False, default="therapist")  # one of ROLES
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    tenant = relationship("Tenant")
