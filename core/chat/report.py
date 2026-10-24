"""What one week of advertising says about itself.

The numbers are the product's own arithmetic and the explanation is one
sentence from Claude - and the split is the whole design. "Thirty-four
leads, twelve percent cheaper" is a calculation and needs no model. "Why
they got cheaper" is a reading, and it is different on every account.

**The cause is chosen, never found.** :attr:`WeeklyReport.changes` is a
closed list this product computed - a change that landed, a campaign that
started, a campaign that stopped, a quality share that moved - and the
model's only job is to tie the movement to at most one of them, or to say
it cannot. An empty list means no call is made at all: with nothing to
choose from, anything written would be invention. Same shape as the agent,
where the rules decide and Claude writes the sentence.

**Silence is a real answer here.** A week that moved less than its own
counting error gets no explanation and says so, because at five leads
against six there is nothing to explain and a confident sentence about it
would talk somebody into moving a budget on a coin toss. See
:mod:`core.metrics.significance`.

Values arrive already rendered, as they do in :mod:`core.chat.context`, and
for the same reason: a figure the model echoes back should look like the
figure on the screen the person is comparing it against.
"""

from dataclasses import dataclass, field
from typing import Final, Literal

from core.chat.daily import CAUSE_EN, STATE_EN, Census, DayCampaign
from core.chat.numbers import figures_in
from core.chat.results import RESULT_EN
from core.metrics import Movement

# Why a week has no sentence under it. Codes rather than text: three
# languages read these, and the arithmetic has no reader.
Silence = Literal["", "empty", "noise", "no_change"]


@dataclass(frozen=True, slots=True)
class KindFigures:
    """One kind of result inside a week: its own count, on its own money.

    **A week is not one number when it bought two things.** A page running
    a form campaign beside a chat campaign has two counts in two units and
    two prices, and the one arithmetic this product never does is adding
    them - a conversation is not an enquiry, and the spend behind one is
    not the spend behind the other. The pair on :class:`WeekFigures` is the
    headline, about the kind the money mostly went to; this is every kind
    the week actually bought, each priced out of what was spent on it.

    Rendered, like everything else a surface prints from here.
    """

    kind: str
    results: int
    # What went on this kind alone, which is what its price is divided out
    # of. The week's own spend above it is every kind together.
    spend: str
    cost: str
    label: str = ""
    cost_label: str = ""


@dataclass(frozen=True, slots=True)
class WeekFigures:
    """One week, summed and formatted. Money is a string like everywhere.

    **The week is denominated in whatever the advertising bought.** This
    product sells eight goals of which one produces a lead, so a week
    denominated in leads reports nought and a dash for a week of chat
    campaigns - on the cabinet card, in the Telegram message, and in the
    report handed to the model, which then has a nought to explain.

    ``results`` and ``result_cost`` are the only pair, rather than a pair
    per kind: on a form account they hold the lead count and the cost per
    lead, and a second pair of fields saying the same thing in a second
    spelling is a pair that eventually disagrees.

    ``qualified`` and ``cpql`` are the withdrawn ones and are not that.
    They divide by a verdict somebody set by hand, which no screen can set
    at the moment - see `templates/leads/partials/_live.html` - and they
    stay so the week can go back to being about them.
    """

    spend: str
    qualified: int
    cpql: str
    # The same money as an integer, for the one question a rendered string
    # cannot answer: was anything spent at all. A week that bought nothing
    # is silent, and a week that bought nothing *with money* is the one
    # week most worth putting on a phone - see
    # :attr:`WeeklyReport.worth_sending`.
    spend_minor: int = 0
    # How many of the seven days actually had spend. Counts are only
    # comparable across two weeks that ran for the same number of days; a
    # rate is comparable whatever the days, which is why the two are kept
    # apart below.
    active_days: int = 0
    # What the money bought, and what one of them cost.
    kind: str = "lead"
    results: int = 0
    result_cost: str = "—"
    # The same two things in the reader's own language, already rendered -
    # the rule this module opens with. A screen prints these; the report
    # handed to the model prints :data:`RESULT_EN` instead.
    result_label: str = ""
    result_cost_label: str = ""
    # Every countable kind the week bought, dearest first, each with the
    # money that bought it. The pair above is the first of these; a week
    # that bought one thing has one entry and reads exactly as it did.
    kinds: tuple[KindFigures, ...] = ()


@dataclass(frozen=True, slots=True)
class CampaignLine:
    """One campaign's week, for the two lines a report names.

    Ranked by results and never by cost per result. A week gives a single
    campaign a handful of them, and a cost built on two would put whichever
    campaign got lucky at the top of a list labelled "best" - the exact bad
    reading ``SegmentComparison`` splits four ways to avoid.

    It ranked by *qualified* leads until that marking was withdrawn, and
    ``qualified`` is still carried here so it can go back to doing so.

    **Only campaigns of one kind are ever ranked against each other.** Five
    thousand times shown and three enquiries are not two scores on one
    scale, and "best" over a mixed account would name whichever kind counts
    in the largest units. Which kind is the week's own - see
    ``apps.chat.selectors.report``.
    """

    name: str
    spend: str
    leads: int
    qualified: int
    # The count this row is ranked on, and the English word for it in the
    # report handed to the model. Both are the lead figures on a form
    # account; on a chat one they are conversations, and a line saying "3
    # leads" about a campaign that produced none is the thing the model
    # would then have written a sentence about.
    results: int = 0
    word: str = "leads"
    # The same word in the reader's own language, singular and lowercase,
    # for the two lines a screen draws: «Eng ko'p suhbat», «birorta suhbat
    # bermadi». Already rendered, like everything a person reads here.
    label: str = ""


@dataclass(frozen=True, slots=True)
class Change:
    """One thing that changed in the account during the week.

    ``kind`` is what happened, from a closed set. ``what`` is the sentence
    a person would recognise, already in their language.

    This is the candidate list, and it is the report's main defence. The
    model picks from it or says nothing; it is never asked to think of a
    cause, because a cause thought of is a cause invented.
    """

    kind: Literal["applied", "started", "stopped", "quality"]
    what: str


@dataclass(frozen=True, slots=True)
class WeeklyReport:
    """The week, the week before it, and what may be said about the two."""

    since: str
    until: str
    now: WeekFigures
    before: WeekFigures
    # The code every money string above is written in, for a sum the
    # message adds up itself - what the campaigns left off its list spent.
    currency: str = ""
    # Which page this week belongs to, already the name a reader knows it
    # by, and empty for the only page there is. A message on a phone has no
    # header saying which page it is about; a screen does.
    page: str = ""
    # The same page as the provider names it. Two pages can carry the same
    # name and the name above is empty for the only page there is, so what
    # a journal claims a week under has to be this instead.
    page_id: str = ""
    headline: str = ""
    # What campaigns made in Ads Manager spent on this page over the week,
    # as money text, or empty. Never added to a figure above: the week
    # reports what this product runs, and this is the one line saying what
    # it left out - the same line the daily message carries, so the two
    # cannot describe the account differently.
    elsewhere: str = ""
    # What this page's own advertising spent in a currency this week is not
    # written in, one entry per currency, or empty - which is every account
    # that pays for its page out of one. Beside the week and never in it:
    # nothing converts money here, so two currencies added make a figure in
    # neither, out by the size of an exchange rate rather than a rounding.
    other_currency: tuple[str, ...] = ()
    # ``default_factory`` for a frozen dataclass whose default is a
    # frozen dataclass: the value is immutable either way, and this is
    # the spelling that says so without a call in the class body.
    move: Movement = field(default_factory=Movement)
    best: CampaignLine | None = None
    barren: CampaignLine | None = None
    changes: tuple[Change, ...] = ()
    # Every campaign that spent this week, the biggest first, judged by the
    # daily message's rules - see :func:`core.chat.daily.census`. The
    # message names the few in ``attention`` and folds the rest away.
    campaigns: tuple[DayCampaign, ...] = ()
    census: Census = field(default_factory=Census)
    attention: tuple[DayCampaign, ...] = ()
    # The agent's proposals about this page that wait for an answer now.
    open_proposals: int = 0
    # Whether the week's last day was read again after it ended. The
    # message goes out at a fixed hour either way and says so when not.
    final: bool = True

    @property
    def counts_comparable(self) -> bool:
        """Whether the two weeks ran long enough to compare their counts.

        Rates already survive a short week - a cost per lead is a cost per
        lead over three days as over seven - but "twelve leads against
        thirty" is a comparison between a fortnight and a Tuesday when one
        of the weeks only ran for two days.
        """
        return self.now.active_days == self.before.active_days

    @property
    def silence(self) -> Silence:
        """Why there is no explanation under this week. ``""`` when there is.

        Three different silences, and they are not interchangeable. A week
        with nothing in it is not a week whose movement was small, and
        neither is a clear movement nobody changed anything to cause.
        """
        if not self.now.results and not self.before.results:
            return "empty"
        if not self.headline:
            return "noise"
        if not self.changes:
            return "no_change"
        return ""

    @property
    def worth_sending(self) -> bool:
        """Whether this week belongs on a phone at all.

        Spend is the test, not results. A week that produced nothing while
        the money kept going is precisely the week somebody needs told
        about, and it was the one week that used to be silent: the
        "nothing happened" silence below is about having no *sentence* to
        write, and sending was wrongly decided by the same question.

        A week with no spend and no results either way is genuinely empty,
        and a Monday ping saying so every week is how a channel teaches
        somebody to ignore it.
        """
        return bool(self.now.spend_minor or self.now.results or self.before.results)

    @property
    def spent_for_nothing(self) -> bool:
        """Money went out and nothing came back. Said in the message itself.

        The figures already print a nought beside the spend, but a nought
        in a list reads as a missing number; this is what lets the message
        say it in words.

        **Every kind the week bought, not the headline one.** A page that
        ran a form campaign and a chat campaign has money against two
        counts, and "nothing came back" said because the smaller of them is
        nought is a sentence about a week that worked.

        And never for a week this product cannot count at all: a campaign
        whose result is a sale on the advertiser's own site has no count
        here, so a nought is this product's blindness rather than the
        week's finding - the same rule the evening message keeps.
        """
        if not self.now.spend_minor or not self.now.kinds:
            return False
        return not any(row.results for row in self.now.kinds)

    @property
    def wants_sentence(self) -> bool:
        """Whether asking Claude is worth doing at all.

        Any week that spent. The reading says how the week went and what to
        do this week, which every week with money in it has an answer to;
        the cause of a movement is still only ever picked from
        :attr:`changes` - the prompt holds that line, and the figure gate
        holds the numbers.
        """
        return self.now.spend_minor > 0

    def render(self) -> str:
        """The report as the model sees it. English labels, local figures.

        English for the same reason the prompts are: these are instructions
        to a model rather than text for a person, and a label that changed
        with the reader's language would make two accounts' calls
        incomparable.
        """
        return "\n".join(self._lines())

    def figures(self) -> frozenset[str]:
        """Every figure this report handed over. The gate's allow-set.

        Read back out of the rendered text rather than collected while it
        was built - the rule :meth:`core.chat.context.ChatContext.figures`
        follows, and for the same reason. A set assembled separately is a
        second source of truth, and the first time the two disagree the
        gate either masks a real figure or lets an invented one through.
        """
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
        # The two the marking fed are not written, and this is the one
        # place where leaving them in would be worse than a blank card:
        # what this list says is what the model may print, so a nought
        # here is a sentence about a week in which nothing was any good.
        #
        #     f"- Qualified: {week.qualified}",
        #     f"- Cost per qualified lead: {week.cpql}",
        #
        # **The count and the cost are named after what the money bought.**
        # Saying "Leads" and "Cost per lead" whatever the campaigns were
        # for hands the model a nought on a week of conversations and asks
        # it to explain one - and this list is also the gate's allow-set,
        # so the conversation count it should write about would be the one
        # figure it was forbidden to print.
        count, cost = RESULT_EN.get(week.kind, RESULT_EN["lead"])
        if len(week.kinds) < 2:
            return [
                f"- Spend: {week.spend}",
                f"- {count}: {week.results}",
                f"- {cost}: {week.result_cost}",
                f"- Days with spend: {week.active_days}",
            ]
        # **A week that bought two things is never one figure.** The spend
        # above covers every kind; each count below is priced out of the
        # money that bought it alone, because the alternative - one count
        # against the whole week's spend - is a price that is wrong by
        # whatever the other kind cost. Handed over this way so the model
        # cannot do that division either: what it may print is what is on
        # these lines.
        lines = [f"- Spend: {week.spend} (across more than one kind of result)"]
        for row in week.kinds:
            words = RESULT_EN.get(row.kind, RESULT_EN["none"])
            lines.append(
                f"- {words[0]}: {row.results}, "
                f"spend on them {row.spend}, {words[1]} {row.cost}"
            )
        return [*lines, f"- Days with spend: {week.active_days}"]

    def _state_of(self, row: CampaignLine) -> str:
        """Its state right now, from the campaign list below, or nothing.

        Without it the model advised looking at a campaign that took money
        for nothing and had been paused since.
        """
        state = next(
            (item.state for item in self.campaigns if item.name == row.name), ""
        )
        return f", state right now: {STATE_EN.get(state, state)}" if state else ""

    @staticmethod
    def _campaign(row: CampaignLine) -> str:
        # Was "{qualified} qualified of {leads} leads" - the first half
        # goes with the marking, the second is what stays.
        return f"- {row.name} - {row.results} {row.word}, spend {row.spend}"


# How many campaigns the model is shown one by one. The rest are counted.
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
