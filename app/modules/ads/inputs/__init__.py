"""What the launch API accepts, checked the way the Django forms checked it.

Each module takes a pydantic body, refuses it field by field through
:class:`Problems`, and hands the services the shape they take. Nothing here
writes: a check that passes answers with plain values.
"""

from app.common.exceptions import InputRefused


class Problems:
    """Sentences gathered per field; the first one for a field wins."""

    def __init__(self) -> None:
        self.found: dict[str, str] = {}

    def add(self, field: str, message: object) -> None:
        self.found.setdefault(field, str(message))

    def __contains__(self, field: str) -> bool:
        return field in self.found

    def drop(self, field: str) -> None:
        self.found.pop(field, None)

    def refuse(self) -> None:
        """Raise when anything was found; return quietly otherwise."""
        if self.found:
            raise InputRefused(self.found)


__all__ = ["Problems"]
