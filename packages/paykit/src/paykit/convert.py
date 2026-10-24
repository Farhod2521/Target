"""The two conversions every adapter here needs, written once."""

from datetime import UTC, datetime
from decimal import Decimal

from paykit.refs import MinorUnits

MS: int = 1000


def to_units(*, amount_minor: MinorUnits, decimal_places: int) -> str:
    """``4_900_000`` at two places becomes ``"49000.00"``."""
    if decimal_places <= 0:
        return str(int(amount_minor))
    value = Decimal(int(amount_minor)) / (10**decimal_places)
    return f"{value:.{decimal_places}f}"


def to_minor(*, units: str, decimal_places: int) -> MinorUnits:
    """``"49000.00"`` at two places becomes ``4_900_000``."""
    scaled = Decimal(units) * (10**decimal_places)
    return MinorUnits(int(scaled.quantize(Decimal(1))))


def to_epoch_ms(value: datetime) -> int:
    """A moment as the milliseconds both protocols count in."""
    return int(value.timestamp() * MS)


def from_epoch_ms(value: int) -> datetime:
    """The other direction, always in UTC."""
    return datetime.fromtimestamp(value / MS, tz=UTC)


__all__ = ["MS", "from_epoch_ms", "to_epoch_ms", "to_minor", "to_units"]
