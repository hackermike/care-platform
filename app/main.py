from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse

import app.models  # noqa: F401 — registers models on Base
from app.auth.dependencies import NotAuthenticated, login_redirect
from app.db_init import run_migrations
from app.routers import auth, dashboards, pages
from app.security.csrf import CSRFError
from app.security.deps import csrf_protect
from app.security.middleware import CSRFTokenMiddleware
from app.tenancy import CrossTenantError, TenantResolutionError


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Alembic owns the schema; bring the DB to head on startup (needs Postgres up).
    run_migrations()
    yield


app = FastAPI(
    title="Care Platform",
    lifespan=lifespan,
    # CSRF is enforced app-wide, so a new state-changing route is protected by
    # default rather than by the author remembering to add a dependency.
    dependencies=[Depends(csrf_protect)],
)
app.add_middleware(CSRFTokenMiddleware)

app.include_router(pages.router)
app.include_router(auth.router)
app.include_router(dashboards.router)


@app.exception_handler(NotAuthenticated)
async def _not_authenticated(request: Request, exc: NotAuthenticated):
    """Send the browser to the login page; answer JSON callers with a 401.

    This is a server-rendered app, so redirecting is the default and JSON is the
    exception — the reverse would leave an expired session showing a raw 401
    body instead of a login form.
    """
    if request.headers.get("hx-request") == "true":
        # A 303 inside an HTMX swap would replace a fragment with the login page.
        # HX-Redirect tells HTMX to navigate the whole window instead.
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        response.headers["HX-Redirect"] = "/login"
        return response

    accept = request.headers.get("accept", "")
    if "application/json" in accept and "text/html" not in accept:
        return JSONResponse({"detail": "Not authenticated."}, status_code=401)
    return login_redirect(request)


@app.exception_handler(TenantResolutionError)
async def _tenant_unresolved(request: Request, exc: TenantResolutionError):
    """An unknown or inactive tenant looks like nothing at all.

    404 rather than 400: whether a given network exists on this platform is not
    something an unauthenticated caller should be able to probe.
    """
    return PlainTextResponse("Not found.", status_code=status.HTTP_404_NOT_FOUND)


@app.exception_handler(CrossTenantError)
async def _cross_tenant(request: Request, exc: CrossTenantError):
    """A tenant-boundary violation is a bug, not a user error — fail loudly."""
    return PlainTextResponse(
        "Internal error.", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
    )


@app.exception_handler(CSRFError)
async def _csrf_failed(request: Request, exc: CSRFError):
    return PlainTextResponse(
        "CSRF validation failed.", status_code=status.HTTP_403_FORBIDDEN
    )


@app.get("/healthz")
async def healthz():
    """Liveness probe. Deliberately tenant-free — load balancers have no host."""
    return {"status": "ok"}
