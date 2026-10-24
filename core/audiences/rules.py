"""Deciding what an audience should be built out of, before anybody is asked.

The other half of :mod:`core.audiences.members`, and its opposite in the one
way that matters most: **there is no personal data here at all.** A customer
list is people this business already holds; a rule is a description of
people the *provider* already knows about, and nothing about any of them is
collected, hashed or sent. Which is why this file has no digests in it and
why nothing in it needs a test with a known vector.

What it does have is the reason the split exists. The rule that reaches a
provider is that provider's own document - a nested envelope, its own words
for each source, a different comparison operator per source, a window in
seconds - and none of it means anything to a second platform. So the domain
names the **intent** in four fields and the adapter spells it, exactly as
the money rules do: shape on this side, table on the far one.

The provider's answer to "what can I build, and how far back" arrives as
:class:`~adskit.RuleSupportDTO` and is never guessed at here. This module
holds one thing of its own - the ladder of windows a person is offered -
and that is a product decision rather than a platform limit.

No Django, no clock, no configuration.
"""

from collections.abc import Iterable
from typing import Final

from adskit import AudienceAction, AudienceRuleDTO, AudienceSource, ExternalRef
from adskit.dto import RuleSupportDTO

from core.audiences.exceptions import (
    ActionNotSupported,
    RetentionNotOffered,
    RetentionTooLong,
    SourceNotSupported,
)

# The windows a person is offered, shortest first.
#
# A ladder rather than a number they type, and the reason is asymmetric
# failure. Too long is refused by the provider - annoying, and visible. Too
# short is accepted and produces an audience of forty people that never
# delivers, which looks like the product not working. Five rungs cover what
# anybody actually wants: a week for a promotion, a month for the ordinary
# case, three months and up for a business with a long decision.
#
# Not filtered by the provider's own maximum here - that is
# :func:`windows_for`, which needs the provider's answer to do it.
WINDOWS: Final[tuple[int, ...]] = (7, 30, 90, 180, 365)


def windows_for(*, support: RuleSupportDTO) -> tuple[int, ...]:
    """The windows worth offering for this source, shortest first.

    The ladder cut off at whatever the provider will look back. A lead form
    keeps three rungs and a website keeps all five, which is the honest
    picker: offering a year on something that stops at ninety days is
    offering a refusal.

    Never empty in practice - every source seen so far looks back at least
    a week - but an empty answer is returned rather than defended against,
    because a source that looks back no distance at all is one this product
    should stop offering rather than one it should invent a rung for.
    """
    return tuple(days for days in WINDOWS if days <= support.max_retention_days)


def build_rule(
    *,
    kind: AudienceSource,
    action: AudienceAction,
    source: ExternalRef,
    retention_days: int,
    support: Iterable[RuleSupportDTO],
) -> AudienceRuleDTO:
    """Check the choice against what the provider offers, and name it.

    Everything is checked here rather than at the provider, and the
    difference is what the person sees. A refusal that arrives from Meta
    names a code; a refusal that arrives from this function names the
    source, the action and the number that would have worked - and it
    arrives before an audit row has been opened and a call has been spent.

    ``support`` is the provider's own answer, passed in rather than looked
    up: this module has no registry, no provider and no idea which one it
    is being asked about, and that is what keeps it usable for the second.
    """
    offered = _for_kind(kind=kind, support=support)

    if action not in offered.actions:
        raise ActionNotSupported(kind=kind, action=action)
    if retention_days not in WINDOWS:
        raise RetentionNotOffered(days=retention_days)
    if retention_days > offered.max_retention_days:
        raise RetentionTooLong(
            kind=kind, days=retention_days, maximum=offered.max_retention_days
        )

    return AudienceRuleDTO(
        kind=kind,
        action=action,
        source=source,
        retention_days=retention_days,
    )


def _for_kind(
    *, kind: AudienceSource, support: Iterable[RuleSupportDTO]
) -> RuleSupportDTO:
    """The provider's entry for this source, or a refusal naming it.

    A source the provider does not build from is **absent** from its
    answer, never present with an empty action list - so the missing case
    and the "offers nothing" case are one case here, which is the one a
    picker means.
    """
    for entry in support:
        if entry.kind == kind:
            return entry
    raise SourceNotSupported(kind=kind)


__all__ = ["WINDOWS", "build_rule", "windows_for"]
