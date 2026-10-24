"""Which figures a campaign panel may show, and what each one is.

A catalogue and nothing else: no arithmetic, no query, no label. It exists
because "which numbers appear on the screen" became a decision the owner
makes rather than one this code makes, and a decision stored in a database
needs a fixed vocabulary to be stored *in*.

**Keys are stored and are therefore permanent.** A preference row holds a
list of these strings. Renaming one silently drops that card from every
account that had chosen it, which is the worst shape this failure can take:
nothing errors, a number just stops being on the screen.

**Two bases, and the difference is not cosmetic.** A ``period`` card is a
range summed - or a ratio recomputed from the sums, never averaged. A
``day`` card is one day's row, because the figure underneath it counts
*people*: reach and the unique counts cannot be added across days without
counting somebody who came back twice, and a frequency built on a summed
reach is wrong in the direction that reassures. Those three are offered as
the newest measured day and labelled as such, which is the only honest way
to show them at all.

Labels live in ``apps.metrics.cards`` - three languages read them, and this
package may not import Django to translate. The two are pinned together by
a test, the same way ``TargetingMode`` and its domain twin are.
"""

from dataclasses import dataclass
from typing import Final, Literal

CardKey = Literal[
    "spend",
    "cpl",
    "cpql",
    "cpm",
    "cpc",
    "platform_cpl",
    "leads",
    "qualified",
    "quality_share",
    "leads_reported",
    "impressions",
    "reach",
    "frequency",
    "ctr",
    "link_ctr",
    "clicks",
    "link_clicks",
    "unique_clicks",
    "video_plays",
    "video_thruplays",
    "video_hold",
]

CardGroup = Literal["money", "result", "delivery", "engagement", "video"]

# How the figure is arrived at. See the module note: this is what keeps a
# count of people out of a sum over thirty days.
Basis = Literal["period", "day"]

# What kind of number comes out, which is all the screen needs to format it.
# ``money`` is minor units, ``percent`` and ``ratio`` are hundredths, and
# ``count`` is a count.
Unit = Literal["money", "count", "percent", "ratio"]

# The order the groups are drawn in, and it is the order somebody asks the
# questions: what did it cost, what did it produce, how many people saw it,
# what did they do, and - only for the campaigns that have one - the video.
GROUPS: Final[tuple[CardGroup, ...]] = (
    "money",
    "result",
    "delivery",
    "engagement",
    "video",
)


@dataclass(frozen=True, slots=True)
class CardSpec:
    """One figure the panel can draw.

    ``lower_is_better`` is here rather than at the screen because it is a
    fact about the figure and not about the drawing of it: a falling cost
    is good news and a falling lead count is not, and a panel that coloured
    both arrows green would teach somebody to ignore the colour.

    Which figures reach a *campaign row* is not a fact about the figure and
    is not here: it is ``ROW_KEYS`` below, three names fixed for every
    cabinet.
    """

    key: CardKey
    group: CardGroup
    basis: Basis
    unit: Unit
    lower_is_better: bool = False
    is_default: bool = False


# Every figure, in the order it is drawn.
#
# **Five are on by default and the rest are not**, which is the whole point
# of the catalogue. The five are the ones a person who has never bought
# advertising can act on: what it cost, what it produced, and whether
# anybody clicked. The other thirteen answer questions somebody has to know
# to ask - and a panel that opened with eighteen figures on it would be one
# nobody read at all.
#
# The count was eight over twenty-one until the three the quality marking
# fed were withdrawn - see the note where ``cpql`` used to stand, at the
# head of the money group below.
CARDS: Final[tuple[CardSpec, ...]] = (
    # --- Money -------------------------------------------------------
    # The cost per qualified lead led this group and was on by default.
    # It is offered nowhere while the quality marking is withdrawn - see
    # `templates/leads/partials/_live.html` - because a settings screen
    # that offers a figure no screen can fill is a tick somebody spends
    # a week waiting on. ``CardKey`` still names it, so restoring the
    # marking is uncommenting this entry and the two below it.
    #
    #     CardSpec(
    #         key="cpql",
    #         group="money",
    #         basis="period",
    #         unit="money",
    #         lower_is_better=True,
    #         is_default=True,
    #     ),
    CardSpec(
        key="cpl",
        group="money",
        basis="period",
        unit="money",
        lower_is_better=True,
        is_default=True,
    ),
    CardSpec(
        key="spend",
        group="money",
        basis="period",
        unit="money",
        is_default=True,
    ),
    CardSpec(
        key="cpm", group="money", basis="period", unit="money", lower_is_better=True
    ),
    CardSpec(
        key="cpc", group="money", basis="period", unit="money", lower_is_better=True
    ),
    # What the **provider** says a lead cost, beside what we say it cost.
    #
    # The reconciliation figure, and the reason this catalogue has it: an
    # advertiser comparing this screen against Ads Manager and finding a
    # difference has no way to tell which of the two is wrong. Ours divides
    # by the leads that reached this product; this one divides by the count
    # the provider reports, and the gap between them is a webhook that went
    # missing rather than a campaign that got worse.
    #
    # Computed from the two counts rather than read from the provider's own
    # per-day copy of it, which is stored. A range's cost per lead is its
    # spend over its leads and never the mean of its days - the same rule
    # ``cpm`` and ``cpc`` above follow, and the reason the request asks for
    # counts and does its own division.
    CardSpec(
        key="platform_cpl",
        group="money",
        basis="period",
        unit="money",
        lower_is_better=True,
    ),
    # --- Results -----------------------------------------------------
    CardSpec(
        key="leads",
        group="result",
        basis="period",
        unit="count",
        is_default=True,
    ),
    # Withdrawn with the marking that fills them - see the note above
    # ``cpql`` at the head of the money group:
    #
    #     CardSpec(
    #         key="qualified",
    #         group="result",
    #         basis="period",
    #         unit="count",
    #         is_default=True,
    #     ),
    #     CardSpec(
    #         key="quality_share",
    #         group="result",
    #         basis="period",
    #         unit="percent",
    #     ),
    # The provider's own lead count beside ours. They disagree when a
    # webhook was lost, and that disagreement is the only warning this
    # product gets that leads are going missing - so it is offered rather
    # than reconciled away.
    CardSpec(key="leads_reported", group="result", basis="period", unit="count"),
    # --- Delivery ----------------------------------------------------
    CardSpec(
        key="impressions",
        group="delivery",
        basis="period",
        unit="count",
        is_default=True,
    ),
    # On by default: how many people saw it is the first sign that an advert
    # with no result yet is running at all.
    CardSpec(key="reach", group="delivery", basis="day", unit="count", is_default=True),
    # Rising frequency is a creative wearing out, and it shows here before
    # it shows in the cost per lead. Lower is better only in the sense that
    # matters: nobody wants to pay to show one person the same ad nine times.
    CardSpec(
        key="frequency",
        group="delivery",
        basis="day",
        unit="ratio",
        lower_is_better=True,
    ),
    # --- Engagement --------------------------------------------------
    CardSpec(
        key="ctr",
        group="engagement",
        basis="period",
        unit="percent",
        is_default=True,
    ),
    # The honest click-through rate, beside the headline one.
    #
    # ``ctr`` counts every tap on the unit - expanding the caption, opening
    # the page's profile - so an advert that is interesting to look at
    # scores well on it and sends nobody anywhere. This one counts the taps
    # that went where the money was being spent to send them, and a wide
    # gap between the two is the clearest signal a creative has that its
    # promise and its destination do not match.
    CardSpec(
        key="link_ctr",
        group="engagement",
        basis="period",
        unit="percent",
    ),
    CardSpec(key="clicks", group="engagement", basis="period", unit="count"),
    CardSpec(key="link_clicks", group="engagement", basis="period", unit="count"),
    CardSpec(key="unique_clicks", group="engagement", basis="day", unit="count"),
    # --- Video -------------------------------------------------------
    CardSpec(key="video_plays", group="video", basis="period", unit="count"),
    CardSpec(key="video_thruplays", group="video", basis="period", unit="count"),
    CardSpec(key="video_hold", group="video", basis="period", unit="percent"),
)

BY_KEY: Final[dict[str, CardSpec]] = {card.key: card for card in CARDS}

# What an account that has never opened the settings sees.
DEFAULT_KEYS: Final[tuple[CardKey, ...]] = tuple(
    card.key for card in CARDS if card.is_default
)

# The figures every campaign row carries, in every cabinet.
#
# **Fixed, and never read out of the owner's own choice.** Taking the
# first ticked cards that would fit would make one column mean different
# things on two accounts - and the list is a table: campaigns are compared
# by running an eye down a column, which only works when the column is in
# the same place every time. The settings screen is still honoured where
# the space allows it, which is the campaign's own page.
#
# The order is Ads Manager's: what was spent, what it brought, what one of
# those cost - and then whether the advert is reaching anybody at all. The
# last two are what tells a campaign with no result yet that is being shown
# from one that is not running: without them a row of noughts reads the
# same in both cases.
#
# ``cpql`` and ``qualified`` led this list until the quality marking was
# withdrawn, and they are what the row is waiting to get back. While there
# is no way to mark a lead, both of them are a dash and a nought in the
# two most prominent columns of every row on the screen - which reads as
# twenty-five campaigns that produced nothing rather than as a feature
# that is switched off.
#
#     ROW_KEYS: Final[tuple[CardKey, ...]] = ("cpql", "qualified", "spend")
ROW_KEYS: Final[tuple[CardKey, ...]] = (
    "spend",
    "leads",
    "cpl",
    "reach",
    "impressions",
)


def chosen_keys(stored: object) -> tuple[CardKey, ...]:
    """The cards to draw, from whatever the preference row happens to hold.

    Defensive on purpose, and about a value this code wrote itself. A JSON
    column survives a deploy that removed a card, a hand-edit in the admin
    and a row written by an older release, and every one of those arrives
    here as a list containing a string nothing knows about. Dropping the
    stranger is the only behaviour that leaves the screen drawable.

    **An empty choice is a choice.** Somebody who unticks everything gets an
    empty panel, not the defaults back - a settings screen that reinstates
    what was just removed is one nobody trusts. Falling back to the defaults
    happens where there is no preference at all, which is
    :func:`stored_or_default` next door and not here.

    Order is the catalogue's, never the stored list's. What is stored is a
    set of choices; where each one is drawn is this module's business, and
    keeping the two separate is what stops a reordered save from shuffling
    somebody's screen.
    """
    if not isinstance(stored, list):
        return ()
    picked = {item for item in stored if isinstance(item, str)}
    return tuple(card.key for card in CARDS if card.key in picked)


def stored_or_default(stored: object) -> tuple[CardKey, ...]:
    """What to draw for an account that may never have chosen.

    ``None`` means no preference row and the defaults apply. A list - even
    an empty one - is an answer somebody gave, and it is honoured.
    """
    return DEFAULT_KEYS if stored is None else chosen_keys(stored)


def specs_for(keys: tuple[CardKey, ...]) -> tuple[CardSpec, ...]:
    """The catalogue entries behind a choice, in the order given.

    A lookup and not a sort. Order is :func:`chosen_keys`' guarantee and
    every caller here is handed its output, so re-sorting would be a second
    place for the same rule - and the place it would eventually disagree.
    """
    return tuple(BY_KEY[key] for key in keys)


__all__ = [
    "BY_KEY",
    "CARDS",
    "DEFAULT_KEYS",
    "GROUPS",
    "ROW_KEYS",
    "Basis",
    "CardGroup",
    "CardKey",
    "CardSpec",
    "Unit",
    "chosen_keys",
    "specs_for",
    "stored_or_default",
]
