"""Matching chosen interest names against what a provider answered."""

from dataclasses import dataclass, replace
from typing import Final

from core.targeting.contracts import Interest

STAND_IN_TARGET: Final = 4


@dataclass(frozen=True, slots=True)
class Confirmation:
    """What came back from one round of confirmation."""

    confirmed: tuple[Interest, ...] = ()
    unchanged: tuple[Interest, ...] = ()
    missing: tuple[Interest, ...] = ()

    @property
    def all_confirmed(self) -> tuple[Interest, ...]:
        """Everything targetable, in one tuple, ready to be built with."""
        return self.confirmed + self.unchanged

    @property
    def is_launchable(self) -> bool:
        """At least one interest survived, which is the product's floor."""
        return bool(self.all_confirmed)


@dataclass(frozen=True, slots=True)
class Found:
    """One catalogue row, reduced to what matching needs."""

    name: str
    external_id: str
    audience_lower: int = 0
    audience_upper: int = 0


def needs_lookup(interests: tuple[Interest, ...]) -> tuple[str, ...]:
    """The names still worth asking about, de-duplicated and in order."""
    seen: set[str] = set()
    pending: list[str] = []

    for interest in interests:
        if interest.is_confirmed:
            continue
        key = _key(interest.query)
        if not key or key in seen:
            continue
        seen.add(key)
        pending.append(interest.query)

    return tuple(pending)


def apply_found(
    interests: tuple[Interest, ...], found: tuple[Found, ...]
) -> Confirmation:
    """Split the chosen list by what the provider recognised."""
    rows = {_key(row.name): row for row in found if _key(row.name)}

    confirmed: list[Interest] = []
    unchanged: list[Interest] = []
    missing: list[Interest] = []

    for interest in interests:
        if interest.is_confirmed:
            unchanged.append(interest)
            continue

        row = rows.get(_key(interest.query))
        if row is None:
            missing.append(interest)
            continue

        confirmed.append(
            replace(
                interest,
                external_id=row.external_id,
                audience_size=row.audience_lower,
            )
        )

    return Confirmation(
        confirmed=tuple(confirmed),
        unchanged=tuple(unchanged),
        missing=tuple(missing),
    )


def retranslate(
    missing: tuple[Interest, ...], translations: dict[str, str]
) -> tuple[Interest, ...]:
    """The names that failed, pointed at a different word to search for."""
    return tuple(
        replace(interest, query=translations[_key(interest.query)])
        if _key(interest.query) in translations
        else interest
        for interest in missing
    )


def stand_in_room(*, kept: int, dropped: int, target: int = STAND_IN_TARGET) -> int:
    """How many stand-ins a list may take: one per dropped name, up to target."""
    return max(0, min(dropped, target - kept))


def stand_ins(
    *,
    kept: tuple[Interest, ...],
    dropped: tuple[Interest, ...],
    spare: tuple[Interest, ...],
    target: int = STAND_IN_TARGET,
) -> tuple[Interest, ...]:
    """Confirmed spares to take the place of names the provider did not have."""
    room = stand_in_room(kept=len(kept), dropped=len(dropped), target=target)
    taken_queries = {_key(item.query) for item in kept}
    taken_ids = {item.external_id for item in kept}

    picked: list[Interest] = []
    for item in spare:
        if len(picked) >= room:
            break
        if not item.is_confirmed:
            continue
        if _key(item.query) in taken_queries or item.external_id in taken_ids:
            continue
        picked.append(item)
        taken_queries.add(_key(item.query))
        taken_ids.add(item.external_id)
    return tuple(picked)


def _key(value: str) -> str:
    return value.strip().casefold()
