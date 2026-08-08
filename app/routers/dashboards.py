"""Role landing pages.

The therapist surface links into `app/routers/practice.py`; the client surface
lives in `app/routers/portal.py` and is not routed from here. What remains is
the admin landing page, whose features arrive in M8.
"""
from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import require_admin, require_therapist
from app.models.session import UserSession
from app.models.user import User
from app.templates_config import templates
from app.tenancy import TenantScope, get_scope

router = APIRouter()


@router.get("/app")
async def therapist_home(
    request: Request,
    user: User = Depends(require_therapist),
    scope: TenantScope = Depends(get_scope),
):
    return templates.TemplateResponse(
        request,
        "dashboards/therapist.html",
        {"request": request, "user": user, "tenant": scope.tenant},
    )


@router.get("/admin")
async def admin_home(
    request: Request,
    user: User = Depends(require_admin),
    scope: TenantScope = Depends(get_scope),
):
    # Every count goes through the scope, so it is tenant-filtered by construction.
    user_count = scope.query(User).count()
    active_sessions = scope.query(UserSession).filter(UserSession.revoked_at.is_(None)).count()
    return templates.TemplateResponse(
        request,
        "dashboards/admin.html",
        {
            "request": request,
            "user": user,
            "tenant": scope.tenant,
            "user_count": user_count,
            "active_sessions": active_sessions,
        },
    )
