"""Putting a question back beside the answer somebody gave it.

An answer sheet arrives keyed by field name - ``full_name``, ``q2`` - and
the question that produced ``q2`` is stored on the form, not on the lead.
The two have to be read together or a screen shows a column of keys:
``q2`` above "Chilonzor", where the advertiser wrote "Qaysi tumandasiz?".

**Answer order, not question order.** The pairing walks what the person
answered and looks the question up, rather than walking the questions and
finding answers. A form's questions can outnumber the answers - somebody
skipped one, or the form was edited into a new version after these leads
arrived - and the second reading would show empty rows for questions this
person was never asked.

**The answer needs the same treatment as the question.** A multiple-choice
answer arrives as the key of the option that was picked, not as the words
on it: ``q3_o1`` where the person tapped "4-6 kishi". Those keys are ours,
written into the form when it was created so that answers can be counted
by option rather than by wording, and they are unreadable to the one
audience this screen has. The form carries the pairing back, so the option
text is looked up exactly like the question text is - and falls back the
same way, to what arrived, because an option a form does not describe is
still an identifier somebody can match in Ads Manager.

Django-free, like everything here, which is what lets the rules below be
tested without a form, a lead or a database.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Answer:
    """One question and what was written in it.

    ``label`` falls back to the raw key rather than to an empty string. A
    key is poor labelling and it is still an identifier somebody can match
    against the form in Ads Manager; a blank row is a screen quietly
    dropping an answer.
    """

    key: str
    label: str
    values: tuple[str, ...]

    @property
    def is_labelled(self) -> bool:
        """Whether a question was found for this answer.

        False for a standard question the provider named but did not
        describe, and for an answer to a form we never mirrored. Both are
        normal; a screen may want to show them differently.
        """
        return self.label != self.key


def label_answers(
    *,
    field_data: Iterable[Mapping[str, Any]],
    questions: Iterable[Mapping[str, Any]] = (),
) -> tuple[Answer, ...]:
    """Every answer, with the question it belongs to where one is known.

    ``questions`` is the form's own list as the provider holds it. Empty is
    a normal case rather than a degraded one - a lead can arrive through a
    form nothing here has mirrored - and produces answers labelled by their
    keys.

    An answer with no values is left out. A question somebody skipped is
    not a question they answered with nothing, and a blank row invites the
    reading that they wrote an empty string.
    """
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
    """``{key: label}`` and ``{key: {option key: what it says}}``, in one walk.

    One pass and not two because the argument is an iterable: a caller
    handing this a generator would find the second walk over an empty one,
    and the failure would be silent - labelled questions with unreadable
    answers, which is the exact bug this is here to fix.

    A standard question carries neither half - the provider prefills and
    labels it in the person's own language, so there is nothing of ours to
    store. It is skipped rather than filled with a placeholder, which is
    what leaves the raw key visible instead of an invented word.
    """
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
    """One question's choices as ``{key: what it says}``.

    Empty for a free-text question, and empty too for a form whose options
    carry no keys of their own - forms built by hand in Ads Manager are
    usually those, and the provider then sends the words themselves, which
    need no translating back.
    """
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
    """Picked options traded back for their wording, per question.

    The lookup is scoped to the question that was asked, never to every
    option on the form. Two questions are free to key their options the
    same way - ours do, ``q2_o1`` and ``q3_o1`` differ only by which
    question owns them - and a form-wide table would answer one question
    with another's wording.

    A value that matches nothing is kept as it arrived. It is either a
    typed answer, which is already words, or an option this form does not
    describe, and inventing wording for the second would be worse than
    showing the key.
    """
    if not options:
        return values
    return tuple(options.get(value, value) for value in values)


def _values(raw: object) -> tuple[str, ...]:
    """The answers to one question, blanks dropped."""
    if not isinstance(raw, list):
        return ()
    return tuple(str(value).strip() for value in raw if str(value).strip())


# What a question the provider does not name is called on the wire, and the
# one type whose wording is the advertiser's rather than the platform's.
# Every other type is prefilled and titled in the reader's own language, so
# the type alone identifies it; a custom question is identified only by
# what it asks.
CUSTOM_TYPE = "CUSTOM"


def form_signature(questions: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    """What a form asks, as strings two forms can be compared by.

    Written for one question: *does a form that already asks exactly this
    exist?* A provider that refuses to delete a lead form makes that
    question worth asking before every campaign - a form built to ask the
    same four things as one already on the page is an undeletable duplicate
    of it.

    **Ordered, and the order is part of the answer.** Two forms asking a
    name and a telephone number in opposite orders are not the same form to
    the person filling one in on a phone, and a recommendation that treated
    them as interchangeable would quietly reorder somebody's questions. The
    cost of being strict is a badge that does not appear; the cost of being
    loose is a form that asks in an order nobody chose.

    A standard question is its type and nothing else - the provider
    prefills and titles it, so there is no wording of ours to compare. A
    custom one is its type and its label, folded for case, because "Qaysi
    filial?" and "qaysi filial?" are one question asked twice.

    A question with no type at all is skipped rather than given a
    placeholder. It cannot be matched against anything, and a signature
    that invented a slot for it would make two forms differ over a field
    neither of them describes.
    """
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
