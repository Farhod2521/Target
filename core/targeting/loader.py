"""Reading the catalogue off disk: ``*.yaml`` in, ``Preset`` out."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import yaml

from core.targeting.buttons import FIXED_BUTTONS
from core.targeting.chat import MAX_CHAT_QUESTIONS, MAX_QUESTION_CHARS
from core.targeting.contracts import Interest
from core.targeting.destinations import (
    DESTINATIONS,
    AdDestination,
    opens_chat,
    opens_profile,
    shows_a_button,
)
from core.targeting.exceptions import CatalogError
from core.targeting.placements import names_a_placement
from core.targeting.presets import Category, Preset

NO_BUTTON = "NO_BUTTON"


def read_directory(path: Path) -> tuple[list[Category], list[Preset]]:
    """Every ``*.yaml`` under ``path``, in filename order."""
    categories: list[Category] = []
    presets: list[Preset] = []
    seen: set[tuple[str, str, str]] = set()

    for file in sorted(path.glob("*.yaml")):
        category, file_presets = _read_file(file)
        categories.append(category)
        for preset in file_presets:
            marker = (preset.provider, preset.category, preset.goal)
            if marker in seen:
                raise CatalogError(f"{preset.key} is defined twice", source=file.name)
            seen.add(marker)
            presets.append(preset)

    return categories, presets


def _read_file(file: Path) -> tuple[Category, tuple[Preset, ...]]:
    """One YAML file: a category, its seeds, and its presets."""
    raw = yaml.safe_load(file.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise CatalogError("expected a mapping at the top level", source=file.name)

    data: dict[str, Any] = raw
    source = file.name
    provider = _text(data, "provider", source=source)
    key = _text(data, "category", source=source)
    version = str(_required(data, "version", source=source))

    category = Category(
        provider=provider,
        key=key,
        label=_text(data, "label", source=source),
        version=version,
        interest_seeds=_seeds(data.get("interest_seeds") or [], source=source),
        trait_seeds=_traits(data.get("trait_seeds") or [], source=source),
    )

    base = _mapping(data.get("targeting_base"), source=source)
    _check_placements(base, where=f"{key}/targeting_base", source=source)
    entries = _required(data, "presets", source=source)
    if not isinstance(entries, list) or not entries:
        raise CatalogError("presets must be a non-empty list", source=source)

    presets = tuple(
        _read_preset(entry, category=category, base=base, source=source)
        for entry in entries
    )
    return category, presets


def _read_preset(
    entry: Any,
    *,
    category: Category,
    base: Mapping[str, Any],
    source: str,
) -> Preset:
    """One entry of the ``presets:`` list, merged over the category base."""
    if not isinstance(entry, dict):
        raise CatalogError("each preset must be a mapping", source=source)

    data: dict[str, Any] = entry
    goal = _text(data, "goal", source=source)
    if "schedule" in data:
        raise CatalogError(f"{goal} names a schedule; nothing reads one", source=source)
    own = _mapping(data.get("targeting"), source=source)
    _check_placements(own, where=goal, source=source)

    targeting = {**base, **own}
    if not targeting:
        raise CatalogError(f"{category.key}/{goal} targets nothing", source=source)

    sends_to = _destination(data, source=source)
    welcome, autofill = _chat(data, sends_to=sends_to, goal=goal, source=source)
    call_to_action, destination_type = _provider_words(
        data, sends_to=sends_to, goal=goal, source=source
    )

    return Preset(
        provider=category.provider,
        category=category.key,
        goal=goal,
        label=_text(data, "label", source=source),
        version=category.version,
        objective=_text(data, "objective", source=source),
        optimization_goal=_text(data, "optimization_goal", source=source),
        billing_event=_text(data, "billing_event", source=source),
        sends_to=sends_to,
        call_to_action=call_to_action,
        destination_type=destination_type,
        targeting=targeting,
        defaults=_mapping(data.get("defaults"), source=source),
        promoted_object=_mapping(data.get("promoted_object"), source=source),
        welcome_message=welcome,
        autofill_message=autofill,
        chat_questions=_chat_questions(
            data, sends_to=sends_to, goal=goal, source=source
        ),
        offered=_offered(data, source=source),
    )


def _check_placements(targeting: Mapping[str, Any], *, where: str, source: str) -> None:
    """A preset may not decide where the ad appears. Refused, not ignored."""
    named = names_a_placement(targeting)
    if named:
        raise CatalogError(
            f"{where} names {', '.join(named)}: where an ad appears is not "
            "the catalogue's to decide",
            source=source,
        )


def _destination(data: Mapping[str, Any], *, source: str) -> AdDestination:
    """``sends_to``, checked against the six the domain knows."""
    value = _text(data, "sends_to", source=source)
    if value not in DESTINATIONS:
        raise CatalogError(f"unknown sends_to {value!r}", source=source)
    return value  # type: ignore[return-value]


def _chat(
    data: Mapping[str, Any], *, sends_to: str, goal: str, source: str
) -> tuple[str, str]:
    """The two texts a conversation opens with, checked against the goal."""
    welcome = str(data.get("welcome_message") or "")
    autofill = str(data.get("autofill_message") or "")

    if not opens_chat(sends_to):
        if welcome or autofill:
            raise CatalogError(
                f"{goal} sends nobody to a chat and cannot greet one",
                source=source,
            )
        return "", ""

    if not welcome or not autofill:
        raise CatalogError(
            f"{goal} opens a chat: welcome_message and autofill_message "
            "are both required",
            source=source,
        )
    return welcome, autofill


def _chat_questions(
    data: Mapping[str, Any], *, sends_to: str, goal: str, source: str
) -> tuple[str, ...]:
    """The questions offered first when the owner asks for some."""
    raw = data.get("chat_questions") or []
    if not isinstance(raw, list):
        raise CatalogError(f"{goal}: chat_questions must be a list", source=source)
    questions = tuple(str(item).strip() for item in raw)
    if questions and not opens_chat(sends_to):
        raise CatalogError(
            f"{goal} sends nobody to a chat and cannot ask questions in one",
            source=source,
        )
    if len(questions) > MAX_CHAT_QUESTIONS or any(
        not item or len(item) > MAX_QUESTION_CHARS for item in questions
    ):
        raise CatalogError(
            f"{goal}: at most {MAX_CHAT_QUESTIONS} chat_questions of "
            f"1-{MAX_QUESTION_CHARS} characters",
            source=source,
        )
    return questions


def _provider_words(
    data: Mapping[str, Any], *, sends_to: str, goal: str, source: str
) -> tuple[str, str]:
    """The button and the ad set destination, where the preset owns them."""
    given_cta = str(data.get("call_to_action") or "")
    given_destination = str(data.get("destination_type") or "")

    if opens_chat(sends_to):
        if given_cta or given_destination:
            raise CatalogError(
                f"{goal} opens a chat: the channel names the button and the "
                "destination, so the preset may not",
                source=source,
            )
        return "", ""

    if not given_cta:
        raise CatalogError("missing 'call_to_action'", source=source)

    if not shows_a_button(sends_to) and given_cta != NO_BUTTON:
        raise CatalogError(
            f"{goal} sends nobody anywhere: call_to_action must be "
            f"{NO_BUTTON}, not {given_cta}",
            source=source,
        )
    profile_button = FIXED_BUTTONS["profile"]
    if opens_profile(sends_to) and given_cta != profile_button:
        raise CatalogError(
            f"{goal} opens the Instagram profile: call_to_action must be "
            f"{profile_button}, not {given_cta}",
            source=source,
        )
    return given_cta, given_destination


TRAIT_KINDS: Final[frozenset[str]] = frozenset({"behaviour", "life_event"})


def _traits(raw: Any, *, source: str) -> tuple[Interest, ...]:
    """``trait_seeds``: a label, a name to match, and which catalogue."""
    if not isinstance(raw, list):
        raise CatalogError("trait_seeds must be a list", source=source)

    seeds: list[Interest] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise CatalogError("each trait seed must be a mapping", source=source)
        data: dict[str, Any] = entry
        kind = _text(data, "kind", source=source)
        if kind not in TRAIT_KINDS:
            raise CatalogError(
                f"trait seed kind must be one of {sorted(TRAIT_KINDS)}, got {kind!r}",
                source=source,
            )
        seeds.append(
            Interest(
                label=_text(data, "label", source=source),
                query=_text(data, "query", source=source),
                kind=kind,  # type: ignore[arg-type]
            )
        )
    return tuple(seeds)


def _seeds(raw: Any, *, source: str) -> tuple[Interest, ...]:
    """``interest_seeds``: a label to read and a name to search for."""
    if not isinstance(raw, list):
        raise CatalogError("interest_seeds must be a list", source=source)

    seeds: list[Interest] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise CatalogError("each interest seed must be a mapping", source=source)
        data: dict[str, Any] = entry
        seeds.append(
            Interest(
                label=_text(data, "label", source=source),
                query=_text(data, "query", source=source),
            )
        )
    return tuple(seeds)


def _required(data: Mapping[str, Any], key: str, *, source: str) -> Any:
    value = data.get(key)
    if value is None or value == "":
        raise CatalogError(f"missing {key!r}", source=source)
    return value


def _offered(data: Mapping[str, Any], *, source: str) -> bool:
    """``offered: false`` withdraws a goal from the wizard, not from lookup."""
    value = data.get("offered", True)
    if not isinstance(value, bool):
        raise CatalogError("'offered' must be true or false", source=source)
    return value


def _text(data: Mapping[str, Any], key: str, *, source: str) -> str:
    value = _required(data, key, source=source)
    if not isinstance(value, str):
        raise CatalogError(f"{key!r} must be text", source=source)
    return value


def _mapping(value: Any, *, source: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise CatalogError("expected a mapping", source=source)
    result: dict[str, Any] = value
    return result
