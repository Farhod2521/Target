"""One pair's finished day, as the morning message prints it: figures only.

Nothing here judges a day. No verdict, no "needs attention", no reading by
a model: the message says what was spent and what came of it, and a reader
who wants to know whether that is good asks - the assistant answers that,
with the figures in front of it.

Values arrive already rendered, in the reader's language and the pair's
money, because a figure on the phone should look like the figure on the
screen it is compared with. The numbers beside them are kept for the one
reader that adds rather than prints: the message's own total.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class Result:
    """One kind of result on one line: how many, and what one cost.

    ``word`` is the bare singular - «murojaat», «suhbat». ``cost`` is money
    text or a dash; ``per_thousand`` says it is the price of a thousand
    rather than of one, which is how a showing is priced.
    """

    kind: str
    count: int
    word: str
    cost: str
    per_thousand: bool = False


@dataclass(frozen=True, slots=True)
class Figure:
    """What one row came to: the money, and what it brought.

    ``results`` holds a kind once, in the order first met. Empty with
    ``counted`` false where nothing here counts what the money was spent
    on - a purchase on somebody else's website - which the message says in
    words rather than printing a nought it never counted.
    """

    spend: str
    spend_minor: int
    results: tuple[Result, ...] = ()
    counted: bool = True


@dataclass(frozen=True, slots=True)
class AdLine:
    """One advert that spent that day."""

    name: str
    figure: Figure


@dataclass(frozen=True, slots=True)
class GroupLine:
    """One ad group that spent that day, and the adverts under it.

    ``running`` is the group as it stands now - its own switch and its
    campaign's - not as it stood on the day: nothing records yesterday's
    state, and the message says "switched on now" for that reason.
    """

    campaign: str
    name: str
    running: bool
    figure: Figure
    ads: tuple[AdLine, ...] = ()


@dataclass(frozen=True, slots=True)
class DailyReport:
    """One pair's day: a page and one ad account it is paired with.

    ``groups`` holds every group that spent, the running ones first and
    each half by money. ``final`` is false where the night's re-read had
    not happened when this was built, and the message says so.
    """

    day: date
    day_text: str
    currency: str
    pair: str
    page: str
    page_id: str
    account: str
    figure: Figure
    final: bool = True
    # The day is today and not over: its figures are what has arrived so
    # far, and the message says so rather than "not final".
    ongoing: bool = False
    groups: tuple[GroupLine, ...] = ()
    campaigns: int = 0
    # This pair's money the cabinet draws here but whose page was only
    # guessed, as money text. In no figure above - the line that makes the
    # message and the cabinet agree.
    unplaced: str = ""
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
        """«Page · Account», the pair as the cabinet's header names it."""
        return " · ".join(part for part in (self.page, self.account) if part)

    @property
    def is_quiet(self) -> bool:
        """Nothing was spent that day. A day whose only money was in another
        currency is not quiet: that money is real and has a line."""
        return self.spend_minor <= 0 and not self.other_currency

    @property
    def running(self) -> tuple[GroupLine, ...]:
        return tuple(group for group in self.groups if group.running)

    @property
    def stopped(self) -> tuple[GroupLine, ...]:
        return tuple(group for group in self.groups if not group.running)

    @property
    def ad_count(self) -> int:
        return sum(len(group.ads) for group in self.groups)


__all__ = ["AdLine", "DailyReport", "Figure", "GroupLine", "Result"]
