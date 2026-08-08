"""How money is stored, and why the protocol boundary looks different.

**Storage is exact.** Every monetary column is `Numeric(10, 2)`, which
SQLAlchemy hands back as `Decimal`. Binary floats cannot represent most cent
values, and errors accumulate across sums — tolerable in a solo superbill tool,
not in a platform that will submit insurance claims and reconcile remittances
against them (docs/DECISIONS.md).

**`breakout-core` speaks float.** Its Protocols declare `amount: float`,
`fee: float | None`, and its money math sums them; mixing `Decimal` and `float`
in `sum()` raises TypeError. So the shared columns are stored under a private
name (`fee_amount`) and exposed as float through a property carrying the
protocol's name (`fee`).

That keeps both halves honest: the database stays exact, and `breakout-core`
gets exactly the shape it documents. The conversion happens in one place, and
the direction is deliberate — floats are derived for presentation and for the
shared library, never written back as the source of truth.

If `breakout-core` later moves to `Decimal`, these properties are the only thing
that has to change.
"""
from decimal import Decimal

from sqlalchemy import Numeric

# 10 digits with 2 after the point: up to 99,999,999.99, which is far beyond any
# single therapy charge and leaves headroom for aggregate columns later.
Money = Numeric(10, 2)


def to_float(value: Decimal | None) -> float | None:
    """Decimal -> float, for the breakout-core protocol surface only."""
    return None if value is None else float(value)


def to_decimal(value) -> Decimal | None:
    """Parse user or API input into an exact Decimal.

    Goes through `str()` so a float argument does not carry its binary
    representation error into storage: Decimal(0.1) is 0.1000000000000000055…,
    while Decimal(str(0.1)) is exactly 0.1.
    """
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
