"""Opaque token generation and hashing.

Session tokens are stored hashed, for the same reason passwords are: a dump of
the sessions table must not hand the reader a set of live sessions. SHA-256 is
sufficient here (unlike passwords) because the token is 256 bits of entropy from
the start, so there is nothing to brute-force.
"""
import hashlib
import hmac
import secrets

TOKEN_BYTES = 32


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    """Constant-time comparison, so a mismatch leaks no timing signal."""
    return hmac.compare_digest(a, b)
