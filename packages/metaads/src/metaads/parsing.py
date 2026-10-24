"""Meta's answers turned into this package's models, failures included.

``model_validate`` raises pydantic's own error, and pydantic is an
implementation detail of this package. A caller that catches ``MetaError``
and is handed a ``ValidationError`` instead has no way to know it should
have caught something else, so what it gets is a traceback.

The connect callback is where that shows: a field Meta returns as a
number where the model expects a string turns the whole handshake into a
blank 500, at the end of a minute the customer has just spent on Meta's
own consent screens.

A shape change is still a failure - the module docstring in :mod:`dto`
says so and means it. It is just this package's failure to report, in the
class the boundary already promises.
"""

from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel, ValidationError

from metaads.errors import MetaAPIError


def parsed[T: BaseModel](model: type[T], row: Mapping[str, Any]) -> T:
    """One row as a model, or an error naming the field that stopped fitting.

    The field name is the whole value of this. "validation failed" sends
    somebody to read a payload; "min_daily_budget: input should be a valid
    string" is a one-line fix.
    """
    try:
        return model.model_validate(row)
    except ValidationError as exc:
        raise MetaAPIError(f"{model.__name__} - {_first(exc)}") from exc


def parsed_all[T: BaseModel](
    model: type[T], rows: Iterable[Mapping[str, Any]]
) -> list[T]:
    """A page of rows, all or nothing.

    All or nothing on purpose. A list of ad accounts with one silently
    missing is worse than a refusal: the customer connects, sees five of
    their six accounts, and has no reason to suspect the sixth exists.
    """
    return [parsed(model, row) for row in rows]


def _first(exc: ValidationError) -> str:
    """The first complaint, with its field. The rest are usually the same
    field seen from another angle, and one line is what fits in a log."""
    for error in exc.errors():
        where = ".".join(str(part) for part in error.get("loc", ()))
        return f"{where or 'payload'}: {error.get('msg', 'invalid')}"
    return "invalid payload"
