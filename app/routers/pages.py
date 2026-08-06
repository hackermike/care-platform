from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse

from app.auth.dependencies import optional_user
from app.models.user import User
from app.routers.auth import landing_path_for

router = APIRouter()


@router.get("/")
async def home(request: Request, user: User | None = Depends(optional_user)):
    """Root sends people where they belong: their surface, or the login page.

    There is no public marketing page here — the platform is white-labeled and
    sold to networks (docs/DECISIONS.md), so an anonymous visitor to a tenant
    host has nothing to see.
    """
    destination = landing_path_for(user) if user else "/login"
    return RedirectResponse(url=destination, status_code=status.HTTP_303_SEE_OTHER)
