"""Response security headers.

Set on every response rather than per route, because the value of these headers
is that they hold everywhere — a page that forgets `X-Frame-Options` is the one
that gets framed.

**The CSP is deliberately not `default-src 'self'` yet.** `base.html` loads
Tailwind and HTMX from CDNs, and the inline `htmx:configRequest` handler needs
`'unsafe-inline'` for scripts. Writing a policy that permits all of that and
calling it done would be worse than useless: it would look like protection while
allowing exactly the injection it is meant to stop.

So the CDN hosts are named explicitly, and tightening this is tied to
precompiling Tailwind (`docs/DEPLOYMENT.md`). `CSP_REPORT_ONLY=1` runs the strict
policy in report-only mode so the violations can be seen before enforcing.
"""
import os

from starlette.middleware.base import BaseHTTPMiddleware

from app import config

# What the templates actually need today. Every entry here is a thing to remove,
# not a thing to keep.
_SCRIPT_SRC = "'self' 'unsafe-inline' https://cdn.tailwindcss.com https://unpkg.com"
_STYLE_SRC = "'self' 'unsafe-inline'"

CURRENT_CSP = "; ".join(
    [
        "default-src 'self'",
        f"script-src {_SCRIPT_SRC}",
        f"style-src {_STYLE_SRC}",
        "img-src 'self' data:",
        "font-src 'self' data:",
        # No third party should be receiving anything from a page rendering PHI.
        "connect-src 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "object-src 'none'",
    ]
)

# Where this is going once Tailwind is precompiled and the inline handler moves
# to a file. Run it report-only first.
TARGET_CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "object-src 'none'",
    ]
)

CSP_REPORT_ONLY = os.getenv("CSP_REPORT_ONLY", "").strip() == "1"


def security_headers() -> dict[str, str]:
    headers = {
        # Clickjacking. frame-ancestors in the CSP covers modern browsers;
        # this covers the rest.
        "x-frame-options": "DENY",
        "x-content-type-options": "nosniff",
        # Referrers must not carry a PHI-bearing path to another origin.
        "referrer-policy": "no-referrer",
        # Nothing here needs a camera, microphone, or location. Denying them
        # will need revisiting when in-product video lands (M6).
        "permissions-policy": "camera=(), microphone=(), geolocation=()",
        "cross-origin-opener-policy": "same-origin",
    }

    if CSP_REPORT_ONLY:
        headers["content-security-policy-report-only"] = TARGET_CSP
        headers["content-security-policy"] = CURRENT_CSP
    else:
        headers["content-security-policy"] = CURRENT_CSP

    # HSTS only where there is TLS to insist on. Sending it from a dev server on
    # localhost would pin the browser to HTTPS for a host that does not serve it.
    if not config.IS_DEV:
        headers["strict-transport-security"] = (
            "max-age=31536000; includeSubDomains"
        )

    return headers


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        for name, value in security_headers().items():
            # Do not clobber a header a route set deliberately.
            response.headers.setdefault(name, value)
        return response
