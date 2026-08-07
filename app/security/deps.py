"""Security dependencies applied application-wide."""
from fastapi import Request

from app.security import csrf


async def csrf_protect(request: Request) -> None:
    """Validate CSRF on every state-changing request.

    Registered as a global dependency in `app.main`, so protection is opt-out by
    exception rather than opt-in by memory. Safe methods return immediately.
    """
    await csrf.validate(request)
