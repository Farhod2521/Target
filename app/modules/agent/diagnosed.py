"""Which group's diagnosis a finding is about, and the shape it is kept in.

Two readers need the same answer - the shortlist Claude reads tonight and the
row written after it - and a second copy of the lookup would let the card
and the sentence beneath it name two different causes.
"""

from collections.abc import Mapping
from typing import Any

from core.agent import Finding
from core.agent.diagnosis import Diagnosis
from core.agent.rules.faults import BROKEN_PICTURE, REFUSED_AD

_OWN_CAUSE = frozenset({REFUSED_AD, BROKEN_PICTURE})


def diagnosis_of(finding: Finding, causes: Mapping[str, Diagnosis]) -> Diagnosis | None:
    """The diagnosis of the group a finding is about.

    Its own for a group, the one it sits in for an advert. Nothing for a
    campaign: a diagnosis is about one group's money, and a campaign's is
    several groups'. Nothing for a provider's fault on one advert either -
    see ``_OWN_CAUSE``.
    """
    if finding.rule in _OWN_CAUSE:
        return None
    return causes.get(finding.parent_id or finding.ref.id)


def diagnosis_record(diagnosis: Diagnosis | None) -> dict[str, Any]:
    """The diagnosis as a row keeps it and as ``apps.agent.causes`` reads it."""
    if diagnosis is None:
        return {}
    return {
        "cause": diagnosis.cause,
        "signals": list(diagnosis.signals),
        "evidence": dict(diagnosis.evidence),
    }


__all__ = ["diagnosis_of", "diagnosis_record"]
