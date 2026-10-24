"""How far along one account is, read from what the provider has learned.

The first question every strategy asks, and the one place it is answered.
"Wide audience or broad delivery", "keep gathering or start scaling" - all
of it turns on whether the provider has enough conversion signal on this
account to optimise with, and that is a fact about history rather than
about any single campaign.

**The thresholds are not invented here - and where one had to be, it says
so.** The provider does not publish its own number: the v26.0 learning
stage reference exposes ``dynamic_lp_conversions_threshold`` and
``dynamic_lp_days_threshold`` as *fields*, meaning the bar moves per ad
set and is never written down. What it does publish is its **verdict** -
``learning_stage_info.status`` becomes ``SUCCESS`` exactly when an ad set
cleared that bar - so the verdict is read instead of the bar being
guessed. The two numeric defaults below exist for accounts where no
verdict is available, and each is marked for what it is.

Age and total spend are deliberately not signals. An old account with no
conversions has taught the provider nothing, so age flatters it; and an
absolute amount of money would mean a different maturity per currency,
which is the hardcode ban wearing a different hat.

No Django, no clock: history arrives as a value, like everything in
``core``.
"""

from dataclasses import dataclass
from typing import Final, Literal

# Where one account stands, in the product's own words.
#
#   new      - the provider has essentially nothing to optimise on. The
#              next campaign should be wide: one or two interests, nothing
#              clever, because narrowing multiplies guesses
#   growing  - signal is arriving but has not stabilised. Keep the shape,
#              feed it, test creatives; do not change the foundations
#   proven   - the provider has demonstrated it can find these customers.
#              Broad and automatic delivery become the better bargain, and
#              scaling is a question worth asking
AccountMaturity = Literal["new", "growing", "proven"]

# How much history maturity is judged on. Ninety days: the widest window
# this product ever tells a complete story about - the lead provider keeps
# a lead that long, the metrics backfill reaches that far on a fresh
# account, and the screen's own longest period is the same figure. A
# season, where the reactive rules read a week - the two windows answer
# different questions and are deliberately not one setting.
SIGNAL_WINDOW_DAYS: Final = 90

# The provider's own word for an ad set that cleared its learning bar,
# from the v26.0 learning-stage reference (LEARNING / SUCCESS / FAIL).
# Provider vocabulary in ``core``, the same documented asymmetry as
# ``core.metrics.LEAD_GOALS`` and ``core.targeting.modes``: the word
# arrives raw on the mirror, and this is the one place that reads it.
LEARNING_SUCCESS: Final = "SUCCESS"


def has_exited_learning(learning_status: str) -> bool:
    """Whether the provider itself says this ad set finished learning.

    An allowlist of one, pointed the safe way like ``counts_leads``:
    ``LEARNING``, ``FAIL``, an empty mirror and a value nobody has met all
    answer *no*. The cost of a wrong "no" is a gentler strategy; a wrong
    "yes" would scale an account on signal it does not have.
    """
    return learning_status.strip().upper() == LEARNING_SUCCESS


@dataclass(frozen=True, slots=True)
class SignalHistory:
    """What the provider has had to learn from, over a long window.

    A different window from :class:`core.agent.AccountFacts` on purpose -
    the reactive rules judge a week because last week is what a budget
    decision is about, and maturity judges a season because "does the
    provider know these customers" is not answered by seven days. The same
    split ``lead_totals`` makes: two questions, two figures.

    ``reported_results`` is the provider's own count on the ad sets that
    can produce a lead, not this product's webhook rows. Maturity asks
    what *the provider* saw, and the provider optimises on its own count.
    """

    window_days: int
    # The provider's own lead count over the window, summed over ad sets
    # whose optimisation goal can produce one - the logical twin of
    # ``AccountFacts.lead_totals`` and bounded the same way.
    reported_results: int = 0
    # How many of the window's days anything at all was spent. Zero means
    # a dormant account, whatever its past.
    days_with_spend: int = 0
    # Whether any ad set currently carries the provider's SUCCESS verdict.
    has_proven_adset: bool = False


@dataclass(frozen=True, slots=True)
class MaturityThresholds:
    """The two numbers used when the provider's verdict is not available.

    Defaults rather than settings, the ``Policy`` bargain: one place holds
    what nobody was asked about, and a caller who wants different numbers
    passes different numbers. Neither is in the database, because neither
    is a preference.
    """

    # Weekly results at or above which an account counts as proven even
    # without a SUCCESS verdict in sight. Anchored to the provider's own
    # published guidance - the Help Center's "about 50 optimization events
    # in seven days" - but that figure is per ad set and approximate by
    # its own wording, and applying it account-wide is this product's
    # reading. Approximate, and adjustable for exactly that reason.
    proven_weekly_results: int = 50
    # Below this many results over the whole window, the account is new.
    # No document names this number; it is the smallest count at which
    # "signal is arriving" is a sentence worth saying. Heuristic.
    min_results: int = 10


# The defaults, made once. Frozen, so one shared instance is a constant
# rather than a risk - and a caller who wants different numbers passes a
# different instance.
DEFAULT_THRESHOLDS: Final = MaturityThresholds()


def maturity(
    *,
    history: SignalHistory,
    thresholds: MaturityThresholds = DEFAULT_THRESHOLDS,
) -> AccountMaturity:
    """Where this account stands, safest reading first.

    The provider's verdict wins - but only on an account that is actually
    spending. A SUCCESS earned last year on an account that has been
    dormant since is a fact about the past: the verdict belongs to an ad
    set, and an account with no spend in the window falls through to the
    arithmetic, where dormancy reads as what it is.

    Everything unknown lands on ``new``. An empty history, a window of
    nought days, a mirror that has not synced - all of them get the
    gentlest strategy rather than the boldest, the ``counts_leads``
    direction: the two mistakes are not the same size.
    """
    if history.window_days <= 0 or history.days_with_spend <= 0:
        return "new"
    if history.has_proven_adset:
        return "proven"

    weekly = history.reported_results * 7 / history.window_days
    if weekly >= thresholds.proven_weekly_results:
        return "proven"
    if history.reported_results < thresholds.min_results:
        return "new"
    return "growing"


__all__ = [
    "DEFAULT_THRESHOLDS",
    "LEARNING_SUCCESS",
    "SIGNAL_WINDOW_DAYS",
    "AccountMaturity",
    "MaturityThresholds",
    "SignalHistory",
    "has_exited_learning",
    "maturity",
]
