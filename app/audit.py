"""Writing to the audit log.

One helper, used everywhere, so the shape of an audit record stays consistent
and callers cannot accidentally omit the request context.

**Never pass PHI in `detail`.** The audit log is retained longer and read more
widely than the records it describes; putting clinical content in it widens
exposure rather than narrowing it. Identify records by type and id.
"""
from fastapi import Request
from sqlalchemy.orm import Session

from app.models.audit import AuditLog

_MAX_USER_AGENT = 500


def client_ip(request: Request | None) -> str | None:
    """Best-effort client IP.

    X-Forwarded-For is only meaningful behind a proxy that sets it; the leftmost
    entry is the original client. Deployments must ensure the TLS proxy
    overwrites rather than appends, or this value is attacker-controlled.
    """
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def record(
    db: Session,
    action: str,
    *,
    tenant_id: int | None = None,
    user_id: int | None = None,
    resource_type: str | None = None,
    resource_id: str | int | None = None,
    detail: str | None = None,
    request: Request | None = None,
) -> AuditLog:
    """Append an audit entry. The caller owns the commit."""
    user_agent = request.headers.get("user-agent") if request is not None else None
    entry = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        detail=detail,
        ip_address=client_ip(request),
        user_agent=user_agent[:_MAX_USER_AGENT] if user_agent else None,
    )
    db.add(entry)
    return entry
