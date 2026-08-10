"""Runtime configuration, read from the environment.

**Everything here fails closed.** `APP_ENV` defaults to production, so a variable
someone forgot to set cannot silently turn on development behaviour; secrets and
the tenant host suffix are startup errors rather than quietly insecure defaults.

The dev relaxations are deliberately few and all gated on `IS_DEV`: cookies are
not marked `Secure` (no local TLS), a placeholder `SECRET_KEY` is accepted, tenant
resolution falls back to a default slug, and emailed links use `DEV_BASE_URL`.
"""
import os

# Defaults to production, not dev. An omitted APP_ENV should not quietly relax
# cookie flags, accept a placeholder SECRET_KEY, enable the single-tenant host
# fallback, and point emailed links at localhost — which is exactly what a "dev"
# default did. Development opts in explicitly; `.env.example`, `start.sh` (via
# .env), the test suite, and the smoke script all set it.
APP_ENV = os.getenv("APP_ENV", "production").strip() or "production"
IS_DEV = APP_ENV == "dev"

_DEV_SECRET = "dev-only-change-me"


def _secret_key() -> str:
    key = os.getenv("SECRET_KEY")
    if key and key != _DEV_SECRET:
        return key
    if IS_DEV:
        return _DEV_SECRET
    raise RuntimeError(
        "SECRET_KEY must be set to a real random value when APP_ENV is not "
        "'dev'. For local development set APP_ENV=dev (see .env.example); "
        "in a real environment supply a random secret from your secrets manager."
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
def _tenant_host_suffix() -> str:
    """The DNS suffix tenants live under.

    Required outside dev. Checking it at import means a misconfigured deployment
    fails loudly on startup; deferring it to the first emailed link would fail
    only for addresses that have an account, which is an account-existence
    oracle wearing a 500.
    """
    suffix = os.getenv("TENANT_HOST_SUFFIX", "").strip()
    if suffix or IS_DEV:
        return suffix
    raise RuntimeError(
        "TENANT_HOST_SUFFIX must be set when APP_ENV is not 'dev'. Tenants "
        "resolve by host subdomain, and emailed links are built from it. "
        "For local development set APP_ENV=dev (see .env.example)."
    )


TENANT_HOST_SUFFIX = _tenant_host_suffix()
DEV_DEFAULT_TENANT_SLUG = os.getenv("DEV_DEFAULT_TENANT_SLUG", "demo")

# The origin used to build emailed links. Never derived from the request Host
# header: an attacker who sends `Host: evil.example` with a reset request would
# otherwise have the victim's link point at their server, which is a password
# reset poisoning attack. In dev there is no wildcard DNS, so a fixed value
# stands in.
DEV_BASE_URL = os.getenv("DEV_BASE_URL", "http://localhost:8000")

# Failed-login throttling, per (tenant, email).
LOGIN_MAX_ATTEMPTS = int(os.getenv("LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_LOCKOUT_MINUTES = int(os.getenv("LOGIN_LOCKOUT_MINUTES", "15"))
