"""Login and logout."""
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import audit, config
from app.auth import sessions
from app.auth.dependencies import optional_user
from app.auth.service import authenticate
from app.database import get_db
from app.models.audit import ACTION_LOGOUT
from app.models.tenant import Tenant
from app.models.user import ROLE_ADMIN, ROLE_CLIENT, User
from app.security import csrf
from app.templates_config import templates
from app.tenancy import get_tenant

router = APIRouter()


def landing_path_for(user: User) -> str:
    """Where a user goes after signing in. Each role has its own surface."""
    if user.role == ROLE_ADMIN:
        return "/admin"
    if user.role == ROLE_CLIENT:
        return "/portal"
    return "/app"


def _safe_next(candidate: str | None) -> str | None:
    """Only allow same-site relative redirects.

    A `next` parameter that accepts absolute URLs is an open redirect, which is
    a credible phishing vector against exactly the users this platform serves.
    """
    if not candidate:
        return None
    # Reject anything a browser might read as scheme-relative. "//host" is the
    # obvious form; "/\\host" and "/\t/host" are the ones that get missed,
    # because some browsers normalise a backslash to a slash before resolving.
    if not candidate.startswith("/"):
        return None
    if candidate[1:2] in ("/", "\\"):
        return None
    if any(ch in candidate for ch in ("\\", "\t", "\r", "\n")):
        return None
    return candidate


@router.get("/login")
async def login_form(
    request: Request,
    tenant: Tenant = Depends(get_tenant),
    user: User | None = Depends(optional_user),
):
    if user is not None:
        return RedirectResponse(
            url=landing_path_for(user), status_code=status.HTTP_303_SEE_OTHER
        )
    # The CSRF token is provisioned by CSRFTokenMiddleware; templates read it
    # from request.state, so no route has to remember to mint one.
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {
            "request": request,
            "tenant": tenant,
            "error": None,
            "next": _safe_next(request.query_params.get("next")) or "",
        },
    )


@router.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    next: str = Form(""),
    tenant: Tenant = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    result = authenticate(db, tenant, email, password, request=request)
    if not result.ok:
        db.commit()  # persist the failed-login audit entry and lockout counter
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {
                "request": request,
                "tenant": tenant,
                "error": result.error,
                "next": _safe_next(next) or "",
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    user = result.user
    raw_token = sessions.create_session(db, user, request=request)
    db.commit()

    destination = _safe_next(next) or landing_path_for(user)
    response = RedirectResponse(url=destination, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        config.SESSION_COOKIE,
        raw_token,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    # Rotate the CSRF token on privilege change, so a token minted before login
    # cannot be replayed against the authenticated session.
    csrf.issue_token(response)
    return response


@router.post("/logout")
async def logout(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(optional_user),
):
    raw = request.cookies.get(config.SESSION_COOKIE)
    if raw:
        session = sessions.load_session(db, raw)
        if session is not None:
            sessions.revoke(db, session)
    if user is not None:
        audit.record(
            db, ACTION_LOGOUT, tenant_id=user.tenant_id, user_id=user.id, request=request
        )
    db.commit()

    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(config.SESSION_COOKIE, path="/")
    return response
