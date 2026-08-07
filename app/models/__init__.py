"""Importing this package registers every model on the shared Base."""
from app.models.appointment import Appointment  # noqa: F401
from app.models.audit import AuditLog  # noqa: F401
from app.models.client import Client  # noqa: F401
from app.models.note import ClinicalNote, NoteAddendum  # noqa: F401
from app.models.payment import Payment  # noqa: F401
from app.models.provider import TherapistLicense, TherapistProfile  # noqa: F401
from app.models.session import UserSession  # noqa: F401
from app.models.tenant import Tenant  # noqa: F401
from app.models.user import ROLES, User  # noqa: F401
