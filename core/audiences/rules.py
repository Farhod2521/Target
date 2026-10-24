"""Deciding what an audience should be built out of, before anybody is asked."""

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

WINDOWS: Final[tuple[int, ...]] = (7, 30, 90, 180, 365)


def windows_for(*, support: RuleSupportDTO) -> tuple[int, ...]:
    """The windows worth offering for this source, shortest first."""
    return tuple(days for days in WINDOWS if days <= support.max_retention_days)


def build_rule(
    *,
    kind: AudienceSource,
    action: AudienceAction,
    source: ExternalRef,
    retention_days: int,
    support: Iterable[RuleSupportDTO],
) -> AudienceRuleDTO:
    """Check the choice against what the provider offers, and name it."""
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
    """The provider's entry for this source, or a refusal naming it."""
    for entry in support:
        if entry.kind == kind:
            return entry
    raise SourceNotSupported(kind=kind)


__all__ = ["WINDOWS", "build_rule", "windows_for"]
