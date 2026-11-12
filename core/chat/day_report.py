"""One finished day or week, as the morning message prints it: figures only.

Nothing here judges a day. No verdict, no "needs attention", no reading by
a model: the message says what was spent and what came of it, and a reader
who wants to know whether that is good asks - the assistant answers that,
with the figures in front of it.

**By goal and nothing below it.** The message never names a campaign, a group
or an advert: what each goal cost and brought is what a phone is read for, and
the cabinet is one press away for the rest.

Values arrive already rendered in the pair's money, because a figure on the
phone should look like the figure on the screen it is compared with. The
numbers beside them are kept for the one reader that adds rather than prints:
the day's own total.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class Result:
    """One goal on one line: how many, what one cost, what the goal spent.

    ``word`` is the bare singular - «murojaat», «suhbat». ``cost`` is money
    text or a dash; ``per_thousand`` says it is the price of a thousand
    rather than of one, which is how a showing is priced.
    """

    kind: str
    count: int
    word: str
    cost: str
    spend: str = ""
    per_thousand: bool = False
    # The same goal over the period before; ``before_spend`` empty when it
    # had no money then.
    before_spend: str = ""
    before_count: int = 0
    before_cost: str = ""


@dataclass(frozen=True, slots=True)
class Figure:
    """What a pair came to: the money, and what it brought.

    ``results`` holds a kind once, the kind the most money went on first.
    ``uncounted`` is the money of goals nothing here counts - a purchase on
    somebody else's website - so the lines still add up to ``spend``.
    """

    spend: str
    spend_minor: int
    results: tuple[Result, ...] = ()
    uncounted: str = ""


@dataclass(frozen=True, slots=True)
class DailyReport:
    """One pair's day: a page and one ad account it is paired with.

    ``figure`` is all the pair's money, whoever built the campaign: ``here``
    and ``elsewhere`` are the same money split by where it was built, empty
    where there is none. ``elsewhere_apart`` is a plan that may not describe
    what Ads Manager built: that money stays out of ``results`` and is named
    on one line of its own, so the lines still add up.
    """

    day: date
    day_text: str
    currency: str
    pair: str
    page: str
    page_id: str
    account: str
    account_id: str
    figure: Figure
    # The day is today and not over: its figures are what has arrived so
    # far, and the message says so rather than "not final".
    ongoing: bool = False
    here: str = ""
    elsewhere: str = ""
    elsewhere_apart: bool = False
    # The day before's money, as text; empty when there was none to compare.
    before: str = ""
    before_minor: int = 0
    # How far the money moved from the period before, as «+94%».
    change: str = ""
    # Ads Manager campaigns switched on, silent that day, but spending lately.
    idle: int = 0
    # The agent's proposals on this pair waiting for an answer: weekly only.
    open_proposals: int = 0
    # What the page spent that day in a currency this report is not in.
    # Named rather than added: nothing here converts money.
    other_currency: tuple[str, ...] = ()

    @property
    def spend(self) -> str:
        return self.figure.spend

    @property
    def spend_minor(self) -> int:
        return self.figure.spend_minor

    @property
    def title(self) -> str:
        """«Page · Account», or the one name where both are called the same."""
        names = dict.fromkeys(part for part in (self.page, self.account) if part)
        return " · ".join(names)

    @property
    def is_quiet(self) -> bool:
        """Nothing was spent that day. A day whose only money was in another
        currency is not quiet: that money is real and has a line."""
        return self.spend_minor <= 0 and not self.other_currency


@dataclass(frozen=True, slots=True)
class DayTotal:
    """The period's money in one currency, and the period before's."""

    spend: str
    before: str = ""
    change: str = ""


@dataclass(frozen=True, slots=True)
class DayBook:
    """One owner's whole day or week: every chosen pair, and what fell outside.

    ``day`` is the period's first day and ``until`` its last, the same day for
    a daily report. ``outside`` is money spent on pages the subscription does not hold, one
    text per currency. It is named and never added to ``totals``: the owner
    has not chosen those pages, and no goal or name of theirs is printed.
    """

    day: date
    until: date
    day_text: str
    weekly: bool = False
    reports: tuple[DailyReport, ...] = ()
    totals: tuple[DayTotal, ...] = ()
    outside: tuple[str, ...] = ()
    final: bool = True
    ongoing: bool = False
    # Set when the connection was down before the period's last night was
    # read: the moment of the last read, in the cabinet's own time. The
    # figures stop there, and "not final yet" would promise a re-read that
    # cannot come.
    cut_off: str = ""

    @property
    def spent(self) -> tuple[DailyReport, ...]:
        return tuple(report for report in self.reports if not report.is_quiet)

    @property
    def quiet(self) -> tuple[DailyReport, ...]:
        return tuple(report for report in self.reports if report.is_quiet)

    @property
    def only(self) -> DailyReport | None:
        """The one pair that spent, whose day needs no list in front of it."""
        spent = self.spent
        return spent[0] if len(spent) == 1 else None

    @property
    def is_quiet(self) -> bool:
        return not self.spent and not self.outside


__all__ = ["DailyReport", "DayBook", "DayTotal", "Figure", "Result"]
