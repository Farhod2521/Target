"""A text the office wrote, put into the other languages, and its check.

The office writes an answer in one language - what an owner reads when Meta
refuses them, or the steps the assistant gives for a known problem. The
model is asked for every other language in one call and answers in the
shape below. The answer is used only if it is the same text: every language
once, every field there, the same ``[[links]]``, and as many numbered steps
and list lines as the source. A translation that lost a step or a link
would send a person the wrong way, so it is refused whole.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Final

from pydantic import BaseModel, Field

LINK: Final = re.compile(r"\[\[([^\[\]]+)\]\]")
STEP: Final = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)
BULLET: Final = re.compile(r"^\s*[-*•]\s", re.MULTILINE)


class TranslatedField(BaseModel):
    name: str = Field(description="The field's name, exactly as given.")
    text: str = Field(description="The field's text, translated.")


class TranslatedLanguage(BaseModel):
    language: str = Field(description="The language code, exactly as given.")
    fields: list[TranslatedField]


class OfficeTranslation(BaseModel):
    """Every target language, each once."""

    languages: list[TranslatedLanguage]


class TranslationMismatchError(Exception):
    """The answer is not the same text as the one sent."""


def shape(text: str) -> tuple[tuple[str, ...], int, int]:
    """What a translation must keep: the links, the steps, the list lines."""
    return (
        tuple(sorted(LINK.findall(text))),
        len(STEP.findall(text)),
        len(BULLET.findall(text)),
    )


def checked(
    answer: OfficeTranslation,
    *,
    languages: Sequence[str],
    source: Mapping[str, str],
) -> dict[str, dict[str, str]]:
    """Each target language's fields, or ``TranslationMismatchError``."""
    found: dict[str, dict[str, str]] = {}
    for item in answer.languages:
        if item.language in found or item.language not in languages:
            raise TranslationMismatchError(f"unexpected language {item.language!r}")
        fields = {field.name: field.text.strip() for field in item.fields}
        if len(fields) != len(item.fields) or set(fields) != set(source):
            raise TranslationMismatchError(f"{item.language}: fields differ")
        for name, text in fields.items():
            if not text:
                raise TranslationMismatchError(f"{item.language}: empty {name}")
            if shape(text) != shape(source[name]):
                raise TranslationMismatchError(
                    f"{item.language}: {name} lost a link, a step or a list line"
                )
        found[item.language] = fields
    if set(found) != set(languages):
        raise TranslationMismatchError("a language is missing")
    return found


__all__ = [
    "OfficeTranslation",
    "TranslatedField",
    "TranslatedLanguage",
    "TranslationMismatchError",
    "checked",
    "shape",
]
