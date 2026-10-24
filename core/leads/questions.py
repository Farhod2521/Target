"""Putting a question back beside the answer somebody gave it."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Answer:
    """One question and what was written in it."""

    key: str
    label: str
    values: tuple[str, ...]

    @property
    def is_labelled(self) -> bool:
        """Whether a question was found for this answer."""
        return self.label != self.key


def label_answers(
    *,
    field_data: Iterable[Mapping[str, Any]],
    questions: Iterable[Mapping[str, Any]] = (),
) -> tuple[Answer, ...]:
    """Every answer, with the question it belongs to where one is known."""
    labels, choices = _catalogue(questions)
    rows: list[Answer] = []

    for row in field_data:
        key = str(row.get("name", "")).strip()
        if not key:
            continue
        values = _values(row.get("values"))
        if not values:
            continue
        rows.append(
            Answer(
                key=key,
                label=labels.get(key) or key,
                values=_spelled(values, choices.get(key, {})),
            )
        )

    return tuple(rows)


def _catalogue(
    questions: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """``{key: label}`` and ``{key: {option key: what it says}}``, in one walk."""
    labels: dict[str, str] = {}
    choices: dict[str, dict[str, str]] = {}

    for question in questions:
        key = str(question.get("key", "")).strip()
        if not key:
            continue
        label = str(question.get("label", "")).strip()
        if label:
            labels.setdefault(key, label)
        options = _options(question.get("options"))
        if options:
            choices.setdefault(key, options)

    return labels, choices


def _options(raw: object) -> dict[str, str]:
    """One question's choices as ``{key: what it says}``."""
    if not isinstance(raw, list):
        return {}

    found: dict[str, str] = {}

    for option in raw:
        if not isinstance(option, Mapping):
            continue
        key = str(option.get("key", "")).strip()
        value = str(option.get("value", "")).strip()
        if key and value:
            found.setdefault(key, value)

    return found


def _spelled(values: tuple[str, ...], options: Mapping[str, str]) -> tuple[str, ...]:
    """Picked options traded back for their wording, per question."""
    if not options:
        return values
    return tuple(options.get(value, value) for value in values)


def _values(raw: object) -> tuple[str, ...]:
    """The answers to one question, blanks dropped."""
    if not isinstance(raw, list):
        return ()
    return tuple(str(value).strip() for value in raw if str(value).strip())


CUSTOM_TYPE = "CUSTOM"


def form_signature(questions: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    """What a form asks, as strings two forms can be compared by."""
    built: list[str] = []
    for question in questions:
        kind = str(question.get("type", "")).strip().upper()
        if not kind:
            continue
        if kind != CUSTOM_TYPE:
            built.append(kind)
            continue
        label = str(question.get("label", "")).strip().casefold()
        built.append(f"{CUSTOM_TYPE}:{label}")
    return tuple(built)


__all__ = ["Answer", "form_signature", "label_answers"]
