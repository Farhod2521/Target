"""What one week of advertising says about itself."""

from dataclasses import dataclass, field
from typing import Final, Literal

from core.chat.daily import CAUSE_EN, STATE_EN, Census, DayCampaign
from core.chat.numbers import figures_in
from core.chat.results import RESULT_EN
from core.metrics import Movement

Silence = Literal["", "empty", "noise", "no_change"]


@dataclass(frozen=True, slots=True)
class KindFigures:
    """One kind of result inside a week: its own count, on its own money."""

    kind: str
    results: int
    spend: str
    cost: str
    label: str = ""
    cost_label: str = ""


@dataclass(frozen=True, slots=True)
class WeekFigures:
    """One week, summed and formatted. Money is a string like everywhere."""

    spend: str
    qualified: int
    cpql: str
    spend_minor: int = 0
    active_days: int = 0
    kind: str = "lead"
    results: int = 0
    result_cost: str = "—"
    result_label: str = ""
    result_cost_label: str = ""
    kinds: tuple[KindFigures, ...] = ()


@dataclass(frozen=True, slots=True)
class CampaignLine:
    """One campaign's week, for the two lines a report names."""

    name: str
    spend: str
    leads: int
    qualified: int
    results: int = 0
    word: str = "leads"
    label: str = ""


@dataclass(frozen=True, slots=True)
class Change:
    """One thing that changed in the account during the week."""

    kind: Literal["applied", "started", "stopped", "quality"]
    what: str


@dataclass(frozen=True, slots=True)
class WeeklyReport:
    """The week, the week before it, and what may be said about the two."""

    since: str
    until: str
    now: WeekFigures
    before: WeekFigures
    currency: str = ""
    page: str = ""
    page_id: str = ""
    pair: str = ""
    headline: str = ""
    elsewhere: str = ""
    other_currency: tuple[str, ...] = ()
    move: Movement = field(default_factory=Movement)
    best: CampaignLine | None = None
    barren: CampaignLine | None = None
    changes: tuple[Change, ...] = ()
    campaigns: tuple[DayCampaign, ...] = ()
    census: Census = field(default_factory=Census)
    attention: tuple[DayCampaign, ...] = ()
    open_proposals: int = 0
    final: bool = True

    @property
    def counts_comparable(self) -> bool:
        """Whether the two weeks ran long enough to compare their counts."""
        return self.now.active_days == self.before.active_days

    @property
    def silence(self) -> Silence:
        """Why there is no explanation under this week. ``""`` when there is."""
        if not self.now.results and not self.before.results:
            return "empty"
        if not self.headline:
            return "noise"
        if not self.changes:
            return "no_change"
        return ""

    @property
    def worth_sending(self) -> bool:
        """Whether this week belongs on a phone at all."""
        return bool(self.now.spend_minor or self.now.results or self.before.results)

    @property
    def spent_for_nothing(self) -> bool:
        """Money went out and nothing came back. Said in the message itself."""
        if not self.now.spend_minor or not self.now.kinds:
            return False
        return not any(row.results for row in self.now.kinds)

    @property
    def wants_sentence(self) -> bool:
        """Whether asking Claude is worth doing at all."""
        return self.now.spend_minor > 0

    def render(self) -> str:
        """The report as the model sees it. English labels, local figures."""
        return "\n".join(self._lines())

    def figures(self) -> frozenset[str]:
        """Every figure this report handed over. The gate's allow-set."""
        return figures_in(self.render())

    def _lines(self) -> list[str]:
        lines = [
            f"## This week ({self.since} - {self.until})",
            *self._week(self.now),
            "",
            "## The week before",
            *self._week(self.before),
        ]
        if self.headline and self.move.direction != "flat":
            lines += [
                "",
                "## Movement",
                f"- {self.headline}: {self.move.direction} {self.move.percent}% "
                f"({'better' if self.move.is_good else 'worse'})",
            ]
        if not self.counts_comparable:
            lines += [
                "",
                "## Warning",
                "- The two weeks ran for a different number of days, so "
                "counts and spend are not comparable. Costs per result are.",
            ]
        if self.best is not None:
            lines += ["", "## Best campaign", self._campaign(self.best)]
        if self.barren is not None:
            lines += [
                "",
                f"## Campaign that produced no {self.barren.word}",
                self._campaign(self.barren) + self._state_of(self.barren),
            ]
        if self.changes:
            lines += ["", "## What changed this week"]
            lines += [f"- {item.what}" for item in self.changes]
        return [*lines, *self._campaign_lines()]

    def _campaign_lines(self) -> list[str]:
        """The week campaign by campaign, as the daily report hands it over."""
        lines = [
            "",
            "## Campaigns",
            "- The week's last day was read again after it ended"
            if self.final
            else "- The week's last day is NOT final: the nightly re-read had "
            "not happened when this was written",
            f"- Campaigns that spent this week: {self.census.spenders}",
        ]
        if self.census.spenders:
            lines.append(
                "- Of those: "
                f"{self.census.fine} came out at or below their cost the week "
                f"before, {self.census.watch} dearer or still learning, "
                f"{self.census.burning} spent with no result at all"
            )
        if self.open_proposals:
            lines.append(
                "- Proposals from the agent waiting for an answer: "
                f"{self.open_proposals}"
            )
        for index, row in enumerate(self.campaigns[:MAX_WEEK_CAMPAIGNS]):
            lines += ["", *_week_campaign(index, row)]
        if len(self.campaigns) > MAX_WEEK_CAMPAIGNS:
            lines += [
                "",
                f"- {len(self.campaigns) - MAX_WEEK_CAMPAIGNS} smaller campaigns "
                "are not listed",
            ]
        return lines

    @staticmethod
    def _week(week: WeekFigures) -> list[str]:
        count, cost = RESULT_EN.get(week.kind, RESULT_EN["lead"])
        if len(week.kinds) < 2:
            return [
                f"- Spend: {week.spend}",
                f"- {count}: {week.results}",
                f"- {cost}: {week.result_cost}",
                f"- Days with spend: {week.active_days}",
            ]
        lines = [f"- Spend: {week.spend} (across more than one kind of result)"]
        for row in week.kinds:
            words = RESULT_EN.get(row.kind, RESULT_EN["none"])
            lines.append(
                f"- {words[0]}: {row.results}, "
                f"spend on them {row.spend}, {words[1]} {row.cost}"
            )
        return [*lines, f"- Days with spend: {week.active_days}"]

    def _state_of(self, row: CampaignLine) -> str:
        """Its state right now, from the campaign list below, or nothing."""
        state = next(
            (item.state for item in self.campaigns if item.name == row.name), ""
        )
        return f", state right now: {STATE_EN.get(state, state)}" if state else ""

    @staticmethod
    def _campaign(row: CampaignLine) -> str:
        return f"- {row.name} - {row.results} {row.word}, spend {row.spend}"


MAX_WEEK_CAMPAIGNS: Final = 8


def _week_campaign(index: int, row: DayCampaign) -> list[str]:
    count, cost = RESULT_EN.get(row.kind, RESULT_EN["none"])
    state = STATE_EN.get(row.state, row.state or "unknown")
    if row.learning:
        state += ", the platform is still learning who to show it to"
    lines = [
        f'### {index}. "{row.name}"',
        f"- State right now: {state}",
        f"- Spend this week: {row.spend}",
    ]
    if row.kind != "none":
        lines += [
            f"- {count}: {row.results}",
            f"- {cost}: {row.cost}",
            f"- {cost} the week before: {row.usual_cost}",
        ]
    if row.cause:
        lines.append(
            f"- Diagnosis over the last few days: {CAUSE_EN.get(row.cause, row.cause)}"
        )
        if row.cause_line:
            lines.append(f"- The figure behind it: {row.cause_line}")
    return lines
