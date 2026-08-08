"""The therapist's daily surface: caseload, sessions, notes, money, superbills.

Every route here reads or writes PHI, so every route records that it did
(`app/phi.py`). Records that do not belong to the actor return 404 rather than
403 — a 403 confirms the record exists, which is itself a disclosure.
"""
from datetime import date

from breakout_core import cpt, finances
from breakout_core.superbill import build_superbill_pdf
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse, Response

from app import downloads, forms, licensure, phi
from app.auth.dependencies import require_therapist
from app.models.appointment import STATUSES, Appointment
from app.models.client import Client
from app.models.forms import FormAssignment, FormTemplate
from app.models.money import to_decimal
from app.models.note import KIND_PROGRESS, KIND_PSYCHOTHERAPY, KINDS
from app.models.payment import METHODS
from app.models.user import User
from app.services import practice
from app.services.practice import NotPermitted
from app.templates_config import templates
from app.tenancy import TenantScope, get_scope

router = APIRouter(prefix="/app")


def _not_found() -> Response:
    return Response("Not found.", status_code=status.HTTP_404_NOT_FOUND)


def _actor(scope: TenantScope, user: User) -> practice.Actor:
    return practice.actor_for(scope, user)


@router.get("/clients")
async def client_list(
    request: Request,
    user: User = Depends(require_therapist),
    scope: TenantScope = Depends(get_scope),
):
    actor = _actor(scope, user)
    clients = practice.visible_clients(scope, actor).all()
    # A caseload listing is PHI access even without opening a chart.
    phi.viewed(
        scope.db, user, phi.RESOURCE_CLIENT, "list",
        request=request, detail=f"count={len(clients)}",
    )
    scope.commit()
    return templates.TemplateResponse(
        request,
        "practice/clients.html",
        {"request": request, "user": user, "tenant": scope.tenant,
         "clients": clients, "actor": actor},
    )


@router.get("/clients/{client_id}")
async def client_detail(
    client_id: int,
    request: Request,
    user: User = Depends(require_therapist),
    scope: TenantScope = Depends(get_scope),
):
    actor = _actor(scope, user)
    client = practice.get_client(scope, actor, client_id)
    if client is None:
        return _not_found()

    appointments = practice.appointments_for(scope, client).all()
    phi.viewed(scope.db, user, phi.RESOURCE_CLIENT, client.id, request=request)
    scope.commit()

    # Money math comes from breakout-core, not from a local reimplementation.
    balance = finances.balance_on_services(appointments)
    collected = finances.total_collected(appointments)

    licence = None
    if actor.profile is not None:
        licence = licensure.check(actor.profile, client.state)

    form_templates = (
        scope.query(FormTemplate)
        .filter(FormTemplate.is_active.is_(True))
        .order_by(FormTemplate.name)
        .all()
    )
    assignments = (
        scope.query(FormAssignment)
        .filter(FormAssignment.client_id == client.id)
        .order_by(FormAssignment.assigned_at.desc())
        .all()
    )

    return templates.TemplateResponse(
        request,
        "practice/client_detail.html",
        {
            "request": request, "user": user, "tenant": scope.tenant,
            "client": client, "appointments": appointments,
            "balance": balance, "collected": collected, "licence": licence,
            "statuses": STATUSES, "cpt_codes": cpt.BOOKABLE,
            "form_templates": form_templates, "assignments": assignments,
        },
    )


@router.post("/clients")
async def create_client(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    state: str = Form(""),
    email: str = Form(""),
    diagnosis_codes: str = Form(""),
    user: User = Depends(require_therapist),
    scope: TenantScope = Depends(get_scope),
):
    actor = _actor(scope, user)
    client = Client(
        therapist_id=actor.profile_id,
        first_name=forms.required_text(first_name, "First name", max_length=100),
        last_name=forms.required_text(last_name, "Last name", max_length=100),
        state=forms.parse_state(state),
        email=forms.optional_text(email),
        diagnosis_codes=forms.optional_text(diagnosis_codes),
    )
    scope.add(client)
    scope.flush()
    phi.modified(
        scope.db, user, phi.RESOURCE_CLIENT, client.id,
        request=request, detail="created",
    )
    scope.commit()
    return RedirectResponse(
        url=f"/app/clients/{client.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/clients/{client_id}/appointments")
async def create_appointment(
    client_id: int,
    request: Request,
    starts_at: str = Form(...),
    cpt_code: str = Form(""),
    fee: str = Form(""),
    user: User = Depends(require_therapist),
    scope: TenantScope = Depends(get_scope),
):
    actor = _actor(scope, user)
    client = practice.get_client(scope, actor, client_id)
    if client is None:
        return _not_found()

    # Licensure is checked at booking — the engineering residue of the
    # state-agnostic launch decision (docs/DECISIONS.md).
    if actor.profile is not None:
        allowed = licensure.check(actor.profile, client.state)
        if not allowed:
            return Response(allowed.reason, status_code=status.HTTP_400_BAD_REQUEST)

    when = forms.parse_datetime(starts_at, "Session time")
    code = forms.parse_cpt(cpt_code)
    appointment = Appointment(
        client_id=client.id,
        therapist_id=actor.profile_id,
        starts_at=when,
        cpt_code=code,
        # Fall back to the shared catalog's default fee rather than a local copy.
        fee_amount=forms.parse_money(fee, "Fee", required=False)
        or to_decimal(cpt.default_fee(code)),
        diagnosis_codes=client.diagnosis_codes,
    )
    scope.add(appointment)
    scope.flush()
    phi.modified(
        scope.db, user, phi.RESOURCE_APPOINTMENT, appointment.id,
        request=request, detail="created",
    )
    scope.commit()
    return RedirectResponse(
        url=f"/app/appointments/{appointment.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/appointments/{appointment_id}")
async def appointment_detail(
    appointment_id: int,
    request: Request,
    user: User = Depends(require_therapist),
    scope: TenantScope = Depends(get_scope),
):
    actor = _actor(scope, user)
    appointment = practice.get_appointment(scope, actor, appointment_id)
    if appointment is None:
        return _not_found()

    phi.viewed(
        scope.db, user, phi.RESOURCE_APPOINTMENT, appointment.id, request=request
    )
    scope.commit()

    progress = practice.note_for(scope, appointment, KIND_PROGRESS)
    psychotherapy = practice.note_for(scope, appointment, KIND_PSYCHOTHERAPY)
    return templates.TemplateResponse(
        request,
        "practice/appointment_detail.html",
        {
            "request": request, "user": user, "tenant": scope.tenant,
            "appointment": appointment, "client": appointment.client,
            "progress": progress, "psychotherapy": psychotherapy,
            "paid": finances.appt_paid(appointment), "statuses": STATUSES,
        },
    )


@router.post("/appointments/{appointment_id}/complete")
async def complete_appointment(
    appointment_id: int,
    request: Request,
    user: User = Depends(require_therapist),
    scope: TenantScope = Depends(get_scope),
):
    actor = _actor(scope, user)
    appointment = practice.get_appointment(scope, actor, appointment_id)
    if appointment is None:
        return _not_found()
    practice.mark_completed(scope, appointment)
    phi.modified(
        scope.db, user, phi.RESOURCE_APPOINTMENT, appointment.id,
        request=request, detail="status=completed",
    )
    scope.commit()
    return RedirectResponse(
        url=f"/app/appointments/{appointment.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/appointments/{appointment_id}/notes")
async def save_note(
    appointment_id: int,
    request: Request,
    body: str = Form(""),
    kind: str = Form(KIND_PROGRESS),
    sign: str = Form(""),
    user: User = Depends(require_therapist),
    scope: TenantScope = Depends(get_scope),
):
    actor = _actor(scope, user)
    appointment = practice.get_appointment(scope, actor, appointment_id)
    if appointment is None:
        return _not_found()
    kind = forms.parse_choice(kind, KINDS, "note kind", default=KIND_PROGRESS)

    try:
        note = practice.upsert_note(scope, actor, appointment, kind, body)
        scope.flush()
        if sign:
            practice.sign_note(scope, actor, note)
    except NotPermitted as exc:
        scope.db.rollback()
        return Response(str(exc), status_code=status.HTTP_403_FORBIDDEN)

    phi.modified(
        scope.db, user, phi.RESOURCE_NOTE, note.id,
        request=request, detail=f"kind={kind} signed={bool(sign)}",
    )
    scope.commit()
    return RedirectResponse(
        url=f"/app/appointments/{appointment.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/notes/{note_id}/addenda")
async def add_addendum(
    note_id: int,
    request: Request,
    body: str = Form(...),
    user: User = Depends(require_therapist),
    scope: TenantScope = Depends(get_scope),
):
    from app.models.note import ClinicalNote

    actor = _actor(scope, user)
    note = scope.get(ClinicalNote, note_id)
    if note is None or practice.get_appointment(scope, actor, note.appointment_id) is None:
        return _not_found()
    try:
        practice.add_addendum(scope, actor, note, body)
    except NotPermitted as exc:
        return Response(str(exc), status_code=status.HTTP_403_FORBIDDEN)
    phi.modified(
        scope.db, user, phi.RESOURCE_NOTE, note.id, request=request, detail="addendum"
    )
    scope.commit()
    return RedirectResponse(
        url=f"/app/appointments/{note.appointment_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/appointments/{appointment_id}/payments")
async def add_payment(
    appointment_id: int,
    request: Request,
    amount: str = Form(...),
    method: str = Form(""),
    servicer_fee: str = Form(""),
    is_refund: str = Form(""),
    user: User = Depends(require_therapist),
    scope: TenantScope = Depends(get_scope),
):
    actor = _actor(scope, user)
    appointment = practice.get_appointment(scope, actor, appointment_id)
    if appointment is None:
        return _not_found()
    payment = practice.record_payment(
        scope,
        appointment,
        forms.parse_money(amount, "Payment amount"),
        method=forms.parse_choice(method, METHODS, "payment method", default=None)
        if method
        else None,
        servicer_fee=forms.parse_money(servicer_fee, "Processor fee", required=False),
        is_refund=bool(is_refund),
    )
    scope.flush()
    phi.modified(
        scope.db, user, phi.RESOURCE_PAYMENT, payment.id,
        request=request, detail=f"refund={bool(is_refund)}",
    )
    scope.commit()
    return RedirectResponse(
        url=f"/app/appointments/{appointment.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/clients/{client_id}/forms")
async def assign_form(
    client_id: int,
    request: Request,
    template_id: str = Form(...),
    user: User = Depends(require_therapist),
    scope: TenantScope = Depends(get_scope),
):
    """Give a client a form to complete in the portal.

    Assignment is explicit rather than "every active template applies to
    everyone": which paperwork a client owes is an administrative decision, and
    showing someone consent documents that do not apply to them is worse than
    showing none.
    """
    actor = _actor(scope, user)
    client = practice.get_client(scope, actor, client_id)
    if client is None:
        return _not_found()

    template = scope.get(FormTemplate, forms.parse_int(template_id, "Form template"))
    if template is None or not template.is_active:
        return Response(
            "Unknown form template.", status_code=status.HTTP_400_BAD_REQUEST
        )

    existing = (
        scope.query(FormAssignment)
        .filter(
            FormAssignment.client_id == client.id,
            FormAssignment.template_id == template.id,
            FormAssignment.completed_at.is_(None),
        )
        .first()
    )
    if existing is None:
        assignment = FormAssignment(client_id=client.id, template_id=template.id)
        scope.add(assignment)
        scope.flush()
        phi.modified(
            scope.db, user, "form_assignment", assignment.id,
            request=request, detail=f"template={template.id}",
        )
    scope.commit()
    return RedirectResponse(
        url=f"/app/clients/{client.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/clients/{client_id}/superbill")
async def superbill(
    client_id: int,
    request: Request,
    start: str = "",
    end: str = "",
    user: User = Depends(require_therapist),
    scope: TenantScope = Depends(get_scope),
):
    """Generate a superbill PDF via breakout-core.

    The document itself is PHI leaving the system, so it is audited with the
    range it covers — which is exactly the sort of question a records request
    asks later.
    """
    actor = _actor(scope, user)
    client = practice.get_client(scope, actor, client_id)
    if client is None:
        return _not_found()
    provider = client.therapist or actor.profile
    if provider is None:
        return Response(
            "This client has no assigned therapist to bill under.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    today = date.today()
    start_date = forms.parse_date(start, "Start date") or today.replace(month=1, day=1)
    end_date = forms.parse_date(end, "End date") or today
    if start_date > end_date:
        raise forms.FormError("The start date must not be after the end date.")

    appointments = [
        appt
        for appt in practice.appointments_for(scope, client).all()
        if start_date <= appt.starts_at.date() <= end_date
    ]
    pdf = build_superbill_pdf(provider, client, appointments, start_date, end_date)

    phi.viewed(
        scope.db, user, phi.RESOURCE_SUPERBILL, client.id,
        request=request,
        detail=f"range={start_date}..{end_date} sessions={len(appointments)}",
    )
    scope.commit()

    # The client's name is user-controlled, so the filename is sanitised rather
    # than interpolated — see app/downloads.py.
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers=downloads.attachment_headers(
            f"superbill-{client.last_name.lower()}-{start_date}-{end_date}.pdf",
            fallback="superbill.pdf",
        ),
    )
