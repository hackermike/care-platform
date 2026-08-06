"""Runtime configuration, read from the environment.

Secrets never have usable defaults in production. SECRET_KEY falls back to a
development value only when APP_ENV is "dev"; anywhere else a missing key is a
startup error rather than a silently insecure deployment.
"""
import os

APP_ENV = os.getenv("APP_ENV", "dev")
IS_DEV = APP_ENV == "dev"

_DEV_SECRET = "dev-only-change-me"


def _secret_key() -> str:
    key = os.getenv("SECRET_KEY")
    if key and key != _DEV_SECRET:
        return key
    if IS_DEV:
        return _DEV_SECRET
    raise RuntimeError(
        "SECRET_KEY must be set to a real random value when APP_ENV is not 'dev'."
    )


SECRET_KEY = _secret_key()

# Session cookie. Sessions are server-side rows (see app/models/session.py); the
# cookie carries only an opaque token, so revocation is immediate and real.
SESSION_COOKIE = "care_session"
SESSION_IDLE_TIMEOUT_MINUTES = int(os.getenv("SESSION_IDLE_TIMEOUT_MINUTES", "30"))
SESSION_ABSOLUTE_TIMEOUT_HOURS = int(os.getenv("SESSION_ABSOLUTE_TIMEOUT_HOURS", "12"))

CSRF_COOKIE = "care_csrf"
CSRF_FIELD = "csrf_token"

# Cookies are Secure everywhere except local dev, which has no TLS.
COOKIE_SECURE = not IS_DEV

# Tenant resolution. Requests are mapped to a tenant by host subdomain
# (acme.example.com -> "acme"). Local dev has no subdomains, so a default slug
# stands in. See app/tenancy.py.
TENANT_HOST_SUFFIX = os.getenv("TENANT_HOST_SUFFIX", "")
DEV_DEFAULT_TENANT_SLUG = os.getenv("DEV_DEFAULT_TENANT_SLUG", "demo")

# Failed-login throttling, per (tenant, email).
LOGIN_MAX_ATTEMPTS = int(os.getenv("LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_LOCKOUT_MINUTES = int(os.getenv("LOGIN_LOCKOUT_MINUTES", "15"))
