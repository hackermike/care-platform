"""CSRF token provisioning.

Split deliberately from validation:

* **Provisioning** happens in middleware, which sees every response and can set
  the cookie once. It never reads the request body.
* **Validation** is a route dependency (`app.security.deps.csrf_protect`),
  because reading the form body belongs in the dependency layer where FastAPI
  caches it — doing it in `BaseHTTPMiddleware` consumes the stream before the
  handler can read it.

Every template can therefore rely on `request.state.csrf_token` existing.
"""
from starlette.middleware.base import BaseHTTPMiddleware

from app.security import csrf


class CSRFTokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        raw = csrf.token_for(request)
        issued = raw is None
        if issued:
            raw = csrf.generate_token()
        request.state.csrf_token = raw

        response = await call_next(request)
        # Only set the cookie when the request arrived without a valid one;
        # rotating it on every response would break in-flight form submissions.
        if issued:
            csrf.attach_token(response, raw)
        return response
