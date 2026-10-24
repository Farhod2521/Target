"""What one finished day of advertising says about itself."""

from dataclasses import dataclass
from datetime import date
from typing import Final

from core.chat.numbers import figures_in
from core.chat.results import RESULT_EN

STATE_EN: Final[dict[str, str]] = {
    "active": "running",
    "paused": "paused",
    "paused_above": "paused with the campaign above it",
    "pending": "waiting for the platform's review",
    "rejected": "the platform reported a problem",
    "finished": "finished",
}

NO_FIGURE: Final = "\u2014"

CAUSE_EN: Final[dict[str, str]] = {
    "provider_stopped": "the platform has stopped showing it",
    "landing_blocks": "the form or the website it sends people to is in the way",
    "too_early": "too early to judge",
    "worn_out": "the same people have seen it too often and have stopped clicking",
    "weak_creative": "people are shown the advert and hardly any of them click it",
    "costly_audience": "reaching this audience costs more than the account's usual",
    "promise_mismatch": (
        "people click it, and the platform rates the advert's quality low"
    ),
    "learning_limited": (
        "the platform gets too few results a week for it to learn who to show it to"
    ),
    "unclear": "the figures do not point at one cause",
}


@dataclass(frozen=True, slots=True)
class DayCampaign:
    """One campaign's day, rendered twice: for the model and a reader."""

    name: str
    kind: str
    state: str
    state_label: str
    learning: bool
    spend: str
    results: int
    result_label: str
    cost: str
    cost_label: str
    usual_cost: str
    reported: int = 0
    spend_minor: int = 0
    cost_minor: int | None = None
    usual_cost_minor: int | None = None
    cause: str = ""
    cause_label: str = ""
    cause_line: str = ""


def settled(verdict: str, *, campaign: DayCampaign) -> str:
    """The model's word for a campaign's day, held to three plain facts."""
    if campaign.learning:
        return "watch"
    cheaper = (
        campaign.cost_minor is not None
        and campaign.usual_cost_minor is not None
        and campaign.cost_minor < campaign.usual_cost_minor
    )
    if verdict == "bad" and cheaper:
        return "good"
    if verdict == "good" and _nothing_back(campaign):
        return "watch"
    return verdict


def _nothing_back(campaign: "DayCampaign") -> bool:
    """Money spent and no result by either count, ours or the provider's."""
    return campaign.spend_minor > 0 and max(campaign.results, campaign.reported) == 0


FINE: Final = "good"
WATCH: Final = "watch"
BURNING: Final = "bad"


def standing(campaign: "DayCampaign") -> str:
    """Which of the three this campaign's day was, from the figures alone."""
    if campaign.kind == "none":
        return FINE
    if campaign.learning:
        return WATCH
    if _nothing_back(campaign):
        usual = campaign.usual_cost_minor
        return WATCH if usual and campaign.spend_minor < usual else BURNING
    dearer = (
        campaign.cost_minor is not None
        and campaign.usual_cost_minor is not None
        and campaign.cost_minor > campaign.usual_cost_minor
    )
    return WATCH if dearer else FINE


@dataclass(frozen=True, slots=True)
class Census:
    """How the day came out, in counts rather than in rows."""

    spenders: int = 0
    fine: int = 0
    watch: int = 0
    burning: int = 0
    results: int = 0
    result_label: str = ""

    @property
    def all_fine(self) -> bool:
        """Every campaign that spent came out fine, and there was one."""
        return self.spenders > 0 and self.fine == self.spenders


def census(campaigns: tuple["DayCampaign", ...]) -> Census:
    """The counts, over every campaign that spent - not the listed few."""
    standings = [standing(campaign) for campaign in campaigns]
    earning = [item for item in campaigns if item.kind != "none"]
    kinds = {item.kind for item in earning}
    return Census(
        spenders=len(campaigns),
        fine=standings.count(FINE),
        watch=standings.count(WATCH),
        burning=standings.count(BURNING),
        results=sum(item.results for item in earning) if len(kinds) == 1 else 0,
        result_label=earning[0].result_label if len(kinds) == 1 else "",
    )


ATTENTION_ROWS: Final = 3


def worth_naming(
    campaigns: tuple["DayCampaign", ...], *, limit: int
) -> tuple["DayCampaign", ...]:
    """The few campaigns a message names, worst first and dearest within it."""
    ranked = sorted(
        (item for item in campaigns if standing(item) != FINE or item.cause),
        key=lambda item: (_rank(item), -item.spend_minor),
    )
    return tuple(ranked[:limit])


def _rank(campaign: "DayCampaign") -> int:
    """Worst first: money gone, then money dear, then a diagnosis alone."""
    word = standing(campaign)
    if word == BURNING:
        return 0
    return 1 if word == WATCH else 2


@dataclass(frozen=True, slots=True)
class DailyReport:
    """One page's finished day, and what is waiting in the cabinet now."""

    day: date
    day_text: str
    currency: str
    spend: str
    spend_minor: int
    final: bool = True
    page: str = ""
    page_id: str = ""
    campaigns: tuple[DayCampaign, ...] = ()
    spenders: int = 0
    rest: str = ""
    rest_minor: int = 0
    idle: int = 0
    open_proposals: int = 0
    day_census: Census = Census()
    attention: tuple[DayCampaign, ...] = ()
    elsewhere: str = ""
    other_currency: tuple[str, ...] = ()

    @property
    def is_quiet(self) -> bool:
        """Nothing was spent that day, so there is nothing to report."""
        return self.spend_minor <= 0 and not self.other_currency

    def render(self) -> str:
        """The day as the model sees it. English labels, local figures."""
        return "\n".join(self._lines())

    def figures(self) -> frozenset[str]:
        """Every figure this report handed over. The gate's allow-set."""
        return figures_in(self.render())

    def _lines(self) -> list[str]:
        lines = [
            f"## The day ({self.day_text}, finished)",
            f"- The Facebook page this report is about: {self.page}"
            if self.page
            else "- Advertising whose page is not recorded",
            f"- Spend: {self.spend}",
            *(
                [
                    "- Also paid that day in another currency, NOT included "
                    "in the spend above and never to be added to it: "
                    f"{' + '.join(self.other_currency)}"
                ]
                if self.other_currency
                else []
            ),
            "- The day's figures were read again after it ended"
            if self.final
            else "- The day's figures are NOT final: the nightly re-read had "
            "not happened when this was written, so they are what had "
            "arrived by the afternoon",
            f"- Campaigns that spent that day: {self.spenders}",
        ]
        if self.day_census.spenders:
            lines.append(
                "- Of those: "
                f"{self.day_census.fine} came out at or below their usual "
                f"cost, {self.day_census.watch} dearer or still learning, "
                f"{self.day_census.burning} spent with no result at all"
            )
        if self.rest:
            lines.append(
                f"- Only the {len(self.campaigns)} biggest are listed below; "
                f"the rest spent {self.rest} between them"
            )
        if self.idle:
            lines.append(
                "- Campaigns switched on right now that spent nothing on "
                f"that day: {self.idle}"
            )
        if self.open_proposals:
            lines.append(
                "- Proposals from the agent waiting for an answer: "
                f"{self.open_proposals}"
            )
        lines += ["", "## Campaigns"]
        for index, row in enumerate(self.campaigns):
            lines += ["", *self._campaign(index, row)]
        return lines

    @staticmethod
    def _campaign(index: int, row: DayCampaign) -> list[str]:
        count, cost = RESULT_EN.get(row.kind, RESULT_EN["none"])
        state = STATE_EN.get(row.state, row.state or "unknown")
        if row.learning:
            state += ", the platform is still learning who to show it to"
        lines = [
            f'### {index}. "{row.name}"',
            f"- State right now, not on the reported day: {state}",
            f"- Spend: {row.spend}",
        ]
        if row.kind != "none":
            said = f"- {count}: {row.results}"
            if row.reported > row.results:
                said += f" (the platform counted {row.reported})"
            lines += [
                said,
                f"- {cost}: {row.cost}",
                f"- {cost} over the 7 days before: {row.usual_cost}",
            ]
        if row.cause:
            lines.append(
                "- Diagnosis over the last few days: "
                f"{CAUSE_EN.get(row.cause, row.cause)}"
            )
            if row.cause_line:
                lines.append(f"- The figure behind it: {row.cause_line}")
        return lines


__all__ = [
    "ATTENTION_ROWS",
    "BURNING",
    "CAUSE_EN",
    "FINE",
    "NO_FIGURE",
    "STATE_EN",
    "WATCH",
    "Census",
    "DailyReport",
    "DayCampaign",
    "census",
    "settled",
    "standing",
    "worth_naming",
]
