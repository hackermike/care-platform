"""Password recovery and first-time account setup.

Public routes by necessity — a locked-out user cannot authenticate to ask for
help. That makes them the most exposed surface on the platform, so each one is
written to reveal nothing about whether an account exists.
"""
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import audit, notifications
from app.database import get_db
from app.models.account_token import PURPOSE_INVITE, PURPOSE_RESET
from app.models.audit import ACTION_PHI_MODIFIED
from app.models.tenant import Tenant
from app.services import accounts
from app.services.accounts import AccountError
from app.templates_config import templates
from app.tenancy import get_tenant

router = APIRouter()

# Shown whether or not the address matched an account. Any variation here — a
# different message, a different status, a different response time — turns this
# form into a way to ask "is this person a client of this practice?"
RESET_REQUESTED = (
    "If that address has an account, a reset link is on its way. "
    "The link expires in an hour."
)


def _send(tenant: Tenant, request: Request, purpose: str, email: str, secret: str):
    """Deliver the link, or log loudly if no provider is configured.

    A failure here must not surface to the caller: which addresses failed to
    send is itself a disclosure, and the user-facing response is fixed.
    """
    link = accounts.link_for(str(request.base_url), purpose, secret)
    message = accounts.message_for(purpose, tenant, link)
    sender = notifications.for_environment()
    try:
        sender.send(notifications.Message(to=email, subject=message.subject,
                                          body=message.body))
    except notifications.NotificationError:
        # Deliberately swallowed for the response, surfaced for the operator.
        import logging

        logging.getLogger(__name__).exception(
            "Could not send a %s link for tenant %s", purpose, tenant.slug
        )


@router.get("/forgot")
async def forgot_form(
    request: Request,
    tenant: Tenant = Depends(get_tenant),
):
    return templates.TemplateResponse(
        request,
        "auth/forgot.html",
        {"request": request, "tenant": tenant, "sent": False, "error": None},
    )


@router.post("/forgot")
async def forgot_submit(
    request: Request,
    email: str = Form(""),
    tenant: Tenant = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    issued = accounts.request_reset(
        db, tenant, email, ip=audit.client_ip(request)
    )
    if issued is not None:
        db.flush()
        audit.record(
            db,
            ACTION_PHI_MODIFIED,
            tenant_id=tenant.id,
            user_id=issued.token.user_id,
            resource_type="account_token",
            resource_id=issued.token.id,
            detail="reset requested",
            request=request,
        )
        _send(tenant, request, PURPOSE_RESET, email.strip().lower(), issued.secret)
    db.commit()

    # Identical response either way — see RESET_REQUESTED.
    return templates.TemplateResponse(
        request,
        "auth/forgot.html",
        {"request": request, "tenant": tenant, "sent": True, "error": None},
    )


def _set_password_page(request, tenant, purpose, secret, error=None, status_code=200):
    return templates.TemplateResponse(
        request,
        "auth/set_password.html",
        {
            "request": request, "tenant": tenant, "purpose": purpose,
            "secret": secret, "error": error,
            "min_length": accounts.MIN_PASSWORD_LENGTH,
        },
        status_code=status_code,
    )


def _invalid_link(request, tenant):
    return templates.TemplateResponse(
        request,
        "auth/link_invalid.html",
        {"request": request, "tenant": tenant},
        status_code=status.HTTP_404_NOT_FOUND,
    )


@router.get("/reset/{secret}")
async def reset_form(
    secret: str,
    request: Request,
    tenant: Tenant = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    if accounts.lookup(db, tenant, secret, PURPOSE_RESET) is None:
        return _invalid_link(request, tenant)
    return _set_password_page(request, tenant, PURPOSE_RESET, secret)


@router.get("/invite/{secret}")
async def invite_form(
    secret: str,
    request: Request,
    tenant: Tenant = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    if accounts.lookup(db, tenant, secret, PURPOSE_INVITE) is None:
        return _invalid_link(request, tenant)
    return _set_password_page(request, tenant, PURPOSE_INVITE, secret)


async def _complete(request, tenant, db, secret, purpose, password, confirmation):
    token = accounts.lookup(db, tenant, secret, purpose)
    if token is None:
        return _invalid_link(request, tenant)
    try:
        accounts.validate_password(password, confirmation)
    except AccountError as exc:
        return _set_password_page(
            request, tenant, purpose, secret, error=str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user = accounts.consume(db, token, password)
    audit.record(
        db,
        ACTION_PHI_MODIFIED,
        tenant_id=tenant.id,
        user_id=user.id,
        resource_type="user",
        resource_id=user.id,
        detail=f"password set via {purpose}; sessions revoked",
        request=request,
    )
    db.commit()
    # Deliberately not signed in automatically: proving the password works is
    # worth one extra step, and it keeps a single flow for reaching the app.
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/reset/{secret}")
async def reset_submit(
    secret: str,
    request: Request,
    password: str = Form(""),
    confirmation: str = Form(""),
    tenant: Tenant = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    return await _complete(
        request, tenant, db, secret, PURPOSE_RESET, password, confirmation
    )


@router.post("/invite/{secret}")
async def invite_submit(
    secret: str,
    request: Request,
    password: str = Form(""),
    confirmation: str = Form(""),
    tenant: Tenant = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    return await _complete(
        request, tenant, db, secret, PURPOSE_INVITE, password, confirmation
    )
