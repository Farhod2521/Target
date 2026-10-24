from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.modules.metrics.constants import RECONCILE_FROM, RECONCILE_PCT
from app.modules.metrics.selectors.periods import FUNNEL_TEXT, lines, steps
from app.modules.metrics.selectors.shapes import FunnelStep, Series
from core.metrics import DayFigures, Outcome, PanelDay, Totals, panel_total

NOTHING_LOST = "Hali yetarli ma'lumot yo'q."
LEAD_HEADING = "Murojaat qayerda yo'qoladi"
PEOPLE_HEADING = "Natija qayerda yo'qoladi"
AFTER: dict[int, Any] = {
    0: "ko'rsatilgandan keyin",
    1: "havolaga o'tgandan keyin",
    2: "murojaat qoldirgandan keyin",
}


@dataclass(frozen=True, slots=True)
class CampaignStory:
    series: tuple[Series, ...] = ()
    funnel: tuple[FunnelStep, ...] = ()
    lid: Any = ""
    heading: Any = ""
    mismatch: Any = ""

    @property
    def has_shape(self) -> bool:
        return bool(self.funnel)


def campaign_story(
    *, days: Sequence[PanelDay], currency: str, kind: Outcome = "lead"
) -> CampaignStory:
    totals = panel_total(days)
    if not totals.impressions:
        return CampaignStory()
    rungs = steps(_as_totals(totals), kind=kind)
    return CampaignStory(
        series=lines(days=[_as_day(day) for day in days], currency=currency, kind=kind),
        funnel=rungs,
        lid=_lid(rungs),
        heading=LEAD_HEADING if kind in {"lead", "site_lead"} else PEOPLE_HEADING,
        mismatch=_mismatch(totals) if kind == "lead" else "",
    )


def _mismatch(totals: Any) -> Any:
    reported, ours = (totals.leads_reported, totals.received)
    biggest = max(reported, ours)
    if biggest < RECONCILE_FROM or abs(reported - ours) * 100 < RECONCILE_PCT * biggest:
        return ""
    if reported > ours:
        return (
            "Meta %(reported)s ta murojaat deydi, bu yerga %(ours)s tasi yetib keldi. Farq webhook kechikkanida yoki ulanishdan oldin kelgan murojaatlarda bo'ladi."
            % {"reported": reported, "ours": ours}
        )
    return (
        "Bu yerda %(ours)s ta murojaat bor, Meta %(reported)s tasini sanaydi. Bir xil forma reklamadan tashqarida ham to'ldirilgan bo'lishi mumkin."
        % {"reported": reported, "ours": ours}
    )


def _lid(rungs: tuple[FunnelStep, ...]) -> Any:
    if len(rungs) < 2:
        return NOTHING_LOST
    measured = [
        (index, rung) for index, rung in enumerate(rungs) if rung.share_pct is not None
    ]
    if not measured:
        return NOTHING_LOST
    index, _worst = min(measured, key=lambda pair: pair[1].share_pct or 0)
    where = AFTER.get(index - 1)
    if where is None:
        return NOTHING_LOST
    return (
        "%(top)s %(shown)s → %(bottom)s %(left)s · eng katta yo'qotish: %(where)s"
        % {
            "top": rungs[0].value,
            "shown": str(FUNNEL_TEXT["shown"][0]).lower(),
            "bottom": rungs[-1].value,
            "left": str(rungs[-1].label).lower(),
            "where": str(where),
        }
    )


def _as_totals(totals: Any) -> Totals:
    return Totals(
        spend_minor=totals.spend_minor,
        impressions=totals.impressions,
        clicks=totals.clicks,
        link_clicks=totals.link_clicks,
        leads=totals.leads,
        qualified=totals.qualified,
        leads_reported=totals.leads_reported,
        results=totals.results,
        recallers=totals.recallers,
        profile_visits=totals.profile_visits,
    )


def _as_day(day: PanelDay) -> DayFigures:
    return DayFigures(
        day=day.day,
        spend_minor=day.spend_minor,
        impressions=day.impressions,
        clicks=day.clicks,
        link_clicks=day.link_clicks,
        leads=day.leads,
        qualified=day.qualified,
        leads_reported=day.leads_reported,
        results=day.results,
        recallers=day.recallers,
        profile_visits=day.profile_visits,
    )


__all__ = ["CampaignStory", "campaign_story"]
