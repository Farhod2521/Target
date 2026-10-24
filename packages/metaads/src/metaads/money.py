"""How Meta counts the smallest unit of a currency.

Every budget this package sends and every floor it reads is an integer
count of the ad account currency's smallest unit - ``daily_budget``,
``min_daily_budget``, ``spend_cap``. What an integer *means* is decided by
Meta's own currency table, and that table is not ISO 4217. Meta publishes
an ``offset`` per currency and it disagrees with the standard for a handful
of them, counting in whole units where ISO counts hundredths.

The consequence of getting one wrong is not a rounding error. A currency
Meta counts in whole units, converted as though it had hundredths, is a
daily budget **a hundred times** the one that was typed - and Meta accepts
it, because the number is legal. It is only visible afterwards, in the
spend.

So the table below holds what has been *read from Meta*, and nothing else.
An unlisted currency falls through to ISO 4217, which is right for most of
them and is the assumption the whole codebase already carried before this
module existed. Adding a guess here would be writing the hundredfold error
down on purpose.
"""

from typing import Final

from adskit.money import MoneyRules

# Currencies where Meta's offset differs from ISO 4217, as digits after the
# separator. Empty, and that is a statement rather than an omission: the
# check below has produced nothing to write down.
#
# **What has been checked.** Both ad accounts on the production connection
# are denominated in **USD**, and both answer ``min_daily_budget: 100``
# against an Ads Manager floor of ``$1.00``. So Meta counts that currency
# in hundredths, exactly as ISO 4217 does, and the fall-through below is
# right for it.
#
# That is a partial result and is worth naming as partial. It confirms the
# *mechanism* - Meta's offsets and the standard's agree where they have
# been compared - and it says nothing at all about **UZS**, because no
# so'm account has been connected. The one currency this deployment meets
# daily is therefore unverified, and the table stays empty rather than
# gaining a row somebody would read as confirmation.
#
# **How an entry gets added.** Read the account on the staff console -
# ``act_<id>?fields=currency,min_daily_budget`` - and compare the floor
# against what Ads Manager shows for the same account. A floor of ``100``
# beside a UI reading "1.00" is two decimals; a floor of ``100`` beside a
# UI reading "100" is none. One line here, one line in the test beside it,
# and the whole codebase follows.
#
# The currencies to check first are the ones ISO gives two decimals and
# Meta is reported to give none. UZS is the one this deployment meets
# daily and is deliberately **not** listed: ISO says two (tiyin), that is
# what the product uses, and no so'm account has been read to say
# otherwise. See the test that pins it.
META_CURRENCY_PLACES: Final[dict[str, int]] = {}

# What the registry hands to anything that has to turn a typed amount into
# a number Meta will read, **and what the adapter reads every figure back
# with.** One object, built once, provider-named.
#
# One table for both halves, which is the only way an override can be
# correct: a row added above moves the budgets and the insight figures at
# once. Reading one through this and the other through
# ``adskit.money.to_minor`` - the standard's own table - would agree only
# while the map above stays empty, and disagree by a factor of a hundred
# the day it gains a currency, in opposite directions on the same screen:
# a budget read one way and the spend against it read the other.
META_MONEY: Final = MoneyRules(overrides=META_CURRENCY_PLACES)

__all__ = ["META_CURRENCY_PLACES", "META_MONEY"]
