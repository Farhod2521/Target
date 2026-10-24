"""Which of the advertiser's own audiences this campaign is aimed at."""

from dataclasses import dataclass
from typing import Any, Final

from core.targeting.adjustments import Adjustment

INCLUDE_KEY: Final = "custom_audiences"
EXCLUDE_KEY: Final = "excluded_custom_audiences"

MAX_PER_SIDE: Final = 500

AUDIENCE_FIELD: Final = "audiences"


@dataclass(frozen=True, slots=True)
class AudienceRef:
    """One audience, as much of it as a spec and a sentence need."""

    external_id: str
    label: str = ""
    is_lookalike: bool = False
    is_usable: bool = True


@dataclass(frozen=True, slots=True)
class AudienceChoice:
    """Who to show this to, who never to show it to, and what went missing."""

    included: tuple[AudienceRef, ...] = ()
    excluded: tuple[AudienceRef, ...] = ()
    dropped: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.included and not self.excluded

    @property
    def lookalikes(self) -> tuple[AudienceRef, ...]:
        """Every lookalike named here, on either side."""
        return tuple(
            ref for ref in (*self.included, *self.excluded) if ref.is_lookalike
        )

    @property
    def unusable(self) -> tuple[AudienceRef, ...]:
        """Every audience named here that the provider will not deliver on."""
        return tuple(
            ref for ref in (*self.included, *self.excluded) if not ref.is_usable
        )


def fit(
    spec: dict[str, Any], notes: list[Adjustment], *, choice: AudienceChoice
) -> None:
    """Write both sides into the spec, and report what did not survive."""
    for name in choice.dropped:
        notes.append(
            Adjustment(field=AUDIENCE_FIELD, reason="audience_unavailable", detail=name)
        )

    excluded = _unique(choice.excluded)
    barred = {ref.external_id for ref in excluded}

    included: list[AudienceRef] = []
    for ref in _unique(choice.included):
        if ref.external_id in barred:
            notes.append(
                Adjustment(
                    field=INCLUDE_KEY,
                    reason="audience_on_both_sides",
                    detail=ref.label or ref.external_id,
                )
            )
            continue
        included.append(ref)

    _write(spec, INCLUDE_KEY, included)
    _write(spec, EXCLUDE_KEY, excluded)


def _unique(refs: tuple[AudienceRef, ...]) -> list[AudienceRef]:
    """The same audience twice on one side is one audience, silently."""
    seen: set[str] = set()
    kept: list[AudienceRef] = []
    for ref in refs:
        if not ref.external_id or ref.external_id in seen:
            continue
        seen.add(ref.external_id)
        kept.append(ref)
    return kept


def _write(spec: dict[str, Any], key: str, refs: list[AudienceRef]) -> None:
    """``[{"id": ...}]``, the shape the provider documents its example in."""
    if not refs:
        spec.pop(key, None)
        return
    spec[key] = [{"id": ref.external_id} for ref in refs[:MAX_PER_SIDE]]


__all__ = [
    "AUDIENCE_FIELD",
    "EXCLUDE_KEY",
    "INCLUDE_KEY",
    "MAX_PER_SIDE",
    "AudienceChoice",
    "AudienceRef",
    "fit",
]
