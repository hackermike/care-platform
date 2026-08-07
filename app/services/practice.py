"""Therapist-flow operations.

Sits between routes and models so that the rules which must not vary by entry
point — who owns a record, when a note locks, what a session may be charged —
live in one place. Routes stay thin and handle HTTP; this module handles meaning.

Everything takes a `TenantScope`, so tenant filtering is structural rather than
remembered (see `app/tenancy.py`).
"""
from dataclasses import dataclass

from app.models.appointment import STATUS_COMPLETED, Appointment
from app.models.client import Client
from app.models.note import ClinicalNote, NoteAddendum
from app.models.payment import Payment
from app.models.provider import TherapistProfile
from app.models.user import ROLE_ADMIN, User
from app.tenancy import TenantScope
from app.timeutil import utcnow


class NotPermitted(Exception):
    """The actor may not touch this record, for a reason that is not tenancy."""


@dataclass(frozen=True)
class Actor:
    """Who is acting, and as what.

    A therapist sees their own caseload; an admin sees the whole tenant. Bundling
    these together means callers ask "may this actor see this client?" instead of
    re-deriving the answer from a role string each time.
    """

    user: User
    profile: TherapistProfile | None

    @property
    def is_admin(self) -> bool:
        return self.user.role == ROLE_ADMIN

    @property
    def profile_id(self) -> int | None:
        return self.profile.id if self.profile else None


def profile_for(scope: TenantScope, user: User) -> TherapistProfile | None:
    return (
        scope.query(TherapistProfile)
        .filter(TherapistProfile.user_id == user.id)
        .one_or_none()
    )


def actor_for(scope: TenantScope, user: User) -> Actor:
    return Actor(user=user, profile=profile_for(scope, user))


# --- clients -------------------------------------------------------------


def visible_clients(scope: TenantScope, actor: Actor):
    """The clients this actor may see.

    Therapists are limited to their own caseload. That is a clinical
    confidentiality boundary as much as an access-control one: a therapist has no
    treatment relationship with a colleague's client, so they have no business
    reading that chart.
    """
    query = scope.query(Client)
    if not actor.is_admin:
        query = query.filter(Client.therapist_id == actor.profile_id)
    return query.order_by(Client.last_name, Client.first_name)


def get_client(scope: TenantScope, actor: Actor, client_id: int) -> Client | None:
    """One client, or None if it does not exist *for this actor*.

    None rather than an exception for the not-mine case, so routes can 404
    uniformly — a 403 would confirm the record exists.
    """
    client = scope.get(Client, client_id)
    if client is None:
        return None
    if not actor.is_admin and client.therapist_id != actor.profile_id:
        return None
    return client


# --- appointments --------------------------------------------------------


def appointments_for(scope: TenantScope, client: Client):
    return (
        scope.query(Appointment)
        .filter(Appointment.client_id == client.id)
        .order_by(Appointment.starts_at.desc())
    )


def get_appointment(
    scope: TenantScope, actor: Actor, appointment_id: int
) -> Appointment | None:
    appointment = scope.get(Appointment, appointment_id)
    if appointment is None:
        return None
    if get_client(scope, actor, appointment.client_id) is None:
        return None
    return appointment


def mark_completed(scope: TenantScope, appointment: Appointment) -> Appointment:
    """Complete a session, which is what makes it chargeable.

    `breakout_core.finances` only counts completed, non-written-off sessions, so
    this transition is the one that moves money into accounts receivable.
    """
    appointment.status = STATUS_COMPLETED
    scope.db.add(appointment)
    return appointment


# --- notes ---------------------------------------------------------------


def note_for(scope: TenantScope, appointment: Appointment, kind: str):
    return (
        scope.query(ClinicalNote)
        .filter(
            ClinicalNote.appointment_id == appointment.id, ClinicalNote.kind == kind
        )
        .one_or_none()
    )


def upsert_note(
    scope: TenantScope,
    actor: Actor,
    appointment: Appointment,
    kind: str,
    body: str,
) -> ClinicalNote:
    """Create or update the draft note of `kind` for an appointment.

    Refuses to touch a signed note: corrections go through `add_addendum`, so the
    record always shows what was written at the time as well as what was
    corrected later.
    """
    if actor.profile is None:
        raise NotPermitted("Only a therapist with a clinical profile may write notes.")

    note = note_for(scope, appointment, kind)
    if note is None:
        note = ClinicalNote(
            appointment_id=appointment.id,
            author_id=actor.profile_id,
            kind=kind,
            body=body,
        )
        scope.add(note)
        return note

    if note.is_signed:
        raise NotPermitted("A signed note cannot be edited; add an addendum instead.")
    note.body = body
    note.updated_at = utcnow()
    scope.db.add(note)
    return note


def sign_note(scope: TenantScope, actor: Actor, note: ClinicalNote) -> ClinicalNote:
    """Lock a note as a clinical record.

    Only the author may sign: a signature attests that *this clinician* wrote
    what is there, and an admin countersigning someone else's note would make the
    attestation meaningless.
    """
    if actor.profile_id != note.author_id:
        raise NotPermitted("Only the note's author may sign it.")
    if note.is_signed:
        return note
    note.signed_at = utcnow()
    scope.db.add(note)
    return note


def add_addendum(
    scope: TenantScope, actor: Actor, note: ClinicalNote, body: str
) -> NoteAddendum:
    if actor.profile is None:
        raise NotPermitted("Only a therapist with a clinical profile may add addenda.")
    if not note.is_signed:
        raise NotPermitted("Addenda apply to signed notes; edit the draft instead.")
    addendum = NoteAddendum(
        note_id=note.id, author_id=actor.profile_id, body=body
    )
    scope.add(addendum)
    return addendum


# --- payments ------------------------------------------------------------


def record_payment(
    scope: TenantScope,
    appointment: Appointment,
    amount,
    *,
    method: str | None = None,
    servicer_fee=None,
    is_refund: bool = False,
    reference: str | None = None,
) -> Payment:
    """Record money against a session.

    Amounts are stored positively with direction in `is_refund` — see
    `app/models/payment.py`. A negative amount is rejected rather than quietly
    reinterpreted as a refund, because the two mean different things to a payer.
    """
    from app.models.money import to_decimal

    value = to_decimal(amount)
    if value is None or value <= 0:
        raise ValueError("A payment amount must be positive; use is_refund to reverse.")

    payment = Payment(
        appointment_id=appointment.id,
        amount_value=value,
        servicer_fee_value=to_decimal(servicer_fee),
        is_refund=is_refund,
        method=method,
        reference=reference,
        paid_at=utcnow(),
    )
    scope.add(payment)
    return payment
