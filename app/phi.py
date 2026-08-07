"""Recording PHI access.

`CLAUDE.md` lists audit logging of PHI access as a non-negotiable. M1 built the
log and covered authentication; M3 is where actual clinical data starts being
read, so this is where the obligation becomes real.

The rule these helpers exist to enforce: **every route that renders a client's
clinical or billing data records that it did so, and never records the data
itself.** `detail` carries record identifiers and the shape of the access, never
a name, a diagnosis, or a note body — an audit log is retained longer and read
more widely than the records it describes, so PHI in it widens exposure rather
than narrowing it.
"""
from fastapi import Request
from sqlalchemy.orm import Session

from app import audit
from app.models.audit import ACTION_PHI_MODIFIED, ACTION_PHI_VIEWED
from app.models.user import User

RESOURCE_CLIENT = "client"
RESOURCE_APPOINTMENT = "appointment"
RESOURCE_NOTE = "clinical_note"
RESOURCE_PAYMENT = "payment"
RESOURCE_SUPERBILL = "superbill"


def viewed(
    db: Session,
    user: User,
    resource_type: str,
    resource_id: int | str,
    *,
    request: Request | None = None,
    detail: str | None = None,
) -> None:
    """Record that `user` read a PHI record."""
    audit.record(
        db,
        ACTION_PHI_VIEWED,
        tenant_id=user.tenant_id,
        user_id=user.id,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail,
        request=request,
    )


def modified(
    db: Session,
    user: User,
    resource_type: str,
    resource_id: int | str,
    *,
    request: Request | None = None,
    detail: str | None = None,
) -> None:
    """Record that `user` created or changed a PHI record.

    `detail` should say *what kind* of change ("signed", "status=completed"),
    never the content of it.
    """
    audit.record(
        db,
        ACTION_PHI_MODIFIED,
        tenant_id=user.tenant_id,
        user_id=user.id,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail,
        request=request,
    )
