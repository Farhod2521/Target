from dataclasses import dataclass
from typing import Any

from app.common.money import format_minor
from app.modules.ads.selectors import CreativeState
from app.modules.metrics.selectors.creative_figures import cpql, rate
from app.modules.metrics.selectors.creative_figures import verdict as verdict_of
from app.modules.metrics.selectors.creative_leads import CreativeLeads
from app.modules.metrics.selectors.creative_rankings import Verdicts
from app.modules.metrics.selectors.creatives import CreativeSums
from core.metrics import SegmentCost, WatchPoint, watch_shape

_NO_STATE = CreativeState(delivery="", label="", ad_external_id="")


@dataclass(frozen=True, slots=True)
class CreativeCard:
    external_id: str
    state: str
    place: int
    headline: str
    message: str
    thumbnail_url: str
    kind_label: str
    is_missing: bool
    spend: str
    spend_share: int
    results: int
    cost: str
    verdict: Any
    days: int
    quality: str
    engagement: str
    conversion: str
    impressions: int = 0
    link_clicks: int = 0
    link_ctr: str = ""
    own_leads: int = 0
    qualified: int = 0
    unmarked: int = 0
    cpql: str = ""
    delivery: str = ""
    delivery_label: Any = ""
    ad_external_id: str = ""
    reactions: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0

    @property
    def has_social(self) -> bool:
        return bool(self.reactions or self.comments or self.shares or self.saves)

    watch: tuple[WatchPoint, ...] = ()
    plays: int = 0


def cards(
    costs: tuple[SegmentCost, ...],
    *,
    state: str,
    sums: dict[str, CreativeSums],
    creatives: dict[str, Any],
    verdicts: dict[str, Verdicts],
    leads: dict[str, CreativeLeads],
    states: dict[str, CreativeState],
    currency: str,
    ranked: bool = False,
) -> tuple[CreativeCard, ...]:
    return tuple(
        (
            _card(
                cost,
                state=state,
                place=index if ranked else 0,
                row=sums[cost.segment],
                creative=creatives.get(cost.segment),
                verdict=verdicts.get(cost.segment, ("", "", "")),
                own=leads.get(cost.segment, CreativeLeads()),
                standing=states.get(cost.segment, _NO_STATE),
                currency=currency,
            )
            for index, cost in enumerate(costs, start=1)
        )
    )


def _card(
    cost: SegmentCost,
    *,
    state: str,
    place: int,
    row: CreativeSums,
    creative: Any,
    verdict: Verdicts,
    own: CreativeLeads,
    standing: CreativeState,
    currency: str,
) -> CreativeCard:
    return CreativeCard(
        external_id=cost.segment,
        state=state,
        place=place,
        headline=creative.headline if creative else "",
        message=creative.message if creative else "",
        thumbnail_url=creative.thumbnail_url if creative else "",
        kind_label=creative.get_kind_display() if creative else "",
        is_missing=creative is None,
        spend=format_minor(amount_minor=cost.spend_minor, currency=currency),
        spend_share=cost.spend_share,
        results=cost.leads_reported,
        cost=format_minor(amount_minor=cost.cpl_reported_minor, currency=currency),
        verdict=verdict_of(cost.cpl_index),
        days=row.days,
        quality=verdict[0],
        engagement=verdict[1],
        conversion=verdict[2],
        watch=watch_shape(
            plays=row.video_plays,
            quartiles=(row.video_p25, row.video_p50, row.video_p75, row.video_p100),
        ),
        plays=row.video_plays,
        impressions=row.impressions,
        link_clicks=row.link_clicks,
        link_ctr=rate(part=row.link_clicks, whole=row.impressions),
        own_leads=own.leads,
        qualified=own.qualified,
        unmarked=own.unmarked,
        cpql=cpql(spend_minor=row.spend_minor, own=own, currency=currency),
        delivery=standing.delivery,
        delivery_label=standing.label,
        ad_external_id=standing.ad_external_id,
        reactions=row.reactions,
        comments=row.comments,
        shares=row.shares,
        saves=row.saves,
    )


def waiting_cards(
    *, states: dict[str, CreativeState], creatives: dict[str, Any]
) -> tuple[CreativeCard, ...]:
    return tuple(
        (
            _waiting(creative_id, standing=standing, content=creatives.get(creative_id))
            for creative_id, standing in sorted(states.items())
        )
    )


def _waiting(
    creative_id: str, *, standing: CreativeState, content: Any
) -> CreativeCard:
    return CreativeCard(
        external_id=creative_id,
        state="waiting",
        place=0,
        headline=content.headline if content else standing.name,
        message=content.message if content else "",
        thumbnail_url=content.thumbnail_url if content else "",
        kind_label=content.get_kind_display() if content else "",
        is_missing=False,
        spend="",
        spend_share=0,
        results=0,
        cost="",
        verdict="",
        days=0,
        quality="",
        engagement="",
        conversion="",
        delivery=standing.delivery,
        delivery_label=standing.label,
        ad_external_id=standing.ad_external_id,
    )
