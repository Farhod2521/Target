"""One campaign's days, summed into every figure its panel can show."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date

from adskit import MinorUnits

from core.metrics import formulas
from core.metrics.arithmetic import BASIS_POINTS, basis_points, whole_number
from core.metrics.formulas import PER_MILLE


@dataclass(frozen=True, slots=True)
class PanelDay:
    """One campaign's day, in every count the panel may draw."""

    day: date
    spend_minor: MinorUnits = MinorUnits(0)  # noqa: RUF009 - NewType, not a call
    impressions: int = 0
    clicks: int = 0
    link_clicks: int = 0
    leads: int = 0
    qualified: int = 0
    leads_reported: int = 0
    received: int = 0
    results: int = 0
    recallers: int = 0
    profile_visits: int = 0
    video_plays: int = 0
    video_thruplays: int = 0
    reach: int = 0
    unique_clicks: int = 0

    @property
    def is_measured(self) -> bool:
        """Whether the provider had anything to say about this day."""
        return self.impressions > 0


@dataclass(frozen=True, slots=True)
class PanelTotals:
    """A range, with only the counts that may be added across days."""

    spend_minor: MinorUnits = MinorUnits(0)  # noqa: RUF009 - NewType, not a call
    impressions: int = 0
    clicks: int = 0
    link_clicks: int = 0
    leads: int = 0
    qualified: int = 0
    leads_reported: int = 0
    received: int = 0
    results: int = 0
    recallers: int = 0
    profile_visits: int = 0
    video_plays: int = 0
    video_thruplays: int = 0
    reach: int = 0

    @property
    def cpl_minor(self) -> MinorUnits | None:
        """What one lead cost. ``None`` where the division says nothing."""
        return formulas.cpl(self.spend_minor, self.leads)

    @property
    def cpql_minor(self) -> MinorUnits | None:
        """What one lead worth having cost. The figure the product is for."""
        return formulas.cpql(self.spend_minor, self.qualified)

    @property
    def cpm_minor(self) -> MinorUnits | None:
        """What a thousand showings cost."""
        return formulas.cpm(self.spend_minor, self.impressions)

    @property
    def cpc_minor(self) -> MinorUnits | None:
        """What one click cost, counting every click on the unit."""
        return formulas.cpc(self.spend_minor, self.clicks)

    @property
    def ctr_bp(self) -> int:
        """Clicks per ten thousand impressions. See :data:`BASIS_POINTS`."""
        return basis_points(formulas.ctr(self.clicks, self.impressions))

    @property
    def link_ctr_bp(self) -> int:
        """The same, for the clicks that went where the money was sent."""
        return basis_points(formulas.ctr(self.link_clicks, self.impressions))

    @property
    def platform_cpl_minor(self) -> MinorUnits | None:
        """What the **provider** says one lead cost."""
        return formulas.cpl(self.spend_minor, self.leads_reported)

    @property
    def quality_share(self) -> int:
        """What percentage of the leads were worth having."""
        return whole_number(formulas.qualified_share(self.qualified, self.leads))

    @property
    def hold_share(self) -> int:
        """What share of the people who started the video stayed to the end."""
        return whole_number(
            formulas.thruplay_share(self.video_thruplays, self.video_plays)
        )


def with_provider_leads[T: (PanelDay, PanelTotals)](figures: T) -> T:
    """A form campaign's figures with the provider's lead count in the slot."""
    if not (figures.impressions or figures.spend_minor or figures.leads_reported):
        return replace(figures, received=figures.leads)
    return replace(figures, leads=figures.leads_reported, received=figures.leads)


def panel_total(days: Iterable[PanelDay]) -> PanelTotals:
    """Every additive figure summed. Rates are properties of the result."""
    rows = list(days)
    return PanelTotals(
        spend_minor=MinorUnits(sum(row.spend_minor for row in rows)),
        impressions=sum(row.impressions for row in rows),
        clicks=sum(row.clicks for row in rows),
        link_clicks=sum(row.link_clicks for row in rows),
        leads=sum(row.leads for row in rows),
        qualified=sum(row.qualified for row in rows),
        leads_reported=sum(row.leads_reported for row in rows),
        received=sum(row.received for row in rows),
        results=sum(row.results for row in rows),
        recallers=sum(row.recallers for row in rows),
        profile_visits=sum(row.profile_visits for row in rows),
        video_plays=sum(row.video_plays for row in rows),
        video_thruplays=sum(row.video_thruplays for row in rows),
    )


def newest_measured(days: Sequence[PanelDay]) -> PanelDay | None:
    """The most recent day the campaign actually ran, or nothing."""
    for row in reversed(days):
        if row.is_measured:
            return row
    return None


def frequency_bp(day: PanelDay | PanelTotals) -> int:
    """How often the average person reached saw the ad, in hundredths."""
    return basis_points(formulas.frequency(day.impressions, day.reach))


__all__ = [
    "BASIS_POINTS",
    "PER_MILLE",
    "PanelDay",
    "PanelTotals",
    "frequency_bp",
    "newest_measured",
    "panel_total",
    "with_provider_leads",
]
