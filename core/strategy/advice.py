"""What a strategy answers with, and the words it may use.

A different value from :class:`core.agent.Finding` on purpose. A finding
names one object and one executable change - it becomes a button. Advice
names a *direction* for the whole account - it becomes a card. Sharing the
shape would invite sharing the pipeline, and the pipelines are different: a
finding is re-derived at approval time, advice has no approval to survive.

``needs`` is the half a finding could never carry: what is missing. "Build
a lookalike" said to an account with no customer list is not wrong, it is
premature - and the honest card says what to bring, in a stable code the
Django layer turns into an Uzbek sentence. Codes rather than sentences,
the same rule as every other domain word a person eventually reads.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

# What a not-ready strategy is waiting for. A closed set, like the rule
# codes: a need that is not named here has no sentence on the screen.
NEED_SEED_AUDIENCE: Final = "seed_audience"
NEED_TRAFFIC_SOURCE: Final = "traffic_source"

NEEDS: Final[tuple[str, ...]] = (NEED_SEED_AUDIENCE, NEED_TRAFFIC_SOURCE)


@dataclass(frozen=True, slots=True)
class StrategyAdvice:
    """One direction worth taking, or worth preparing for.

    ``strategy`` is the stable code, the same bargain ``Finding.rule``
    makes: the Django layer maps it to language, a later run can be
    compared against an earlier one by it, and renaming one is a
    migration rather than a rename.

    ``ready`` splits the two kinds of card. True means the account can
    act on this now; False means the account is missing something, and
    ``needs`` names what. A not-ready advice is not a lesser one - "upload
    your customer list" is often the most valuable sentence on the screen.

    ``evidence`` is the numbers the advice was derived from, stored so
    "why did it say that" has an answer after the account has moved on -
    the same reason findings carry theirs.
    """

    strategy: str
    ready: bool = True
    needs: tuple[str, ...] = ()
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def as_record(self) -> dict[str, Any]:
        """The same advice as plain data, for whatever stores a night's.

        Here rather than at the caller so the shape and the fields cannot
        drift apart: a key renamed on the dataclass and not in the writer
        would be a column of dictionaries that silently stopped carrying
        one of them. Codes and numbers only - no sentence is built in this
        package, which has no language.
        """
        return {
            "strategy": self.strategy,
            "ready": self.ready,
            "needs": list(self.needs),
            "evidence": dict(self.evidence),
        }


__all__ = [
    "NEEDS",
    "NEED_SEED_AUDIENCE",
    "NEED_TRAFFIC_SOURCE",
    "StrategyAdvice",
]
