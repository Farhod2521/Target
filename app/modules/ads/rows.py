"""Writing into a launch's JSON columns so the session sees the write.

A JSON column is compared by value when the session flushes. A dict changed
in place is the same object as the one loaded, so nothing would be written:
every writer takes a deep copy first, and ``edited`` marks the column for the
cases that mutate a value already in hand.
"""

import copy
from typing import Any

from sqlalchemy.orm.attributes import flag_modified


def fresh(row: Any, field: str) -> Any:
    """The column's value as a private copy, set back on the row."""
    value = copy.deepcopy(getattr(row, field) or {})
    setattr(row, field, value)
    flag_modified(row, field)
    return value


def edited(row: Any, *fields: str) -> None:
    for field in fields:
        flag_modified(row, field)
