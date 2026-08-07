from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func

from app.database import Base

# Audit actions. PHI access is the category HIPAA actually cares about; auth
# events are here because "who got in, and when" is the first question asked
# after an incident.
ACTION_LOGIN_SUCCEEDED = "auth.login.succeeded"
ACTION_LOGIN_FAILED = "auth.login.failed"
ACTION_LOGOUT = "auth.logout"
ACTION_SESSION_EXPIRED = "auth.session.expired"
ACTION_ACCESS_DENIED = "authz.access.denied"
ACTION_PHI_VIEWED = "phi.viewed"
ACTION_PHI_MODIFIED = "phi.modified"


class AuditLog(Base):
    """Append-only record of authentication and PHI access.

    Never updated or deleted by application code. tenant_id is nullable only
    because a failed login can arrive before a tenant is resolved; every
    tenant-scoped event must set it.
    """

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    action = Column(String, nullable=False, index=True)
    resource_type = Column(String, nullable=True)
    resource_id = Column(String, nullable=True)

    # Free-form context. Must never contain PHI — an audit log that leaks the
    # data it is auditing defeats its own purpose.
    detail = Column(Text, nullable=True)

    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
