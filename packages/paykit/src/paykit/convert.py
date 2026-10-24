"""The two conversions every adapter here needs, written once.

Both are arithmetic on values that are already exact, and neither reads a
clock or a currency table. They live outside the adapters because getting
either one wrong is silent: an amount a hundredfold out is accepted by the
provider, and a timestamp in seconds where milliseconds were expected is a
transaction dated 1970.
"""

from datetime import UTC, datetime
from decimal import Decimal

from paykit.refs import MinorUnits

# Milliseconds, because both protocols in this package count in them.
MS: int = 1000


def to_units(*, amount_minor: MinorUnits, decimal_places: int) -> str:
    """``4_900_000`` at two places becomes ``"49000.00"``.

    A string rather than a float, and via :class:`~decimal.Decimal` rather
    than division: this value goes into a signature that the provider
    recomputes, and a float's shortest representation is not the same
    digits on every machine.

    Zero places returns the integer with no separator - a currency with no
    subdivision has none to print, and a trailing dot is a parse error at
    the other end.
    """
    if decimal_places <= 0:
        return str(int(amount_minor))
    value = Decimal(int(amount_minor)) / (10**decimal_places)
    return f"{value:.{decimal_places}f}"


def to_minor(*, units: str, decimal_places: int) -> MinorUnits:
    """``"49000.00"`` at two places becomes ``4_900_000``.

    The inverse of :func:`to_units`, for the one provider that quotes
    whole currency on the way back in. Quantised rather than truncated: a
    provider that sends ``"49000.005"`` is sending a value that cannot
    exist, and rounding it is closer to the truth than dropping a digit.

    Raises :class:`~decimal.InvalidOperation` on a body that is not a
    number, which the caller turns into a malformed callback - never into
    a zero, which would be an invoice settled for nothing.
    """
    scaled = Decimal(units) * (10**decimal_places)
    return MinorUnits(int(scaled.quantize(Decimal(1))))


def to_epoch_ms(value: datetime) -> int:
    """A moment as the milliseconds both protocols count in.

    The datetime must be timezone-aware. A naive one would be read as the
    machine's local time, which is how a transaction gets stamped five
    hours off on one server and not on another.
    """
    return int(value.timestamp() * MS)


def from_epoch_ms(value: int) -> datetime:
    """The other direction, always in UTC.

    UTC and not a local zone, because everything stored in this system is
    UTC and a provider's own offset is not ours to guess.
    """
    return datetime.fromtimestamp(value / MS, tz=UTC)


__all__ = ["MS", "from_epoch_ms", "to_epoch_ms", "to_minor", "to_units"]
