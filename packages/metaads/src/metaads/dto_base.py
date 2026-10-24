"""The shared base and coercions every row module builds on."""

from pydantic import BaseModel, ConfigDict


class MetaDTO(BaseModel):
    """Shared config. Frozen: these cross layers and are compared."""

    model_config = ConfigDict(frozen=True, extra="ignore")


def _minor_units(value: str | int | None) -> int | None:
    """Meta's money string, as an int in the account's minor units."""
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _text(value: object) -> str:
    """A string field of somebody else's JSON, or empty."""
    return value if isinstance(value, str) else ""
