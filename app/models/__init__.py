"""Importing this package registers every model on the shared Base."""
from app.models.tenant import Tenant  # noqa: F401
from app.models.user import User  # noqa: F401
