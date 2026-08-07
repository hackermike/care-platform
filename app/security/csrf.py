"""CSRF protection for state-changing requests.

Signed double-submit: the token is issued in a cookie signed with SECRET_KEY and
must be echoed back in a form field or header. Signing the cookie is what makes
the double-submit pattern sound — an attacker on a sibling subdomain can write a
cookie, but cannot forge the signature, so they cannot make both halves agree.
"""
import secrets

from fastapi import Request
from fastapi.responses import Response
from itsdangerous import BadSignature, URLSafeSerializer

from app import config
from app.security.tokens import tokens_equal

_serializer = URLSafeSerializer(config.SECRET_KEY, salt="csrf")

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
HEADER_NAME = "x-csrf-token"


class CSRFError(Exception):
    """The request failed CSRF validation."""


def _sign(raw: str) -> str:
    return _serializer.dumps(raw)


def _unsign(signed: str) -> str | None:
    try:
        return _serializer.loads(signed)
    except BadSignature:
        return None


def generate_token() -> str:
    """Mint a raw CSRF token. Pair with `attach_token` on the response."""
    return secrets.token_urlsafe(32)


def attach_token(response: Response, raw: str) -> None:
    """Set the signed CSRF cookie for a token already rendered into the page."""
    response.set_cookie(
        config.CSRF_COOKIE,
        _sign(raw),
        # Readable by JS on purpose: HTMX echoes it into the header. The token's
        # value is not a secret to the user's own page, only to other origins.
        httponly=False,
        secure=config.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def issue_token(response: Response) -> str:
    """Mint a token and set its cookie in one step, for responses with no body
    to render it into (redirects)."""
    raw = generate_token()
    attach_token(response, raw)
    return raw


def token_for(request: Request) -> str | None:
    """The raw token from the request's cookie, if it carries a valid one."""
    signed = request.cookies.get(config.CSRF_COOKIE)
    return _unsign(signed) if signed else None


async def submitted_token(request: Request) -> str | None:
    """The token the client echoed back, from header or form field."""
    header = request.headers.get(HEADER_NAME)
    if header:
        return header
    content_type = request.headers.get("content-type", "")
    if content_type.startswith(
        ("application/x-www-form-urlencoded", "multipart/form-data")
    ):
        form = await request.form()
        value = form.get(config.CSRF_FIELD)
        return value if isinstance(value, str) else None
    return None


async def validate(request: Request) -> None:
    """Raise CSRFError unless the request carries a matching token pair."""
    if request.method.upper() in SAFE_METHODS:
        return
    expected = token_for(request)
    if not expected:
        raise CSRFError("Missing or invalid CSRF cookie.")
    submitted = await submitted_token(request)
    if not submitted:
        raise CSRFError("Missing CSRF token in request.")
    if not tokens_equal(expected, submitted):
        raise CSRFError("CSRF token mismatch.")
