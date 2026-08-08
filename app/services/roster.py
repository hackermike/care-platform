"""Administrative roster operations: therapists, licences, and accounts.

The scale target is thousands of therapists per network (docs/DECISIONS.md), so
listing is paginated and searchable from the outset rather than after it hurts —
an admin page that loads every therapist works fine at fifty and falls over at
five thousand.
"""
from dataclasses import dataclass

from sqlalchemy import func, or_

from app.models.client import Client
from app.models.provider import TherapistLicense, TherapistProfile
from app.models.user import ROLE_THERAPIST, User
from app.tenancy import TenantScope
from app.timeutil import as_utc, utcnow

PAGE_SIZE = 25


class RosterError(Exception):
    """The requested roster change cannot be made."""


@dataclass(frozen=True)
class Page:
    items: list
    page: int
    pages: int
    total: int

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.pages


def paginate(query, page: int, size: int = PAGE_SIZE) -> Page:
    total = query.order_by(None).count()
    pages = max(1, -(-total // size))  # ceiling division
    page = max(1, min(page, pages))
    items = query.limit(size).offset((page - 1) * size).all()
    return Page(items=items, page=page, pages=pages, total=total)


def therapists(scope: TenantScope, *, search: str = "", page: int = 1) -> Page:
    """The tenant's therapists, newest last, optionally filtered by name or NPI."""
    query = scope.query(TherapistProfile)
    term = (search or "").strip()
    if term:
        like = f"%{term}%"
        query = query.filter(
            or_(
                TherapistProfile.name.ilike(like),
                TherapistProfile.npi.ilike(like),
                TherapistProfile.email.ilike(like),
            )
        )
    return paginate(query.order_by(TherapistProfile.name), page)


def caseload_sizes(scope: TenantScope, therapist_ids: list[int]) -> dict[int, int]:
    """Client counts per therapist, in one query.

    Fetched in bulk rather than per row: a roster page of 25 therapists should
    cost two queries, not twenty-six.
    """
    if not therapist_ids:
        return {}
    rows = (
        scope.query(Client.therapist_id, func.count(Client.id))
        .filter(Client.therapist_id.in_(therapist_ids))
        .group_by(Client.therapist_id)
        .all()
    )
    return dict(rows)


def create_therapist(
    scope: TenantScope,
    user: User,
    *,
    name: str,
    credentials: str | None = None,
    npi: str | None = None,
    license_number: str | None = None,
    practice_name: str | None = None,
    email: str | None = None,
) -> TherapistProfile:
    """Give a user account a clinical identity.

    A profile is separate from the account (see app/models/provider.py): this is
    what turns a login into someone who can appear on a superbill or a claim.
    """
    if user.role != ROLE_THERAPIST:
        raise RosterError(
            f"{user.email} has role {user.role!r}; only a therapist account can "
            "hold a clinical profile."
        )
    existing = (
        scope.query(TherapistProfile)
        .filter(TherapistProfile.user_id == user.id)
        .one_or_none()
    )
    if existing is not None:
        raise RosterError(f"{user.email} already has a clinical profile.")

    profile = TherapistProfile(
        user_id=user.id,
        name=name,
        credentials=credentials,
        npi=npi,
        license_number=license_number,
        practice_name=practice_name,
        email=email or user.email,
    )
    scope.add(profile)
    return profile


def add_license(
    scope: TenantScope,
    therapist: TherapistProfile,
    state: str,
    *,
    license_number: str | None = None,
    expires_on=None,
) -> TherapistLicense:
    """Record where a therapist may practise.

    Re-adding an existing state updates it rather than failing: an admin
    recording a renewal is doing the same action as recording the licence, and
    making them delete first would invite deleting the wrong row.
    """
    existing = (
        scope.query(TherapistLicense)
        .filter(
            TherapistLicense.therapist_id == therapist.id,
            TherapistLicense.state == state,
        )
        .one_or_none()
    )
    if existing is not None:
        existing.license_number = license_number or existing.license_number
        existing.expires_on = expires_on
        scope.db.add(existing)
        return existing

    licence = TherapistLicense(
        therapist_id=therapist.id,
        state=state,
        license_number=license_number,
        expires_on=expires_on,
    )
    scope.add(licence)
    return licence


def remove_license(scope: TenantScope, licence: TherapistLicense) -> None:
    scope.db.delete(licence)


def expiring_licenses(scope: TenantScope, *, within_days: int = 60) -> list:
    """Licences that have expired or will soon.

    The roster's one piece of genuine operational value: a lapsed licence means
    a therapist is seeing clients they may not lawfully see, and nobody notices
    until someone checks. Surfacing it is the point of storing expiry at all.
    """
    from datetime import timedelta

    horizon = utcnow() + timedelta(days=within_days)
    candidates = (
        scope.query(TherapistLicense)
        .filter(TherapistLicense.expires_on.isnot(None))
        .all()
    )
    # Compared in Python because SQLite hands back naive datetimes while Postgres
    # returns aware ones (see app/timeutil.py).
    return sorted(
        (lic for lic in candidates if as_utc(lic.expires_on) <= horizon),
        key=lambda lic: as_utc(lic.expires_on),
    )
