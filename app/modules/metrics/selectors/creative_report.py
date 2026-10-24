from dataclasses import dataclass
from datetime import date
from typing import Any, Final

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.selectors.creatives import (
    creative_states,
    creatives_by_external_id,
)
from app.modules.metrics.selectors.creative_basis import (
    average_of,
    cost_label,
    countable_in,
    goal_of,
    kind_of,
    note_for,
    window,
)
from app.modules.metrics.selectors.creative_cards import (
    CreativeCard,
    cards,
    waiting_cards,
)
from app.modules.metrics.selectors.creative_leads import leads_by_creative
from app.modules.metrics.selectors.creative_rankings import rankings
from app.modules.metrics.selectors.creatives import compare_creatives, sums_by_creative
from app.modules.metrics.selectors.results import UNCOUNTED_LABEL, words_for
from core.metrics import MIN_SEGMENT_LEADS, Outcome

_OWN_CELL: Final = frozenset({"lead", "view"})


@dataclass(frozen=True, slots=True)
class CreativeReport:
    kind: Outcome
    result_label: Any
    cost_label: Any
    since: date | None = None
    until: date | None = None
    ranked: tuple[CreativeCard, ...] = ()
    barren: tuple[CreativeCard, ...] = ()
    weak: tuple[CreativeCard, ...] = ()
    thin: tuple[CreativeCard, ...] = ()
    waiting: tuple[CreativeCard, ...] = ()
    count: int = 0
    min_results: int = MIN_SEGMENT_LEADS
    best_results: int = 0
    average: str = ""
    note: Any = ""
    has_figures: bool = False

    @property
    def result_heading(self) -> Any:
        if self.kind in _OWN_CELL:
            return ""
        return words_for(self.kind).label if words_for(self.kind).field else ""

    @property
    def is_alone(self) -> bool:
        return self.count == 1

    @property
    def has_cards(self) -> bool:
        return bool(self.has_figures or self.waiting)

    @property
    def all_cards(self) -> tuple[CreativeCard, ...]:
        return self.ranked + self.barren + self.weak + self.thin


def creative_report(db: Session, *, owner: User, campaign: Any) -> CreativeReport:
    states = creative_states(db, owner=owner, campaign=campaign)
    days = window(db, owner=owner, campaign=campaign)
    if days is None:
        return _nothing(db, owner=owner, campaign=campaign, states=states)
    since, until = days
    sums = sums_by_creative(
        db,
        owner=owner,
        provider=campaign.provider,
        since=since,
        until=until,
        campaign_external_id=campaign.external_id,
    )
    if not sums:
        return _nothing(db, owner=owner, campaign=campaign, states=states)
    goal, promoted = goal_of(db, owner=owner, campaign=campaign)
    kind = kind_of(goal=goal, promoted=promoted)
    comparison = compare_creatives(sums, kind=kind)
    shared: dict[str, Any] = {
        "sums": sums,
        "creatives": creatives_by_external_id(
            db, owner=owner, provider=campaign.provider, external_ids=sorted(sums)
        ),
        "verdicts": rankings(db, owner=owner, campaign=campaign, until=until),
        "leads": leads_by_creative(
            db, owner=owner, campaign=campaign, since=since, until=until
        ),
        "states": states,
        "currency": campaign.ad_account.currency,
    }
    return CreativeReport(
        kind=kind,
        result_label=words_for(kind).one,
        cost_label=cost_label(kind),
        since=since,
        until=until,
        ranked=cards(comparison.ranked, state="ranked", ranked=True, **shared),
        barren=cards(comparison.barren, state="barren", **shared),
        weak=cards(comparison.weak, state="weak", **shared),
        thin=cards(comparison.thin, state="thin", **shared),
        count=len(sums),
        best_results=max(countable_in(row, kind=kind) for row in sums.values()),
        average=average_of(comparison.average_cpl_minor, shared["currency"], kind),
        note=note_for(kind=kind, goal=goal),
        waiting=waiting_cards(
            states={
                creative_id: standing
                for creative_id, standing in states.items()
                if creative_id not in sums
            },
            creatives=shared["creatives"],
        ),
        has_figures=True,
    )


def _nothing(
    db: Session, *, owner: User, campaign: Any, states: dict[str, Any]
) -> CreativeReport:
    return CreativeReport(
        kind="none",
        result_label=UNCOUNTED_LABEL,
        cost_label=UNCOUNTED_LABEL,
        waiting=waiting_cards(
            states=states,
            creatives=creatives_by_external_id(
                db, owner=owner, provider=campaign.provider, external_ids=sorted(states)
            ),
        ),
    )
