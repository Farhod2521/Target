"""Who the business is and what its account did, as the review reads it.

The half of the review's system prompt that is one account's - after the
rules, which are the same for every account the night reaches. See
:mod:`apps.agent.services.review` for why the two are sent apart.
"""

from app.common.money import format_minor
from app.modules.agent.constants import RESULT_WORDS
from app.modules.businesses.models import Business
from app.modules.businesses.selectors import category_label
from core.agent import AccountFacts
from core.agent.benchmark import benchmarks


def account_block(*, account: AccountFacts, business: Business, language: str) -> str:
    """Who the business is and what its account did. Everything it may know.

    Assembled explicitly rather than by handing over rows. A prompt that
    can reach an object can reach a column nobody meant to send, and what
    goes to a third party is a decision rather than a side effect - which
    is why no lead, no phone number and no ad set id appear below.

    No qualified count and no cost per qualified lead: the owner's quality
    mark they rest on is switched off, and a nought here is a nought the
    sentence would explain - see CLAUDE.md on CPQL.
    """
    trade = category_label(business)
    return "\n".join(
        [
            f"Answer in: {language}",
            "",
            "## The business",
            "",
            f"- Nomi: {business.name}",
            f"- Sohasi: {trade}",
            f"- Nima sotadi: {business.offer_text or trade}",
            f"- Valyuta: {account.currency}",
            "",
            f"## The account over the last {account.window_days} days",
            "",
            f"- Sarflandi: {_money(account.totals.spend_minor, account.currency)}",
            *_results(account),
            *_usual(account),
        ]
    )


def _usual(account: AccountFacts) -> list[str]:
    """What this pair usually does: the median day of its last fortnight.

    The reference every figure in the shortlist is read against when the
    group has nothing of its kind beside it - see ``core.agent.usual``.
    """
    lines: list[str] = []
    for family, usual in account.usual.items():
        words = RESULT_WORDS.get(family)
        if words is None or usual.cost_minor is None:
            continue
        lines.append(
            f"- {words[1]}, 14 kunlik odatiy (median): {_money(usual.cost_minor, account.currency)}"
        )
    if not lines:
        return []
    return ["", "## What this account usually does", "", *lines]


def _results(account: AccountFacts) -> list[str]:
    """One pair of lines per kind of result the account's groups were bought for.

    **Never added together.** A conversation is not a lead, and an account
    running a chat campaign beside a form reads "Murojaat: 0" if only the
    form is counted, or a lead price with the chat money in it if the spend
    is divided by the leads alone. Each kind is counted and priced over its
    own groups - the same benchmark the card prints as "odatda" and the
    rules measure against - so the sentence quotes the figure on the screen
    underneath it. Dearest kind first: it is the one most sentences are
    about.

    A kind nothing here counts - a purchase on somebody else's website -
    has no line: it has no count to give and no price to quote.
    """
    lines: list[str] = []
    found = sorted(
        benchmarks(account.adsets).items(), key=lambda pair: -pair[1].funnel.spend_minor
    )
    for family, bench in found:
        words = RESULT_WORDS.get(family)
        if words is None or bench.funnel.spend_minor <= 0:
            continue
        lines += [
            f"- {words[0]}: {bench.results}",
            f"- {words[1]}: {_money(bench.cost_minor, account.currency)}",
        ]
    return lines


def _money(amount_minor: int | None, currency: str) -> str:
    """A figure with its currency, or a dash where there is no answer."""
    if amount_minor is None:
        return "—"
    return format_minor(amount_minor=amount_minor, currency=currency)


__all__ = ["account_block"]
