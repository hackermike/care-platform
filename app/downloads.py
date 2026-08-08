"""Safe file downloads.

Superbills and statements are named after the client, and a client's name is
user-controlled data. Interpolating it straight into a `Content-Disposition`
header lets a quote character break out of the quoted filename and inject
further header parameters:

    last_name = 'Rivera" ; evil="1'
    -> attachment; filename="superbill-rivera" ; evil="1-2026-01-01.pdf"

Beyond parameter injection, an attacker-chosen filename is the basis of
reflected-file-download attacks: a document that arrives named `setup.bat` or
`invoice.html` is a social-engineering primitive regardless of its contents.

So the filename is built from an allowlist rather than escaped. Escaping invites
arguments about which characters matter; an allowlist does not.
"""
import re

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_LENGTH = 100


def safe_filename(name: str, *, fallback: str = "download") -> str:
    """Reduce an arbitrary string to characters that need no quoting."""
    cleaned = _SAFE.sub("-", name or "").strip("-.")
    cleaned = cleaned[:_MAX_LENGTH].strip("-.")
    return cleaned or fallback


def attachment_headers(filename: str, *, fallback: str = "download") -> dict[str, str]:
    """Content-Disposition for a downloaded attachment.

    The filename is sanitised, so the surrounding quotes cannot be escaped.
    """
    safe = safe_filename(filename, fallback=fallback)
    return {"content-disposition": f'attachment; filename="{safe}"'}
