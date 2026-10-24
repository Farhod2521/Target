"""What chat is allowed to know about an account, and nothing else."""

from dataclasses import dataclass, field

from core.chat.numbers import figures_in
from core.chat.rungs import (
    AdDigest,
    AdSetDigest,
    FormDigest,
    PageDigest,
    ResultDigest,
    ad_line,
    adset_line,
    form_line,
    page_line,
    results_text,
)


@dataclass(frozen=True, slots=True)
class BusinessDigest:
    """Who is asking, in the words they used to describe themselves."""

    name: str
    category: str
    offer: str
    currency: str


@dataclass(frozen=True, slots=True)
class PriorDigest:
    """The period before the window, and how the window moved against it."""

    spend: str
    results: tuple[ResultDigest, ...] = ()
    moves: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TotalsDigest:
    """The account over the window every other figure is measured against."""

    window_days: int
    spend: str
    results: tuple[ResultDigest, ...] = ()
    other_currency: tuple[str, ...] = ()
    prior: PriorDigest | None = None


@dataclass(frozen=True, slots=True)
class CampaignDigest:
    name: str
    status: str
    spend: str
    results: tuple[ResultDigest, ...] = ()


@dataclass(frozen=True, slots=True)
class PageTotals:
    """One Facebook page over the window, and the campaigns run from it."""

    name: str
    spend: str
    results: tuple[ResultDigest, ...] = ()
    campaigns: tuple[CampaignDigest, ...] = ()


@dataclass(frozen=True, slots=True)
class AudienceDigest:
    name: str
    kind: str
    size: str
    is_ready: bool


@dataclass(frozen=True, slots=True)
class SuggestionDigest:
    """One thing the agent proposed, and what became of it."""

    what: str
    status: str
    outcome: str
    cause: str = ""
    change: str = ""


@dataclass(frozen=True, slots=True)
class OfferDigest:
    """One thing the reader could have done for them, and its key."""

    key: str
    what: str
    target: str
    why: str


@dataclass(frozen=True, slots=True)
class FocusDigest:
    """One suggestion in full, for a question that arrived from its card."""

    what: str
    target: str
    status: str
    reason: str
    expectation: str
    figures: tuple[tuple[str, str], ...] = ()
    outcome: str = ""
    after: tuple[tuple[str, str], ...] = ()
    reason_dated: bool = False


@dataclass(frozen=True, slots=True)
class TroubleDigest:
    """One line of the cabinet's waiting list, for a question that came from it."""

    what: str
    detail: str
    level: str
    target: str = ""
    about: AdSetDigest | None = None
    outside: bool = False


@dataclass(frozen=True, slots=True)
class AccountDigest:
    """The account, as much of it as this question needed."""

    business: BusinessDigest
    totals: TotalsDigest
    maturity: str
    by_page: tuple[PageTotals, ...] = ()
    adsets: tuple[AdSetDigest, ...] = ()
    ads: tuple[AdDigest, ...] = ()
    forms: tuple[FormDigest, ...] = ()
    pages: tuple[PageDigest, ...] = ()
    audiences: tuple[AudienceDigest, ...] = ()
    suggestions: tuple[SuggestionDigest, ...] = ()
    omitted: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ChatContext:
    """Everything the model is told about this account. Often nothing."""

    account: AccountDigest | None = None
    quoted: frozenset[str] = field(default_factory=frozenset)
    focus: FocusDigest | None = None
    trouble: TroubleDigest | None = None
    offers: tuple[OfferDigest, ...] = ()

    def render(self) -> str:
        """The context as the model sees it. English labels, local figures."""
        if self.account is None:
            return ""
        lines = self._lines(self.account)
        if self.focus is not None:
            lines += self._focus_lines(self.focus)
        if self.trouble is not None:
            lines += self._trouble_lines(self.trouble)
        if self.offers:
            lines += self._offer_lines(self.offers)
        return "\n".join(lines)

    def figures(self) -> frozenset[str]:
        """Every figure the model was handed, canonical. The gate's allow-set."""
        return figures_in(self.render())

    def quote(self) -> dict[str, str]:
        """What this question is a reply to, in the shape the thread stores."""
        if self.trouble is None or self.trouble.outside:
            return {}
        return as_quote(
            title=self.trouble.what,
            body=self.trouble.detail,
            target=self.trouble.target,
        )

    @staticmethod
    def _offer_lines(offers: tuple[OfferDigest, ...]) -> list[str]:
        """The closed list of actions, and the one instruction about it."""
        return [
            "",
            "## Actions you may offer",
            *(
                f"- {item.key}: {item.what} - {item.target} ({item.why})"
                for item in offers
            ),
        ]

    @staticmethod
    def _trouble_lines(trouble: TroubleDigest) -> list[str]:
        """The item the person clicked through from, and what it is about."""
        if trouble.outside:
            return ["", "## The item this question is about", f"- {OUTSIDE_ITEM}"]
        lines = [
            "",
            "## The item this question is about",
            f"- What: {trouble.what}",
            f"- Detail: {trouble.detail}",
            f"- How urgent: {trouble.level}",
        ]
        if trouble.target:
            lines.append(f"- It names: {trouble.target}")
        about = trouble.about
        if about is None:
            return lines
        lines += [
            "",
            "### The ad group it is about",
            f"- Group: {about.name}",
            f"- Campaign: {about.campaign}",
            f"- Delivery: {about.status}",
            f"- Spent: {about.spend}",
            f"- Result: {about.result or 'not counted here'}",
        ]
        if about.audience:
            lines.append(f"- Shown to: {about.audience}")
        if about.trouble:
            lines.append(f"- Provider says: {about.trouble}")
        if about.cause:
            lines.append(f"- Cause: {about.cause}")
        return lines

    @staticmethod
    def _focus_lines(focus: FocusDigest) -> list[str]:
        """The suggestion the person clicked through from, in full."""
        lines = [
            "",
            "## The suggestion this question is about",
            f"- What: {focus.what}",
            f"- Object: {focus.target}",
            f"- Status: {focus.status}",
        ]
        if focus.reason:
            lines.append(f"- Why the agent proposed it: {focus.reason}")
        if focus.reason_dated:
            lines.append(
                "- Note: that reason was written on the figures of the night it "
                "was proposed; the figures below were read again when it was "
                "approved, and they moved"
            )
        if focus.expectation:
            lines.append(f"- What it expects: {focus.expectation}")
        lines += [f"- {label}: {value}" for label, value in focus.figures]
        if focus.outcome:
            lines.append(f"- What actually happened: {focus.outcome}")
        if focus.after:
            lines += ["", "### Since the change"]
            lines += [f"- {label}: {value}" for label, value in focus.after]
        return lines

    @staticmethod
    def _lines(account: AccountDigest) -> list[str]:
        business, totals = account.business, account.totals
        lines = [
            "## Business",
            f"- Name: {business.name}",
            f"- Category: {business.category}",
            f"- Sells: {business.offer}",
            f"- Currency: {business.currency}",
            f"- Account maturity: {account.maturity}",
            "",
            f"## Last {totals.window_days} days",
            f"- Spend: {totals.spend}",
            f"- Results: {results_text(totals.results)}",
        ]
        if totals.other_currency:
            lines.append(
                "- Also paid in another currency, NOT included above and "
                f"never to be added to it: {' + '.join(totals.other_currency)}"
            )
        if totals.prior is not None:
            lines += [
                "",
                f"## The {totals.window_days} days before that",
                f"- Spend: {totals.prior.spend}",
                f"- Results: {results_text(totals.prior.results)}",
                "- Change against them: "
                + ("; ".join(totals.prior.moves) or "nothing moved"),
            ]
        if account.by_page:
            lines += ["", "## Pages in the subscription", *_page_lines(account.by_page)]
        if account.adsets:
            lines += ["", "## Ad groups", *map(adset_line, account.adsets)]
        if account.ads:
            lines += ["", "## Adverts", *map(ad_line, account.ads)]
        if account.forms:
            lines += ["", "## Lead forms", *map(form_line, account.forms)]
        if account.pages:
            lines += ["", "## Website pages", *map(page_line, account.pages)]
        if account.audiences:
            lines += ["", "## Audiences"]
            lines += [
                f"- {item.name} - {item.kind}, size {item.size}, "
                f"{'ready' if item.is_ready else 'not ready'}"
                for item in account.audiences
            ]
        if account.suggestions:
            lines += ["", "## What the agent proposed recently"]
            lines += [_suggestion_line(item) for item in account.suggestions]
        if account.omitted:
            lines += ["", f"## Not included: {', '.join(account.omitted)}"]
        return lines


OUTSIDE_ITEM: str = (
    "Not in this subscription: this line is about advertising on a Facebook "
    "page that is not switched on in the subscription, so none of its names, "
    "figures or settings are available here."
)

UNPLACED: str = "adverts no page could be found for"


def _page_lines(pages: tuple[PageTotals, ...]) -> list[str]:
    """Each page, with its campaigns indented under it where they travelled."""
    lines: list[str] = []
    for page in pages:
        lines.append(
            f"- {page.name or UNPLACED} - spend {page.spend}, "
            f"results: {results_text(page.results)}"
        )
        lines += [
            f"  - {item.name} - {item.status}, spend {item.spend}, "
            f"results: {results_text(item.results)}"
            for item in page.campaigns
        ]
    return lines


def as_quote(*, title: str, body: str, target: str = "") -> dict[str, str]:
    """One line of the waiting list, as a question quotes it."""
    return {"title": title, "body": body, "target": target}


def _suggestion_line(item: SuggestionDigest) -> str:
    """A proposal, its cause, and - once there is one - its verdict and figure."""
    line = f"- {item.what} - {item.status}"
    if item.cause:
        line += f", cause: {item.cause}"
    if item.outcome:
        line += f", outcome: {item.outcome}"
    if item.change:
        line += f" ({item.change})"
    return line
