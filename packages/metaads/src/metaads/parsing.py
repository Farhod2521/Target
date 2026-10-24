"""Meta's answers turned into this package's models, failures included."""

from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel, ValidationError

from metaads.errors import MetaAPIError


def parsed[T: BaseModel](model: type[T], row: Mapping[str, Any]) -> T:
    """One row as a model, or an error naming the field that stopped fitting."""
    try:
        return model.model_validate(row)
    except ValidationError as exc:
        raise MetaAPIError(f"{model.__name__} - {_first(exc)}") from exc


def parsed_all[T: BaseModel](
    model: type[T], rows: Iterable[Mapping[str, Any]]
) -> list[T]:
    """A page of rows, all or nothing."""
    return [parsed(model, row) for row in rows]


def _first(exc: ValidationError) -> str:
    """The first complaint, with its field. The rest are usually the same
    field seen from another angle, and one line is what fits in a log."""
    for error in exc.errors():
        where = ".".join(str(part) for part in error.get("loc", ()))
        return f"{where or 'payload'}: {error.get('msg', 'invalid')}"
    return "invalid payload"
