"""The shared base and coercions every row module builds on.

A leaf on purpose: the row modules import this, ``dto`` imports the row
modules, and nothing here imports anything of ours - which is what keeps
the import graph a tree however a caller enters it.
"""

from pydantic import BaseModel, ConfigDict


class MetaDTO(BaseModel):
    """Shared config. Frozen: these cross layers and are compared."""

    model_config = ConfigDict(frozen=True, extra="ignore")


def _minor_units(value: str | int | None) -> int | None:
    """Meta's money string, as an int in the account's minor units.

    Shared by the account and the campaign rows, which is why it lives
    here rather than in either of their modules.
    """
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _text(value: object) -> str:
    """A string field of somebody else's JSON, or empty.

    Every accessor on :class:`creative_rows.CreativeRow` goes through
    this, and the lead form's privacy URL does too. Meta answers a story
    spec with whatever the advertiser put in it, and a headline that
    arrives as a number - which is what a creative named "2026" does -
    would otherwise reach a ``CharField`` as an integer and fail the
    write for the whole account rather than for the one row.
    """
    return value if isinstance(value, str) else ""
