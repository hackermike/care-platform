"""Password recovery and first-time account setup.

Public routes by necessity — a locked-out user cannot authenticate to ask for
help. That makes them the most exposed surface on the platform, so each one is
written to reveal nothing about whether an account exists.

Two details that are easy to get wrong and are handled deliberately here:

* **Delivery happens after the response is sent.** Minting a token, writing an
  audit row, and talking to a mail provider all take time; doing them inline for
  a known address and returning immediately for an unknown one turns response
  latency into an account-existence oracle. With a real provider that difference
  is hundreds of milliseconds and trivially measurable.
* **The secret leaves the URL before the password is submitted.** An emailed link
  necessarily carries the token in its path, but that path lands in browser
  history, proxy logs, and access logs. The link is exchanged once for an
  HttpOnly cookie, and the form then posts to a path with no secret in it.
"""
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import audit, config, notifications
from app.database import get_db
from app.models.account_token import PURPOSE_INVITE, PURPOSE_RESET
from app.models.audit import ACTION_PHI_MODIFIED
from app.models.tenant import Tenant
from app.services import accounts
from app.services.accounts import AccountError
from app.templates_config import templates
from app.tenancy import get_tenant

logger = logging.getLogger(__name__)

router = APIRouter()

# Holds the emailed secret between the link and the form, so the password POST
# carries no credential in its URL. Short-lived: it only has to survive one
# redirect and however long someone takes to choose a password.
HANDOFF_COOKIE = "care_setpw"
HANDOFF_TTL_SECONDS = 30 * 60


def _deliver(to: str, subject: str, body: str, tenant_slug: str, purpose: str) -> None:
    """Send the link. Runs after the response, so it cannot be timed.

    Takes plain strings rather than ORM instances: by the time this runs the
    request's session is closed and a detached instance would raise.
    """
    try:
        notifications.for_environment().send(
            notifications.Message(to=to, subject=subject, body=body)
        )
    except notifications.NotificationError:
        # Never surfaced to the caller — which addresses failed to send is
        # itself a disclosure. Loud for the operator, silent in the response.
        logger.exception("Could not send a %s link for tenant %s", purpose, tenant_slug)


@router.get("/forgot")
async def forgot_form(request: Request, tenant: Tenant = Depends(get_tenant)):
    return templates.TemplateResponse(
        request,
        "auth/forgot.html",
        {"request": request, "tenant": tenant, "sent": False, "error": None},
    )


@router.post("/forgot")
async def forgot_submit(
    request: Request,
    background: BackgroundTasks,
    email: str = Form(""),
    tenant: Tenant = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    issued = accounts.request_reset(db, tenant, email, ip=audit.client_ip(request))
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
        # Built from configuration, never from the request Host header.
        link = accounts.link_for(tenant, PURPOSE_RESET, issued.secret)
        message = accounts.message_for(PURPOSE_RESET, tenant, link)
        background.add_task(
            _deliver,
            email.strip().lower(),
            message.subject,
            message.body,
            tenant.slug,
            PURPOSE_RESET,
        )
    db.commit()

    # Identical response whether or not an account matched.
    return templates.TemplateResponse(
        request,
        "auth/forgot.html",
        {"request": request, "tenant": tenant, "sent": True, "error": None},
    )


def _invalid_link(request, tenant):
    response = templates.TemplateResponse(
        request,
        "auth/link_invalid.html",
        {"request": request, "tenant": tenant},
        status_code=status.HTTP_404_NOT_FOUND,
    )
    response.delete_cookie(HANDOFF_COOKIE, path="/")
    return response


def _handoff(secret: str, purpose: str, destination: str):
    """Swap the link for a cookie and send the browser to a secretless path."""
    response = RedirectResponse(url=destination, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        HANDOFF_COOKIE,
        f"{purpose}:{secret}",
        max_age=HANDOFF_TTL_SECONDS,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return response


def _held_secret(request: Request, purpose: str) -> str | None:
    raw = request.cookies.get(HANDOFF_COOKIE) or ""
    held_purpose, _, secret = raw.partition(":")
    return secret if held_purpose == purpose and secret else None


def _set_password_page(request, tenant, purpose, error=None, status_code=200):
    return templates.TemplateResponse(
        request,
        "auth/set_password.html",
        {
            "request": request, "tenant": tenant, "purpose": purpose,
            "error": error, "min_length": accounts.MIN_PASSWORD_LENGTH,
        },
        status_code=status_code,
    )


async def _open_link(secret, request, tenant, db, purpose):
    if accounts.lookup(db, tenant, secret, purpose) is None:
        return _invalid_link(request, tenant)
    return _handoff(secret, purpose, f"/{purpose}")


async def _show_form(request, tenant, db, purpose):
    secret = _held_secret(request, purpose)
    if secret is None or accounts.lookup(db, tenant, secret, purpose) is None:
        return _invalid_link(request, tenant)
    return _set_password_page(request, tenant, purpose)


async def _complete(request, tenant, db, purpose, password, confirmation):
    secret = _held_secret(request, purpose)
    if secret is None:
        return _invalid_link(request, tenant)
    token = accounts.lookup(db, tenant, secret, purpose)
    if token is None:
        return _invalid_link(request, tenant)

    try:
        accounts.validate_password(password, confirmation)
    except AccountError as exc:
        # A mistyped confirmation must not burn the link.
        return _set_password_page(
            request, tenant, purpose, error=str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        user = accounts.consume(db, token, password)
    except AccountError:
        # Lost a race with a concurrent request carrying the same link.
        db.rollback()
        return _invalid_link(request, tenant)

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
    # worth one extra step, and it keeps a single path into the app.
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(HANDOFF_COOKIE, path="/")
    return response


@router.get("/reset/{secret}")
async def reset_link(
    secret: str,
    request: Request,
    tenant: Tenant = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    return await _open_link(secret, request, tenant, db, PURPOSE_RESET)


@router.get("/reset")
async def reset_form(
    request: Request,
    tenant: Tenant = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    return await _show_form(request, tenant, db, PURPOSE_RESET)


@router.post("/reset")
async def reset_submit(
    request: Request,
    password: str = Form(""),
    confirmation: str = Form(""),
    tenant: Tenant = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    return await _complete(request, tenant, db, PURPOSE_RESET, password, confirmation)


@router.get("/invite/{secret}")
async def invite_link(
    secret: str,
    request: Request,
    tenant: Tenant = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    return await _open_link(secret, request, tenant, db, PURPOSE_INVITE)


@router.get("/invite")
async def invite_form(
    request: Request,
    tenant: Tenant = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    return await _show_form(request, tenant, db, PURPOSE_INVITE)


@router.post("/invite")
async def invite_submit(
    request: Request,
    password: str = Form(""),
    confirmation: str = Form(""),
    tenant: Tenant = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    return await _complete(request, tenant, db, PURPOSE_INVITE, password, confirmation)
