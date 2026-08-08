"""Intake forms, consent documents, and signatures.

The rule this module exists to hold: **a signature binds to the exact text that
was on screen.** Editing a consent template afterwards must never change what a
past client appears to have agreed to, so every signed submission stores a hash
of the document it was shown.
"""
import hashlib
import json

from app.models.forms import (
    FIELD_CHECKBOX,
    FIELD_CHOICE,
    FormAssignment,
    FormSubmission,
    FormTemplate,
)
from app.tenancy import TenantScope
from app.timeutil import utcnow


class IntakeError(Exception):
    """The submission cannot be accepted as given."""


def parse_schema(template: FormTemplate) -> list[dict]:
    """The template's question list, or an empty list for body-only documents."""
    if not template.schema_json:
        return []
    try:
        loaded = json.loads(template.schema_json)
    except json.JSONDecodeError as exc:
        raise IntakeError(f"Form {template.name!r} has an unreadable schema.") from exc
    if not isinstance(loaded, list):
        raise IntakeError(f"Form {template.name!r} schema must be a list of fields.")
    return loaded


def document_fingerprint(template: FormTemplate) -> str:
    """SHA-256 of everything the client is shown.

    Covers the name, the consent body, and the question list, so a change to any
    of them produces a different hash — which is what makes a past signature
    verifiable rather than merely recorded.
    """
    payload = json.dumps(
        {
            "name": template.name,
            "body": template.body or "",
            "schema": parse_schema(template),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_answers(template: FormTemplate, raw: dict) -> dict:
    """Check submitted answers against the template's schema.

    Unknown keys are dropped rather than stored: a form submission is client
    input, and keeping fields the schema does not describe would let anyone with
    the form URL write arbitrary content into the clinical record.
    """
    answers: dict = {}
    for field in parse_schema(template):
        key = field.get("key")
        if not key:
            continue
        value = raw.get(key)
        if field.get("type") == FIELD_CHECKBOX:
            answers[key] = bool(value)
            continue
        value = (value or "").strip() if isinstance(value, str) else value
        if field.get("required") and not value:
            raise IntakeError(f"{field.get('label', key)} is required.")
        if field.get("type") == FIELD_CHOICE and value:
            options = field.get("options") or []
            if value not in options:
                raise IntakeError(f"{value!r} is not an option for {key}.")
        answers[key] = value
    return answers


def pending_for(scope: TenantScope, client_id: int):
    return (
        scope.query(FormAssignment)
        .filter(
            FormAssignment.client_id == client_id,
            FormAssignment.completed_at.is_(None),
        )
        .order_by(FormAssignment.assigned_at)
    )


def completed_for(scope: TenantScope, client_id: int):
    return (
        scope.query(FormSubmission)
        .filter(FormSubmission.client_id == client_id)
        .order_by(FormSubmission.submitted_at.desc())
    )


def submit(
    scope: TenantScope,
    assignment: FormAssignment,
    raw_answers: dict,
    *,
    submitted_by_id: int | None = None,
    signature_name: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> FormSubmission:
    """Record a completed form, with a signature when the template needs one."""
    template = assignment.template
    if assignment.is_complete:
        raise IntakeError("This form has already been completed.")

    answers = validate_answers(template, raw_answers)

    signed_at = None
    fingerprint = None
    if template.requires_signature:
        name = (signature_name or "").strip()
        if not name:
            raise IntakeError("Type your full name to sign this document.")
        signed_at = utcnow()
        fingerprint = document_fingerprint(template)
        signature_name = name

    submission = FormSubmission(
        template_id=template.id,
        client_id=assignment.client_id,
        assignment_id=assignment.id,
        submitted_by_id=submitted_by_id,
        answers_json=json.dumps(answers, sort_keys=True),
        signed_at=signed_at,
        signature_name=signature_name if signed_at else None,
        document_hash=fingerprint,
        signature_ip=ip if signed_at else None,
        signature_user_agent=(user_agent or "")[:500] if signed_at else None,
    )
    scope.add(submission)
    assignment.completed_at = utcnow()
    scope.db.add(assignment)
    return submission


def signature_is_intact(submission: FormSubmission) -> bool:
    """Does the signed template still match what was signed?

    False means the template was edited after signing — the signature is still
    valid evidence of what the client agreed to, but the current template text is
    no longer that document. Surfacing this is the whole reason the hash exists.
    """
    if not submission.is_signed or not submission.document_hash:
        return False
    return submission.document_hash == document_fingerprint(submission.template)


def answers_of(submission: FormSubmission) -> dict:
    if not submission.answers_json:
        return {}
    try:
        return json.loads(submission.answers_json)
    except json.JSONDecodeError:
        return {}
