"""Reading the catalogue off disk: ``*.yaml`` in, ``Preset`` out.

Apart from :mod:`core.targeting.presets` because the two answer different
questions. That module is the catalogue *as the rest of the product sees
it* - find a preset, list a category's goals - and nothing above it has any
business knowing the files are YAML at all. This is the parser, and it is
the half that grows: every field a preset gains is a required key, a type
check and a sentence about what a missing one means.

**Every value is required unless a comment here says otherwise, and an
unknown one raises.** A catalogue that falls back is a catalogue that ships
a typo to production and finds out from a customer whose goal disappeared
off the first screen.
"""

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

# Meta's own word for "draw no button". The catalogue is where a goal's
# provider words live, so it is named rather than substituted - but a goal
# that sends nobody anywhere may name **only** this one, which is what
# :func:`_provider_words` enforces.
#
# Not a default filled in on the preset's behalf. A silent substitution
# here is a catalogue entry saying one thing and a creative doing another,
# which is the whole failure this stage was written to stop.
NO_BUTTON = "NO_BUTTON"


def read_directory(path: Path) -> tuple[list[Category], list[Preset]]:
    """Every ``*.yaml`` under ``path``, in filename order.

    A duplicate ``category/goal`` raises rather than being overwritten: two
    files claiming the same key means one of them is silently dead, and
    which one depends on the alphabet.
    """
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
        # Nothing reads a schedule: the launch always sends "start now",
        # because a campaign is created paused and a person switches it on.
        # Refused
        # rather than ignored, for the same reason as ``_check_placements``:
        # a key that looks authoritative in a data file and decides nothing
        # is worse than no key at all.
        raise CatalogError(f"{goal} names a schedule; nothing reads one", source=source)
    own = _mapping(data.get("targeting"), source=source)
    _check_placements(own, where=goal, source=source)

    # Shallow on purpose: a preset that names ``geo_locations`` replaces the
    # base's whole block rather than merging into it. Deep-merging two
    # provider specs produces combinations neither author wrote.
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
    """A preset may not decide where the ad appears. Refused, not ignored.

    The rule this stage was written for, and it is the same shape as the
    one ``_provider_words`` enforces on chat goals: a key that looks
    authoritative in a data file and decides nothing is worse than no key
    at all.

    Where an ad appears is one answer with two states, in
    :mod:`core.targeting.placements`, and the builder writes the whole
    block - so a key here would be silently overwritten, which is the one
    outcome worse than being wrong.
    """
    named = names_a_placement(targeting)
    if named:
        raise CatalogError(
            f"{where} names {', '.join(named)}: where an ad appears is not "
            "the catalogue's to decide",
            source=source,
        )


def _destination(data: Mapping[str, Any], *, source: str) -> AdDestination:
    """``sends_to``, checked against the six the domain knows.

    Required, and an unknown value is a refusal rather than a fallback. A
    typo falling through to "cannot be built" would take a working goal off
    the first wizard screen with no error anywhere - the failure that is
    only ever noticed by the customer who stopped seeing their own goal.
    """
    value = _text(data, "sends_to", source=source)
    if value not in DESTINATIONS:
        raise CatalogError(f"unknown sends_to {value!r}", source=source)
    return value  # type: ignore[return-value]


def _chat(
    data: Mapping[str, Any], *, sends_to: str, goal: str, source: str
) -> tuple[str, str]:
    """The two texts a conversation opens with, checked against the goal.

    Required on a goal that opens one and **refused** on a goal that does
    not, rather than merely ignored. A greeting written under a lead preset
    is not harmless data: it reads, in the one file that decides what an ad
    is made of, like a sentence somebody will see - and nothing anywhere
    would ever say that no ad can show it.

    The pair is required together for the same reason the pixel and its
    event are (see ``promoted_object``): half of a welcome message is a
    thread that greets somebody and then leaves their own message box
    empty, which is worse than the provider's default and looks deliberate.
    """
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
    """The questions offered first when the owner asks for some.

    Optional, and refused off a chat goal for the reason the greeting is.
    Held to the same ceilings the owner's own questions are, so a catalogue
    line can never be the one Meta refuses.
    """
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
    """The button and the ad set destination, where the preset owns them.

    Every goal but one names both here: they follow from the goal, and the
    catalogue is where a goal's provider words live.

    **A chat goal names neither**, and that is the same decision the
    automation flag makes. The two are a pair Meta refuses to see
    mismatched - an Instagram Direct ad takes ``INSTAGRAM_MESSAGE`` and
    nothing else - and which surface a conversation opens on is answered
    by the owner, one question later, not by the category. A line in
    twelve files saying ``MESSENGER`` would look authoritative and decide
    nothing. See :data:`core.targeting.destinations.CHANNELS`.
    """
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

    # A goal that sends nobody anywhere may carry exactly one button, and
    # it is the one that is not a button. Refused rather than corrected,
    # for the reason every other rule in this file refuses: a preset
    # reading ``LEARN_MORE`` beside ``sends_to: nothing`` is a sentence
    # somebody will believe. It produces an awareness ad whose button
    # opens this deployment's own front page - a real link, on somebody
    # else's paid impressions, that no screen would ever mention.
    if not shows_a_button(sends_to) and given_cta != NO_BUTTON:
        raise CatalogError(
            f"{goal} sends nobody anywhere: call_to_action must be "
            f"{NO_BUTTON}, not {given_cta}",
            source=source,
        )
    # The profile's button opens the profile and nothing else. Another word
    # beside this destination is accepted by Meta and opens the address in
    # a browser, where somebody not logged in meets a sign-in wall.
    profile_button = FIXED_BUTTONS["profile"]
    if opens_profile(sends_to) and given_cta != profile_button:
        raise CatalogError(
            f"{goal} opens the Instagram profile: call_to_action must be "
            f"{profile_button}, not {given_cta}",
            source=source,
        )
    return given_cta, given_destination


# The kinds a ``trait_seeds`` entry may declare. Interests are not among
# them: those are searched for and belong in ``interest_seeds`` above, and
# a file that could put one here would be a file with two homes for the
# same thing.
TRAIT_KINDS: Final[frozenset[str]] = frozenset({"behaviour", "life_event"})


def _traits(raw: Any, *, source: str) -> tuple[Interest, ...]:
    """``trait_seeds``: a label, a name to match, and which catalogue.

    Refused rather than defaulted when the kind is missing or unknown. The
    two classes are closed lists at the provider and are matched exactly, so
    a seed filed under the wrong one resolves to nothing - and "resolves to
    nothing" is indistinguishable, from every screen, from a class the
    platform does not offer in this market.

    No ids, for the reason the interest seeds carry none: an id in a data
    file is a promise the provider never made.
    """
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
    """``interest_seeds``: a label to read and a name to search for.

    No ids. An id in a data file is a promise the provider never made, and
    it breaks silently the day the provider merges two interests.
    """
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
    """``offered: false`` withdraws a goal from the wizard, not from lookup.

    Absent means offered. A value that is not a boolean is refused rather than
    read for truthiness: ``offered: "no"`` is a string, every non-empty
    string is true, and the goal would go on being offered by a file that
    says it should not be.
    """
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
