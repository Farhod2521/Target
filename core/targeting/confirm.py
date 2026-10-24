"""Matching chosen interest names against what a provider answered.

Pure, and deliberately separate from the call that fetches the rows. The
matching is where the interesting decisions live - what counts as the same
name, what happens to a name nobody recognised, which of two rows wins -
and every one of them is worth a test that runs in a millisecond without a
network, a database or a token.

The rule throughout: a name the provider does not have is **dropped with a
reason**, never guessed at. An interest silently swapped for a similar one
would spend somebody's budget on an audience they did not choose.
"""

from dataclasses import dataclass, replace
from typing import Final

from core.targeting.contracts import Interest

# How many confirmed interests a list the model ticked is brought back up to
# when the provider did not recognise some of its names. Four is the
# smallest list the proposal prompt itself calls runnable.
STAND_IN_TARGET: Final = 4


@dataclass(frozen=True, slots=True)
class Confirmation:
    """What came back from one round of confirmation.

    Three lists rather than two. ``unchanged`` are the ones that were
    already confirmed and cost no call; keeping them apart from ``confirmed``
    is what lets the caller cache only what it actually learned, and what
    lets a screen say "checked" without re-checking.
    """

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
    """One catalogue row, reduced to what matching needs.

    Not ``InterestDTO``: this module is domain code and must not import a
    package's DTO to do arithmetic on strings. The caller converts once.
    """

    name: str
    external_id: str
    audience_lower: int = 0
    audience_upper: int = 0


def needs_lookup(interests: tuple[Interest, ...]) -> tuple[str, ...]:
    """The names still worth asking about, de-duplicated and in order.

    A name that already carries an id is skipped: confirmation is the
    expensive half of this flow, and re-confirming what a previous launch
    already established is a round trip that buys nothing.
    """
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
    """Split the chosen list by what the provider recognised.

    Matched case-insensitively on the query, because providers answer with
    their own capitalisation - "coffee" goes out and "Coffee" comes back -
    and treating that as a miss would drop half of every list.

    The owner-facing ``label`` is never overwritten by the provider's name.
    Somebody who chose "Sartaroshxona" should keep reading "Sartaroshxona"
    on their own screen, whatever Meta files it under internally.
    """
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
    """The names that failed, pointed at a different word to search for.

    ``label`` survives untouched and ``query`` is replaced. That asymmetry
    is the whole feature: the owner keeps the word they typed, and the
    provider is asked about the word it might actually have.

    A name with no translation offered is returned as it was rather than
    dropped here. Deciding it is unusable is the caller's job, once - and
    doing it in two places is how one of them ends up wrong.
    """
    return tuple(
        replace(interest, query=translations[_key(interest.query)])
        if _key(interest.query) in translations
        else interest
        for interest in missing
    )


def stand_in_room(*, kept: int, dropped: int, target: int = STAND_IN_TARGET) -> int:
    """How many stand-ins a list may take: one per dropped name, up to target.

    Never more than was dropped. A list the provider accepted whole is the
    list somebody chose, and growing it is a decision nobody made.
    """
    return max(0, min(dropped, target - kept))


def stand_ins(
    *,
    kept: tuple[Interest, ...],
    dropped: tuple[Interest, ...],
    spare: tuple[Interest, ...],
    target: int = STAND_IN_TARGET,
) -> tuple[Interest, ...]:
    """Confirmed spares to take the place of names the provider did not have.

    ``spare`` is the rest of the same proposal, in its own order, so the
    first stand-in is the one the model ranked highest among those it did
    not tick. Only confirmed ones qualify: a stand-in that is itself
    unrecognised replaces nothing. A spare already in the list under
    another label is skipped by its id.
    """
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
