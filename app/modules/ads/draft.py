from typing import Any, Final

from app.modules.ads.constants import (
    CUSTOM_QUESTION_PREFIX,
    PHONE_QUESTION_LABEL,
    QUESTION_TYPES,
    TYPED_FIRST_NAME_LABEL,
    TYPED_NAME_LABEL,
    TYPED_PHONE_LABEL,
    DraftSection,
)
from app.modules.leads.constants import QUESTION_LABELS
from core.leads import contact_kind

SECTIONS: tuple[str, ...] = tuple(DraftSection.values)
SOURCES_KEY: Final = "sources"
AUDIENCE_MODE: Final = "audience_mode"
PLACEMENT_MODE: Final = "placement_mode"
LEAD_FORM: Final = "lead_form"
CAMPAIGN_TYPE: Final = "campaign_type"
CONVERSION_EVENT: Final = "conversion_event"
URL_TAGS: Final = "url_tags"
BY_AI: Final = "ai"
BY_OWNER: Final = "owner"


def empty_section() -> dict[str, Any]:
    return {"ai": None, "chosen": None, "regenerated": False}


def empty_draft() -> dict[str, Any]:
    return {
        **{name: empty_section() for name in SECTIONS},
        "adjustments": [],
        SOURCES_KEY: {},
    }


def is_written(draft: dict[str, Any] | None) -> bool:
    if not draft:
        return False
    return any(
        isinstance(draft.get(name), dict)
        and (draft[name].get("ai") is not None or draft[name].get("chosen") is not None)
        for name in SECTIONS
    )


def section(draft: dict[str, Any], name: str) -> dict[str, Any]:
    if not isinstance(draft.get(name), dict):
        draft[name] = empty_section()
    return draft[name]


def proposal(draft: dict[str, Any], name: str) -> Any:
    return section(draft, name).get("ai")


def chosen(draft: dict[str, Any], name: str) -> Any:
    part = section(draft, name)
    picked = part.get("chosen")
    return part.get("ai") if picked is None else picked


def propose(draft: dict[str, Any], name: str, value: Any) -> None:
    part = section(draft, name)
    part["ai"] = value
    part["chosen"] = None


def choose(draft: dict[str, Any], name: str, value: Any) -> None:
    section(draft, name)["chosen"] = value


PHONE: Final = "phone"
NAME_KINDS: Final = frozenset({"full_name", "first_name", "last_name"})


def with_phone(questions: list[Any]) -> list[Any]:
    rows = [item for item in questions if isinstance(item, dict)]
    if not rows or any(
        str(item.get("kind", "")) == PHONE or typed_contact(item) == PHONE
        for item in rows
    ):
        return rows
    after = max(
        (
            index + 1
            for index, item in enumerate(rows)
            if str(item.get("kind", "")) in NAME_KINDS
            or typed_contact(item) == "full_name"
        ),
        default=0,
    )
    phone = {"kind": PHONE, "label": str(PHONE_QUESTION_LABEL), "options": []}
    return [*rows[:after], phone, *rows[after:]]


def typed_contact(question: dict[str, Any]) -> str:
    if str(question.get("kind", "")) in QUESTION_TYPES or question.get("options"):
        return ""
    return contact_kind(str(question.get("label", ""))) or ""


def standard_contacts(questions: list[Any]) -> list[Any]:
    rows = [item for item in questions if isinstance(item, dict)]
    asked = {str(item.get("kind", "")) for item in rows}
    built: list[dict[str, Any]] = []
    for item in rows:
        kind = typed_contact(item)
        if not kind:
            built.append(item)
        elif kind not in asked:
            asked.add(kind)
            built.append({"kind": kind, "label": _standard_label(kind), "options": []})
    if "full_name" in asked:
        built = [item for item in built if item.get("kind") not in _NAME_PARTS]
    return built


_NAME_PARTS: Final = frozenset({"first_name", "last_name"})
FORM_VARIANTS: Final = "form_variants"


def form_variants(draft: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    value = (draft or {}).get(FORM_VARIANTS)
    return value if isinstance(value, dict) else {}


def keep_form_variant(draft: dict[str, Any], depth: str, value: dict[str, Any]) -> None:
    draft[FORM_VARIANTS] = {**form_variants(draft), depth: value}


def drop_form_variants(draft: dict[str, Any]) -> None:
    draft.pop(FORM_VARIANTS, None)


def model_questions(questions: list[Any], *, limit: int) -> list[dict[str, Any]]:
    rows = with_phone(standard_contacts(questions))
    while len(rows) > limit:
        last = max(
            (index for index, item in enumerate(rows) if item.get("kind") != PHONE)
        )
        rows = rows[:last] + rows[last + 1 :]
    rows = typed_by_hand(rows)
    built: list[dict[str, Any]] = []
    number = 0
    for item in rows:
        if str(item.get("kind", "")) in QUESTION_TYPES:
            built.append(item)
            continue
        number += 1
        built.append({**item, "kind": f"{CUSTOM_QUESTION_PREFIX}{number}"})
    return built


def typed_by_hand(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The name and the telephone asked as typed questions, not prefilled.

    The name parts become one question where the first of them stood: a
    first name alone is asked as one, anything else as a whole name.
    """
    names = {str(item.get("kind", "")) for item in questions} & NAME_KINDS
    name_label = TYPED_FIRST_NAME_LABEL if names == {"first_name"} else TYPED_NAME_LABEL
    built: list[dict[str, Any]] = []
    named = False
    for item in questions:
        kind = str(item.get("kind", ""))
        if kind in NAME_KINDS:
            if not named:
                named = True
                built.append(_typed(name_label))
        elif kind == PHONE:
            built.append(_typed(TYPED_PHONE_LABEL))
        else:
            built.append(item)
    return built


def _typed(label: str) -> dict[str, Any]:
    return {"kind": "custom", "label": label, "options": []}


def _standard_label(kind: str) -> str:
    if kind == PHONE:
        return str(PHONE_QUESTION_LABEL)
    return str(QUESTION_LABELS.get(QUESTION_TYPES[kind], ""))


FALLBACK_PICKS: Final = 6
STAND_IN: Final = "stand_in"


def ai_picks(proposed: list[Any]) -> list[dict[str, str]]:
    rows = [item for item in proposed if isinstance(item, dict)]
    picked = [item for item in rows if item.get("recommended")] or rows[:FALLBACK_PICKS]
    return [
        {
            "label": str(item.get("label", "")),
            "query": str(item.get("query", "")),
            "external_id": "",
        }
        for item in picked
    ]


def creatives(draft: dict[str, Any]) -> list[dict[str, Any]]:
    picked = chosen(draft, DraftSection.CREATIVE)
    if isinstance(picked, dict):
        return [picked]
    if isinstance(picked, list):
        return [item for item in picked if isinstance(item, dict)]
    return []


def mark_regenerated(draft: dict[str, Any], name: str) -> None:
    section(draft, name)["regenerated"] = True


def was_regenerated(draft: dict[str, Any], name: str) -> bool:
    return bool(section(draft, name).get("regenerated"))


def set_unconfirmed(draft: dict[str, Any], name: str, items: list[Any]) -> None:
    section(draft, name)["unconfirmed"] = items


def unconfirmed(draft: dict[str, Any], name: str) -> list[Any]:
    found = section(draft, name).get("unconfirmed")
    return found if isinstance(found, list) else []


def set_copy_review(
    draft: dict[str, Any], problems: list[list[dict[str, str]]]
) -> None:
    section(draft, DraftSection.CREATIVE)["review"] = problems


def set_adjustments(draft: dict[str, Any], notes: list[dict[str, str]]) -> None:
    draft["adjustments"] = notes


def set_launch_note(draft: dict[str, Any], code: str) -> None:
    draft["launch_note"] = code


def launch_note(draft: dict[str, Any]) -> str:
    found = draft.get("launch_note")
    return found if isinstance(found, str) else ""


def adjustments(draft: dict[str, Any]) -> list[dict[str, str]]:
    found = draft.get("adjustments")
    return found if isinstance(found, list) else []


def source(draft: dict[str, Any], key: str) -> str:
    found = draft.get(SOURCES_KEY)
    if not isinstance(found, dict):
        return ""
    answer = found.get(key)
    return answer if isinstance(answer, str) else ""


def set_source(draft: dict[str, Any], key: str, who: str) -> None:
    if not isinstance(draft.get(SOURCES_KEY), dict):
        draft[SOURCES_KEY] = {}
    draft[SOURCES_KEY][key] = who


def clear_source(draft: dict[str, Any], key: str) -> None:
    found = draft.get(SOURCES_KEY)
    if isinstance(found, dict):
        found.pop(key, None)


def campaign_type(draft: dict[str, Any]) -> str:
    found = draft.get(CAMPAIGN_TYPE)
    return found if isinstance(found, str) else ""


def set_campaign_type(draft: dict[str, Any], key: str) -> None:
    draft[CAMPAIGN_TYPE] = key


def conversion_event(draft: dict[str, Any]) -> str:
    found = draft.get(CONVERSION_EVENT)
    return found if isinstance(found, str) else ""


def set_conversion_event(draft: dict[str, Any], key: str) -> None:
    draft[CONVERSION_EVENT] = key


def url_tags(draft: dict[str, Any]) -> str:
    found = draft.get(URL_TAGS)
    return found if isinstance(found, str) else ""


def set_url_tags(draft: dict[str, Any], tags: str) -> None:
    draft[URL_TAGS] = tags
