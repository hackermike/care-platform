"""Form-input parsing.

Routes take raw strings from HTML forms. Anything that parses — a datetime, a
decimal, a state code — can fail, and an unhandled parse failure is a 500 for
what is really a user error.

Each helper raises `FormError`, which `app.main` turns into a 400 carrying the
message. Validation lives here rather than in the routes so the same input means
the same thing everywhere, and so adding a field does not mean re-deciding how
malformed input behaves.
"""
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from breakout_core import cpt

# USPS state and territory codes. Kept here rather than validated against the
# licence table, because a client may live somewhere no therapist is licensed —
# that is a booking refusal (app/licensure.py), not a bad-input error.
US_STATES = frozenset(
    """AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO
    MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY
    DC AS GU MP PR VI""".split()
)


class FormError(ValueError):
    """Invalid user input. Becomes a 400, never a 500."""


def required_text(value: str | None, field: str, *, max_length: int = 200) -> str:
    text = (value or "").strip()
    if not text:
        raise FormError(f"{field} is required.")
    if len(text) > max_length:
        raise FormError(f"{field} is too long (max {max_length} characters).")
    return text


def optional_text(value: str | None, *, max_length: int = 200) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    if len(text) > max_length:
        raise FormError(f"Value is too long (max {max_length} characters).")
    return text


def parse_datetime(value: str | None, field: str = "Date and time") -> datetime:
    """Parse an ISO-8601 datetime from a form.

    A naive value is treated as UTC. That is right for storage but wrong for a
    therapist typing local time — the real fix is a per-user timezone, which
    belongs with the scheduling work rather than here.
    """
    text = required_text(value, field, max_length=64)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise FormError(f"{field} is not a valid date and time.") from exc
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def parse_date(value: str | None, field: str):
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except ValueError as exc:
        raise FormError(f"{field} is not a valid date.") from exc


def parse_money(value: str | None, field: str = "Amount", *, required: bool = True):
    """Parse a monetary amount into an exact Decimal.

    Rejects non-positive values: refunds are recorded with `is_refund`, not with
    a negative amount (see app/models/payment.py).
    """
    text = (value or "").strip().replace("$", "").replace(",", "")
    if not text:
        if required:
            raise FormError(f"{field} is required.")
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise FormError(f"{field} is not a valid amount.") from exc
    if amount <= 0:
        raise FormError(
            f"{field} must be positive. To reverse a payment, record a refund."
        )
    if amount.as_tuple().exponent < -2:
        raise FormError(f"{field} cannot be finer than cents.")
    return amount


def parse_state(value: str | None, *, required: bool = False) -> str | None:
    text = (value or "").strip().upper()
    if not text:
        if required:
            raise FormError("State is required.")
        return None
    if text not in US_STATES:
        raise FormError(f"{text} is not a valid US state or territory code.")
    return text


def parse_cpt(value: str | None) -> str:
    """Validate a CPT code against the shared catalog.

    Checked against `breakout_core.cpt` rather than a local list, so the platform
    and Breakout Billing cannot disagree about which codes exist.
    """
    text = (value or "").strip()
    if not text:
        return cpt.DEFAULT_CODE
    if text not in cpt.BY_CODE:
        raise FormError(f"{text} is not a CPT code this platform knows.")
    return text


def parse_choice(value: str | None, allowed, field: str, *, default=None):
    text = (value or "").strip()
    if not text and default is not None:
        return default
    if text not in allowed:
        raise FormError(f"{text or '(blank)'} is not a valid {field}.")
    return text
