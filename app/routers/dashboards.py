"""The three role surfaces.

Placeholder landing pages for now — their purpose in M1 is to prove that role
enforcement and tenant scoping actually hold. Features land on them in M3+
(see docs/MILESTONES.md).
"""
from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import require_admin, require_client, require_therapist
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


@router.get("/portal")
async def client_portal(
    request: Request,
    user: User = Depends(require_client),
    scope: TenantScope = Depends(get_scope),
):
    return templates.TemplateResponse(
        request,
        "dashboards/client.html",
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
