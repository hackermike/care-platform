"""The client-facing portal.

White-labeled per tenant (docs/DECISIONS.md) — a client sees their network's
name, never the platform's.

**Every route resolves the client record from the session, never from a URL
parameter.** A client-facing surface that accepts an id in the path is one
off-by-one away from showing someone else's chart, so the id simply is not an
input here.
"""
from datetime import date

from breakout_core import finances
from breakout_core.superbill import build_superbill_pdf
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse, Response

from app import audit, downloads, phi
from app import forms as form_parsing
from app.auth.dependencies import require_client
from app.models.appointment import Appointment
from app.models.client import Client
from app.models.forms import FormAssignment
from app.models.user import User
from app.services import intake
from app.services.intake import IntakeError
from app.templates_config import templates
from app.tenancy import TenantScope, get_scope

router = APIRouter(prefix="/portal")


def _client_for(scope: TenantScope, user: User) -> Client | None:
    """The client record this signed-in user *is*.

    Resolved from the session's user id, so there is no path by which a client
    can address another client's record.
    """
    return scope.query(Client).filter(Client.user_id == user.id).one_or_none()


def _no_record(request: Request, user: User, scope: TenantScope):
    """A client account with no linked chart yet.

    Not an error: an account can be provisioned before the record is linked. It
    just has nothing to show.
    """
    return templates.TemplateResponse(
        request,
        "portal/no_record.html",
        {"request": request, "user": user, "tenant": scope.tenant},
    )


@router.get("")
async def home(
    request: Request,
    user: User = Depends(require_client),
    scope: TenantScope = Depends(get_scope),
):
    client = _client_for(scope, user)
    if client is None:
        return _no_record(request, user, scope)

    pending = intake.pending_for(scope, client.id).all()
    completed = intake.completed_for(scope, client.id).all()
    appointments = (
        scope.query(Appointment)
        .filter(Appointment.client_id == client.id)
        .order_by(Appointment.starts_at.desc())
        .all()
    )
    balance = finances.balance_on_services(appointments)

    phi.viewed(scope.db, user, phi.RESOURCE_CLIENT, client.id, request=request,
               detail="portal-home")
    scope.commit()

    return templates.TemplateResponse(
        request,
        "portal/home.html",
        {
            "request": request, "user": user, "tenant": scope.tenant,
            "client": client, "pending": pending, "completed": completed,
            "balance": balance, "appointments": appointments,
        },
    )


@router.get("/forms/{assignment_id}")
async def show_form(
    assignment_id: int,
    request: Request,
    user: User = Depends(require_client),
    scope: TenantScope = Depends(get_scope),
):
    client = _client_for(scope, user)
    if client is None:
        return _no_record(request, user, scope)

    assignment = scope.get(FormAssignment, assignment_id)
    # The assignment must belong to *this* client, not merely to this tenant.
    if assignment is None or assignment.client_id != client.id:
        return Response("Not found.", status_code=status.HTTP_404_NOT_FOUND)

    return templates.TemplateResponse(
        request,
        "portal/form.html",
        {
            "request": request, "user": user, "tenant": scope.tenant,
            "assignment": assignment, "template": assignment.template,
            "fields": intake.parse_schema(assignment.template),
            "error": None,
        },
    )


@router.post("/forms/{assignment_id}")
async def submit_form(
    assignment_id: int,
    request: Request,
    user: User = Depends(require_client),
    scope: TenantScope = Depends(get_scope),
):
    client = _client_for(scope, user)
    if client is None:
        return _no_record(request, user, scope)

    assignment = scope.get(FormAssignment, assignment_id)
    if assignment is None or assignment.client_id != client.id:
        return Response("Not found.", status_code=status.HTTP_404_NOT_FOUND)

    payload = dict(await request.form())
    signature = payload.pop("signature_name", None)
    payload.pop("csrf_token", None)

    try:
        submission = intake.submit(
            scope,
            assignment,
            payload,
            submitted_by_id=user.id,
            signature_name=signature,
            ip=audit.client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except IntakeError as exc:
        scope.db.rollback()
        return templates.TemplateResponse(
            request,
            "portal/form.html",
            {
                "request": request, "user": user, "tenant": scope.tenant,
                "assignment": assignment, "template": assignment.template,
                "fields": intake.parse_schema(assignment.template),
                "error": str(exc),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    scope.flush()
    phi.modified(
        scope.db, user, "form_submission", submission.id, request=request,
        detail=f"template={assignment.template_id} signed={submission.is_signed}",
    )
    scope.commit()
    return RedirectResponse(url="/portal", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/statement")
async def statement(
    request: Request,
    start: str = "",
    end: str = "",
    user: User = Depends(require_client),
    scope: TenantScope = Depends(get_scope),
):
    """The client's own superbill, for their insurer.

    Same `breakout-core` generator the therapist surface uses — one document,
    one implementation.
    """
    client = _client_for(scope, user)
    if client is None:
        return _no_record(request, user, scope)
    if client.therapist is None:
        return Response(
            "No therapist is assigned to your record yet.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    today = date.today()
    start_date = form_parsing.parse_date(start, "Start date") or today.replace(
        month=1, day=1
    )
    end_date = form_parsing.parse_date(end, "End date") or today
    if start_date > end_date:
        raise form_parsing.FormError("The start date must not be after the end date.")

    appointments = [
        appt
        for appt in scope.query(Appointment)
        .filter(Appointment.client_id == client.id)
        .order_by(Appointment.starts_at)
        .all()
        if start_date <= appt.starts_at.date() <= end_date
    ]
    pdf = build_superbill_pdf(
        client.therapist, client, appointments, start_date, end_date
    )

    phi.viewed(
        scope.db, user, phi.RESOURCE_SUPERBILL, client.id, request=request,
        detail=f"portal range={start_date}..{end_date} sessions={len(appointments)}",
    )
    scope.commit()

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers=downloads.attachment_headers(
            f"statement-{start_date}-{end_date}.pdf", fallback="statement.pdf"
        ),
    )
