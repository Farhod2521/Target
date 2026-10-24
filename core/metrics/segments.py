"""How one slice of a segmented day is named."""

from typing import Final

SEPARATOR: Final = "|"

UNKNOWN: Final = "unknown"


def join_segment(*parts: str) -> str:
    """One stored value from the parts of a cut."""
    if not parts:
        raise ValueError("a segment needs at least one part")

    cleaned = []
    for part in parts:
        text = part.strip()
        if SEPARATOR in text:
            raise ValueError(f"a segment part may not contain {SEPARATOR!r}: {part!r}")
        cleaned.append(text or UNKNOWN)
    return SEPARATOR.join(cleaned)


def split_segment(value: str) -> tuple[str, ...]:
    """The parts back out, in the order they were joined."""
    return tuple(value.split(SEPARATOR))
