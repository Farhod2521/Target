"""What one finished day of advertising says about itself.

The figures are the product's own arithmetic, and Claude reads them - a
sentence under the day, a verdict and a line under each campaign, and at
most one thing worth doing. The split is the weekly report's: counting needs
no model, and "is this going well" is a reading that differs on every
account.

**Only a finished day is read, and only once the night has read it again.**
A campaign with three hours of budget left is not a failure on the strength
of its afternoon, and the platform keeps revising a day's counts after the
day ends.

Values arrive already rendered, as in :mod:`core.chat.report`, and for the
same reason: a figure the model echoes back should look like the figure on
the screen the person compares it against. The allow-set for the figure
gate is read back out of the rendered text.
"""

from dataclasses import dataclass
from datetime import date
from typing import Final

from core.chat.numbers import figures_in
from core.chat.results import RESULT_EN

# What a campaign's state is called in the report handed to the model.
STATE_EN: Final[dict[str, str]] = {
    "active": "running",
    "paused": "paused",
    "paused_above": "paused with the campaign above it",
    "pending": "waiting for the platform's review",
    # Refused, or still delivering with a fault the platform reported - the
    # one state covers both, so it must not read as a stop.
    "rejected": "the platform reported a problem",
    "finished": "finished",
}

# What a figure with no answer prints, here and on the phone.
NO_FIGURE: Final = "\u2014"

# What each cause is called in the report handed to the model - the
# product's own diagnosis of one group, in the language the rest of this
# report is written in. See ``core.agent.diagnosis``, which chooses it, and
# ``apps.agent.constants.DiagnosisCause``, which names it for a reader.
#
# A day's figures say a campaign did badly; only this says what is wrong
# with it. Without it the reading is a verdict with nothing behind it, and
# the model is forbidden to supply the missing half itself.
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
    """One campaign's day, rendered twice: for the model and a reader.

    The ``*_label`` fields are already in the reader's language; ``kind``
    and ``state`` are codes the English report is built from. ``cost`` and
    ``usual_cost`` are money strings or a dash. ``reported`` is the
    provider's own lead count, kept for a lead campaign whose two counts
    differ - nought everywhere else.
    """

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
    # The same money as numbers, in minor units, for the one reader that
    # compares rather than prints: the check on the model's verdict -
    # :func:`settled`. ``None`` where there is nothing to divide by.
    spend_minor: int = 0
    cost_minor: int | None = None
    usual_cost_minor: int | None = None
    # The diagnosis of the part of this campaign carrying the most money,
    # and the figure that decided it. ``cause`` is the code the English
    # report is built from, the other two the reader's own words - the same
    # pattern as ``state`` and ``state_label`` above. All three are empty
    # for a campaign whose groups were found well or not diagnosed at all.
    #
    # **It reads a window, not this day.** A cause rests on the days the
    # nightly diagnosis compares; a campaign that did well yesterday can
    # carry one, and the prompt says so.
    cause: str = ""
    cause_label: str = ""
    cause_line: str = ""


def settled(verdict: str, *, campaign: DayCampaign) -> str:
    """The model's word for a campaign's day, held to three plain facts.

    The word is written without the arithmetic being done, and two of its
    three values are claims the figures can refute. So three rules the
    figures decide, and the word gives way where it breaks one:

    - money spent and no result at all is never "good";
    - a campaign the provider is still learning on is at most "watch" -
      its price this week is the provider still searching;
    - one whose result cost less than usual is never "bad".
    """
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


# Where one campaign's day stands, counted rather than read. The same
# three words the model's verdict uses, and deliberately not the model's
# own: the message says how many campaigns are in each, and a census a
# model wrote is one that comes out different when it is asked twice. It is
# also the only census an account has where the reading was never written -
# no key, no allowance, a call that failed.
FINE: Final = "good"
WATCH: Final = "watch"
BURNING: Final = "bad"


def standing(campaign: "DayCampaign") -> str:
    """Which of the three this campaign's day was, from the figures alone.

    The order is the order the rules are allowed to overrule each other in,
    and it is :func:`settled`'s order: a campaign the platform is still
    learning on is never worse than "watch", whatever it spent, because its
    price today is the platform still searching.
    """
    if campaign.kind == "none":
        # Nothing here counts what this campaign was bought for - a
        # purchase on somebody else's website, usually - so "spent and
        # brought nothing" would be a sentence about this product's own
        # blindness rather than about the day. The figures screen says as
        # much in words; a census has no room to, so it leaves the campaign
        # out of the verdict rather than reading a nought it never counted.
        return FINE
    if campaign.learning:
        return WATCH
    if _nothing_back(campaign):
        # With a usual price, burning only once the money would have bought
        # one result at it: a few coins on a quiet morning are not a
        # verdict. With none, any money for nothing is - a first campaign
        # is exactly the one nobody else is watching.
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
    """How the day came out, in counts rather than in rows.

    What a message says instead of a list. Twenty campaigns is twenty
    blocks nobody reads on a phone, and the reader's question is not "what
    did each one do" but "is anything wrong" - which is three numbers.
    """

    spenders: int = 0
    fine: int = 0
    watch: int = 0
    burning: int = 0
    # The day's results and the word for them, and only where every
    # campaign that spent was bought for the same thing. Eight kinds of
    # result are counted on eight scales, and adding a conversation to an
    # enquiry is the one piece of arithmetic this product never does - so a
    # mixed day reports its spend and leaves the count to the campaigns.
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


# How many campaigns a message names outright. Three is what fits on a
# phone above the fold; the rest of the day is the census above them and
# the folded list under them.
ATTENTION_ROWS: Final = 3


def worth_naming(
    campaigns: tuple["DayCampaign", ...], *, limit: int
) -> tuple["DayCampaign", ...]:
    """The few campaigns a message names, worst first and dearest within it.

    Money burnt before money spent dearly, because the first is a decision
    waiting to be made and the second is a number to keep an eye on. A
    campaign that came out fine is not named for its day - the census has
    already said how many of those there were - unless the product's own
    diagnosis found something wrong with it, which reads several days and
    is the one thing on the report that says what to fix.
    """
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
    """One page's finished day, and what is waiting in the cabinet now.

    A page and not an ad account: the subscription is sold per page, and one
    page's advertising can be paid for out of several ad accounts. ``page``
    is empty for the one report that is not about a page - the spend whose
    page the mirror cannot yet name, which is reported rather than dropped.
    """

    day: date
    day_text: str
    currency: str
    spend: str
    spend_minor: int
    # Whether the night's re-read of this day has happened. False where the
    # report went out in the afternoon instead, which it does rather than
    # skip a day whose sync never finished - the figures are then what had
    # arrived by then, and everything reading this report is told so.
    final: bool = True
    page: str = ""
    page_id: str = ""
    campaigns: tuple[DayCampaign, ...] = ()
    # How many campaigns spent that day, which is not the length of the
    # tuple above: only the biggest are listed. The total is every one of
    # them, so a report that counted the listed ones would print a sum its
    # own breakdown does not add up to - and hand the model a figure to
    # reason from that is simply wrong.
    spenders: int = 0
    # What the ones left out of the list spent between them, as money text,
    # or empty where nothing was left out.
    rest: str = ""
    # The same money as a number, for the reader that has to add to it: a
    # message too long for Telegram drops campaigns of its own and has to
    # say what *those* spent as well. Money is formatted where there is a
    # currency to format it with, which is not here.
    rest_minor: int = 0
    idle: int = 0
    open_proposals: int = 0
    # How the day came out, counted over every campaign that spent - not
    # over the listed few. The list is the biggest handful; the counts are
    # the account, and a message that said "9 of them are fine" about the
    # nine it happened to print would be answering a question nobody asked.
    day_census: Census = Census()
    # The few worth naming, chosen over every campaign that spent. Apart
    # from ``campaigns`` because that list is the biggest handful and this
    # is the worst handful, and on a busy account they are not the same
    # campaigns: money burnt quietly in ninth place is exactly what a list
    # sorted by spend hides.
    attention: tuple[DayCampaign, ...] = ()
    # What campaigns made in Ads Manager spent on this page that day, as
    # money text, or empty. Never in a figure above and never shown to the
    # model: it is the one line saying what the report left out.
    elsewhere: str = ""
    # What this page's own advertising spent that day in a currency this
    # report is not written in, one entry per currency. In no figure above
    # and never added to one: money is an amount and a code here, and
    # there is no rate anywhere to turn one code into another.
    other_currency: tuple[str, ...] = ()

    @property
    def is_quiet(self) -> bool:
        """Nothing was spent that day, so there is nothing to report.

        A day whose only spending was in another currency is not quiet: the
        money is real and the report has a line for it, and dropping the
        message would leave the owner with no word of it at all.
        """
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
            # Named so the reading cannot describe advertising from another
            # page as this one's. An owner with two pages gets two of these
            # and neither may borrow the other's figures.
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
            # The same census the message prints, so the sentence you write
            # and the counts under it cannot disagree.
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
        # As it stands now, not as it stood on the reported day - nothing
        # records yesterday's delivery, and a model told "paused" about a
        # campaign that ran all day would explain the day by a stop that
        # happened this morning.
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
