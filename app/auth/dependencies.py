"""Request dependencies for authentication and role enforcement.

`current_user` resolves the session cookie to a user *and* checks that the user
belongs to the tenant the request resolved to. That second check is the one that
matters: without it, a valid session for tenant A would be honoured on tenant
B's hostname.
"""
from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import audit, config
from app.auth import sessions
from app.database import get_db
from app.models.audit import ACTION_ACCESS_DENIED
from app.models.tenant import Tenant
from app.models.user import ROLE_ADMIN, ROLE_CLIENT, ROLE_THERAPIST, User
from app.tenancy import TenantScope, get_scope, get_tenant


class NotAuthenticated(Exception):
    """No valid session. Browsers get a redirect to the login page."""


def optional_user(
    request: Request,
    tenant: Tenant = Depends(get_tenant),
    db: Session = Depends(get_db),
) -> User | None:
    """The signed-in user, or None. Never raises — for pages that render either way."""
    raw = request.cookies.get(config.SESSION_COOKIE)
    if not raw:
        return None
    session = sessions.load_session(db, raw)
    if session is None:
        return None
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None
    # A session issued for another tenant must not be honoured here.
    if user.tenant_id != tenant.id or session.tenant_id != tenant.id:
        return None
    return user


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise NotAuthenticated()
    return user


def require_role(*allowed: str):
    """Dependency factory restricting a route to the given roles.

    Denials are audited: repeated authorization failures against PHI routes are
    exactly the signal an incident review needs.
    """

    def _dependency(
        request: Request,
        user: User = Depends(current_user),
        scope: TenantScope = Depends(get_scope),
    ) -> User:
        if user.role not in allowed:
            audit.record(
                scope.db,
                ACTION_ACCESS_DENIED,
                tenant_id=user.tenant_id,
                user_id=user.id,
                resource_type="route",
                resource_id=request.url.path,
                detail=f"role={user.role} required={','.join(allowed)}",
                request=request,
            )
            scope.db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted."
            )
        return user

    return _dependency


require_admin = require_role(ROLE_ADMIN)
require_therapist = require_role(ROLE_THERAPIST, ROLE_ADMIN)
require_client = require_role(ROLE_CLIENT)


def login_redirect(request: Request) -> RedirectResponse:
    """Send an unauthenticated browser to the login page, preserving intent."""
    target = request.url.path
    suffix = f"?next={target}" if target and target != "/login" else ""
    return RedirectResponse(url=f"/login{suffix}", status_code=status.HTTP_303_SEE_OTHER)
