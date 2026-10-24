"""The rule the provider could never write.

Every other cost rule here asks a question Meta can also answer: what was
spent, how many forms were filled in, what each one cost. This one asks
the question only the advertiser can - **were the people any good** - and
it is the whole reason this product exists beside the platform it buys
from. An ad set the provider reports as working, delivering leads at a
respectable price, none of which the owner has marked as worth having, is
invisible from every screen Meta has and is the most expensive thing an
account can be doing.

**No threshold is written down, and none could be.** How many leads must
arrive before "none of them were any good" means something depends on how
good this owner's leads usually are: an account where two in five convert
has said something after five, and one where one in twenty does has said
nothing after fifteen. So the bar is derived from the account's own
quality share, the same shape ``core.metrics.segment_compare`` uses for a
segment that had its chance - and the same thing happens at the edges:
an account that has never marked a lead has a share of nought, which
switches the rule off rather than letting it read an owner's silence as a
verdict about a campaign.
"""

from adskit import ExternalRef

from core.agent.contracts import Finding, Policy
from core.agent.facts import AccountFacts, AdSetFacts, judgeable

JUNK = "junk"

# How many qualified leads the account's own rate says should have turned
# up before nought of them is evidence rather than luck.
#
# Three, and the arithmetic behind it: for a count with an expectation of
# three, seeing none happens about five times in a hundred by chance. Two
# would be one in seven, which is a coin this rule would lose too often -
# and losing it means proposing that somebody stop a campaign that was
# doing nothing wrong.
MIN_EXPECTED_QUALIFIED = 3


def junk(*, account: AccountFacts, policy: Policy) -> list[Finding]:
    """It brings people in, and the owner wants none of them - stop it.

    Not ``wasting``, which is about an ad set nobody ever filled a form
    from. This one has forms, and a provider dashboard showing a perfectly
    healthy cost per lead. What it does not have is a single lead the
    owner marked as worth having, on an account where they mark them
    elsewhere - which is the definition of paying for the wrong audience.

    Stopping rather than narrowing, and the difference from
    ``narrow_audience`` next door is what the evidence supports. There, a
    named slice of the audience is dead and the rest converts; here every
    lead it brought was rejected, so there is no live slice to keep - and
    a targeting change would be a guess about which part to blame.
    """
    share = account.lead_totals.quality_share
    if share <= 0:
        # Nobody here has ever marked a lead as good. That is a fact about
        # the owner's habits, not about any campaign, and no proposal can
        # be built on it - least of all one that stops something.
        return []

    found: list[Finding] = []
    for item in account.adsets:
        if not judgeable(item, policy) or item.totals.qualified > 0:
            continue
        expected = item.totals.leads * share / 100
        if expected < MIN_EXPECTED_QUALIFIED:
            continue

        found.append(
            Finding(
                kind="pause",
                rule=JUNK,
                ref=_ref(account, item),
                weight=item.totals.spend_minor,
                evidence={
                    "days": item.days_with_spend,
                    "spend_minor": item.totals.spend_minor,
                    "leads": item.totals.leads,
                    # Nought, always, or this rule would not have fired -
                    # on the card anyway, because it is the line the whole
                    # proposal rests on. The same reason ``wasting`` shows
                    # a lead count it already implies.
                    "qualified": item.totals.qualified,
                    "account_quality_share": share,
                    "expected_qualified": int(expected),
                    "currency": account.currency,
                },
            )
        )

    return found


def _ref(account: AccountFacts, item: AdSetFacts) -> ExternalRef:
    return ExternalRef(provider=account.provider, level="adset", id=item.external_id)


__all__ = ["JUNK", "MIN_EXPECTED_QUALIFIED", "junk"]
