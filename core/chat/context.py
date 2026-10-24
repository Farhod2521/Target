"""What chat is allowed to know about an account, and nothing else.

**A closed set of typed fields, and that is the point.** There is no
key/value bag here and no room for one: every field below is a label or a
measurement, so a lead's name, phone number or email address cannot be put
into the context by accident. Somebody would have to add a field named
after a person and explain why in review - which is the same barrier
``AudienceMemberDTO`` puts in front of plain-text personal data, and for
the same reason. A prompt saying "never mention a lead's phone number" is a
request; a shape with nowhere to put one is a guarantee.

Values arrive already rendered. Money is formatted in the reader's locale
by the Django layer above, because a figure Claude echoes back should look
like the figure on the screen the person is comparing it against.

:meth:`ChatContext.figures` is derived from the rendered text rather than
collected alongside it. That is deliberate: a set assembled separately is a
second source of truth, and the first time the two disagree the gate either
masks a real number or lets an invented one through.

The rungs under a campaign - groups, adverts, forms and pages - are shaped
in :mod:`core.chat.rungs`; this module decides which of them travel.
"""

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
    """The period before the window, and how the window moved against it.

    ``moves`` is worked out in code - see :mod:`core.chat.prior` - so the
    answer quotes a percentage the context supplied rather than one of its
    own, which the gate would remove.
    """

    spend: str
    results: tuple[ResultDigest, ...] = ()
    moves: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TotalsDigest:
    """The account over the window every other figure is measured against.

    No qualified count and no cost per qualified lead. Both rest on the
    owner's quality mark, which is switched off, so both would read as
    nought and an answer would explain the nought - see CLAUDE.md on CPQL.
    """

    window_days: int
    spend: str
    # One entry per kind of result the account's groups were bought for,
    # dearest first - see :class:`~core.chat.rungs.ResultDigest`.
    results: tuple[ResultDigest, ...] = ()
    # What this owner's advertising was paid in a currency the figures
    # above are not in, one entry per currency. Nothing converts money
    # here, so it is in none of them and is said on its own line - both so
    # the reader is not told a smaller figure than the truth, and so the
    # assistant has the words for it when asked.
    other_currency: tuple[str, ...] = ()
    # The same number of days just before the window, for "is it getting
    # worse". ``None`` when there is nothing before it to hold against.
    prior: PriorDigest | None = None


@dataclass(frozen=True, slots=True)
class CampaignDigest:
    name: str
    status: str
    spend: str
    results: tuple[ResultDigest, ...] = ()


@dataclass(frozen=True, slots=True)
class PageTotals:
    """One Facebook page over the window, and the campaigns run from it.

    **The unit the subscription is sold in.** One page's advertising can be
    paid for out of any number of ad accounts, so a digest shaped like an
    ad account describes a fraction of a page and calls it the account.
    Every figure here is the page's across the whole subscription.

    ``name`` is empty for the one entry that is not a page: the groups no
    page could be found for. They are kept rather than dropped, because a
    total that did not add up is a worse answer than an honest "these could
    not be placed" - see :mod:`apps.chat.selectors.page_scope`.

    ``campaigns`` is filled only when the question turned out to be about
    campaigns. The totals above it are two dozen tokens and travel with
    every question; the campaigns under them are not.
    """

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
    """One thing the agent proposed, and what became of it.

    ``AgentRun.dropped`` is deliberately absent. It is the model's own note
    about why a rule was set aside - an explanation, never a decision - and
    no later pass reads it. Handing it to chat would let language output
    start talking over arithmetic.
    """

    what: str
    status: str
    outcome: str
    # The diagnosis the proposal was made under, by name.
    cause: str = ""
    # The figure the verdict was read from, before and after the change,
    # as the record column prints it. Empty until there is a verdict.
    change: str = ""


@dataclass(frozen=True, slots=True)
class OfferDigest:
    """One thing the reader could have done for them, and its key.

    The catalogue an answer is allowed to end with a choice from. Every
    entry is an open proposal the agent has already made and the owner has
    not answered - so the button under an answer is the same button as the
    one on the actions screen, going through the same service, with the
    same rule check and the same rollback behind it.

    ``key`` is short, opaque and made for this one turn. Short because it
    is sent in the context and returned in the answer, and neither is free;
    opaque because a suggestion's real id is a UUID that carries somebody's
    account with it, and a model has no business handling one.

    The model chooses among these and decides nothing else. What the button
    says, what it acts on and what happens when it is pressed are all read
    back out of the card this was built from - see
    :mod:`apps.chat.selectors.choices`.
    """

    key: str
    what: str
    target: str
    why: str


@dataclass(frozen=True, slots=True)
class FocusDigest:
    """One suggestion in full, for a question that arrived from its card.

    The list in :class:`AccountDigest` carries labels only - what kind of
    change, on which rule, and what became of it. That is enough to answer
    "what has the agent been proposing" and nowhere near enough to answer
    "explain this one", which is the question the card's own button asks.
    So the card's whole content travels with that question and with no
    other: the reason the agent wrote, the arithmetic under it, and what it
    said it expected.

    Only on the turn that came from the link. Sending five suggestions in
    full on every question would be paying on every question for something
    most of them do not ask about.
    """

    what: str
    target: str
    status: str
    reason: str
    expectation: str
    # ``(label, value)`` pairs, already formatted by ``apps.agent.figures``
    # - the same formatter the card uses. A different one here would let
    # the explanation cite a figure that is not on the screen beside it.
    figures: tuple[tuple[str, str], ...] = ()
    # What became of it, once it has been carried out and read back.
    #
    # **The reason the button exists.** The record column offers "AI bilan
    # aniqlashtirish" on exactly the rows where a change was made and did
    # not help; without this the assistant is handed the *proposal* alone -
    # what was going to change, why, and what was expected - and can only
    # restate the plan.
    #
    # ``outcome`` is the verdict in the product's own words, or the
    # sentence for the other failure - the provider accepted the write and
    # the object came back unchanged. ``after`` is the days since the
    # change, formatted by the same formatter as ``figures`` above, so the
    # before and after are comparable line by line.
    outcome: str = ""
    after: tuple[tuple[str, str], ...] = ()
    # The figures were read again at approval and had moved, so ``reason``
    # was written on older ones than ``figures`` shows.
    reason_dated: bool = False


@dataclass(frozen=True, slots=True)
class TroubleDigest:
    """One line of the cabinet's waiting list, for a question that came from it.

    The sibling of :class:`FocusDigest` and deliberately not the same shape.
    A proposal has a target, a status and the arithmetic that produced it; a
    trouble has a sentence, the sentence under it, and how much it costs to
    ignore - and squeezing the second into the first would mean a heading
    that says "suggestion" over something that is a broken connection.

    No figures. Every one of these already carries its own words from the
    app that owns it, and none of them is a measurement.
    """

    what: str
    detail: str
    # "urgent", "decision" or "news" - the same three the list orders by.
    # It is here because it changes the answer: a person asking about
    # something that is losing them leads now should be told what to do
    # first, and one asking about a half-built draft should not be hurried.
    level: str
    # What the line names, in the owner's own words for it - the advert,
    # the group, the campaign. The subject's own name rather than the
    # group's below: a line about one advert of four in a group is about
    # that advert, and answering about the group would answer a question
    # nobody asked.
    target: str = ""
    # The advert this line is about, where it is about one at all.
    #
    # The whole reason the waiting list carries objects. Without it a
    # reader pressing "ask about this" is handed the same three sentences
    # they have just failed to understand, and the assistant can only say
    # them again in different words. With the group attached it can answer
    # with this account's own figures instead.
    #
    # ``None`` for the lines that are about the cabinet rather than an
    # advert - a lapsed subscription, an unfinished setup - and for a group
    # the mirror has not caught up with.
    about: AdSetDigest | None = None
    # The line names advertising on a page outside the subscription. The
    # waiting list is the cabinet's current ad account, and that account
    # can carry a page nobody pays to have watched here - so the line can be
    # on the screen while nothing about it may reach the model. Its title,
    # sentence and object are kept for the screen and never rendered.
    outside: bool = False


@dataclass(frozen=True, slots=True)
class AccountDigest:
    """The account, as much of it as this question needed.

    ``omitted`` names the sections that were left out because the question
    was not about them, and it is the half of that decision that must not
    be forgotten. A model handed no campaigns and told nothing will answer
    "you have no adverts running", which is a confident, expensive lie -
    and one this product would only find out about from a customer. Named,
    the same absence becomes "that is on the Reklama screen".
    """

    business: BusinessDigest
    totals: TotalsDigest
    maturity: str
    # The subscription's pages, each with its own window, and the campaigns
    # run from them where the question asked for campaigns. Always sent:
    # what a page is called and what it spent is the shape of the whole
    # account, and an assistant that had to look it up would answer "which
    # page?" to somebody who has one.
    #
    # There is no flat list of campaigns beside this and there must not be.
    # A campaign named twice - once on its page and once in a list of its
    # own - is how an answer ends up adding one page's spend to another's.
    by_page: tuple[PageTotals, ...] = ()
    # The rung under them, sent only when the question turned out to be
    # about a group, about something being broken, or about why. A fault
    # and a cause both sit here - a provider stops a group and the campaign
    # above it goes on looking healthy - so an answer built from campaigns
    # alone could describe a working account while one of its groups was
    # switched off.
    adsets: tuple[AdSetDigest, ...] = ()
    # One rung lower again: each advert with its own words.
    ads: tuple[AdDigest, ...] = ()
    # What a click lands on - the forms and the pages of delivering adverts.
    # One section on the route, two lists here, because the two are
    # different things to read and the prompt names them apart.
    forms: tuple[FormDigest, ...] = ()
    pages: tuple[PageDigest, ...] = ()
    audiences: tuple[AudienceDigest, ...] = ()
    suggestions: tuple[SuggestionDigest, ...] = ()
    omitted: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ChatContext:
    """Everything the model is told about this account. Often nothing.

    ``account`` is ``None`` for a visitor and for a signed-in account with
    no live subscription. That is not a guess about the question - it is a
    fact already in the database, and asking the model to classify what it
    was allowed to see would put the boundary on the wrong side of the wire.
    """

    account: AccountDigest | None = None
    # Figures the person typed into the conversation themselves. Quoting
    # somebody's own number back at them is not a claim about their account,
    # so the gate lets these through.
    quoted: frozenset[str] = field(default_factory=frozenset)
    # The one suggestion this question is about, when it arrived from that
    # suggestion's card. ``None`` for every other question, including every
    # question from a visitor - a proposal belongs to an account.
    focus: FocusDigest | None = None
    # The one item from the cabinet's waiting list this question is about,
    # when it arrived from that item's own "ask about this". ``None``
    # otherwise, and never both at once - a reader arrives from one card.
    trouble: TroubleDigest | None = None
    # What the answer may end by offering. Empty for a visitor, for an
    # account with nothing open, and for a question that turned out not to
    # be about anything actionable - a greeting pays for none of this.
    offers: tuple[OfferDigest, ...] = ()

    def render(self) -> str:
        """The context as the model sees it. English labels, local figures.

        Labels in English for the same reason the prompts are: they are
        instructions to a model, not text for a person, and a label that
        changed with the reader's language would make two accounts'
        transcripts incomparable.
        """
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
        """What this question is a reply to, in the shape the thread stores.

        Empty for a question that replies to nothing, which is most of
        them. Built here rather than beside the screen so that the card
        drawn above the box and the card drawn above the question
        afterwards cannot be assembled from two different readings of one
        line - see :func:`as_quote`.
        """
        if self.trouble is None or self.trouble.outside:
            return {}
        return as_quote(
            title=self.trouble.what,
            body=self.trouble.detail,
            target=self.trouble.target,
        )

    @staticmethod
    def _offer_lines(offers: tuple[OfferDigest, ...]) -> list[str]:
        """The closed list of actions, and the one instruction about it.

        Last in the context so it is the nearest thing to the answer, and
        headed with what it is for. What to *do* with it is in the prompt,
        said once, rather than repeated into every context.
        """
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
        """The item the person clicked through from, and what it is about.

        The sentence is written by the app that owns the trouble and is the
        same sentence on the screen the reader just left - so an answer that
        restates it cannot restate it differently.

        **The group under it is the whole point of the button.** Three
        sentences alone would mean a reader who did not understand a line
        gets it back in different words. With the group attached the answer
        can be about this account: what it spent, what it brought in, who
        it is being shown to, and why the diagnosis thinks it is failing.
        """
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
        """The suggestion the person clicked through from, in full.

        Last in the context and under a heading that says what it is, so
        the model can tell the one proposal being asked about from the
        list of recent ones above it. Two sections carrying the same
        suggestion is not a contradiction - it is the same fact at two
        depths, and the deeper one is the answer.
        """
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
            # Spelled out rather than left to be inferred from the code on
            # the spend line: the figures above are one currency's, and a
            # reader that added this to them would be doing the one piece
            # of arithmetic nothing here can do.
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
            # One line, and it is the cheapest line here: it buys back the
            # whole class of answers that mistake "not sent" for "not
            # there". The names are the headings above, so the model is
            # told which of its own headings are missing - and *what to do
            # about it* is in the prompt, said once, rather than repeated
            # into every context at forty tokens a question.
            lines += ["", f"## Not included: {', '.join(account.omitted)}"]
        return lines


# What the model is told about a line of the waiting list that names
# advertising on a page outside the subscription. The same sentence the
# look-ups give for such an object, so the prompt's one rule about them -
# say it is not covered, and stop - answers both.
OUTSIDE_ITEM: str = (
    "Not in this subscription: this line is about advertising on a Facebook "
    "page that is not switched on in the subscription, so none of its names, "
    "figures or settings are available here."
)

# What the entry that is not a page is called. One phrase, in the model's
# own language like every other label here, and it says what it is rather
# than inventing a name: these are groups the mirror cannot yet place, not
# a page called "other".
UNPLACED: str = "adverts no page could be found for"


def _page_lines(pages: tuple[PageTotals, ...]) -> list[str]:
    """Each page, with its campaigns indented under it where they travelled.

    Indented rather than flattened with the page repeated on every line: a
    reader of this context has to be able to see that two campaigns belong
    to one page, and a campaign named twice is how an assistant ends up
    adding one page's spend to another's.
    """
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
    """One line of the waiting list, as a question quotes it.

    Three strings and a single definition of their names. The card above
    the box, the card above the sent question and the row stored in the
    thread are the same three keys, and a second spelling of them anywhere
    would show a reader one thing before they pressed send and another
    afterwards.

    Plain strings rather than a dataclass because this is written into a
    JSON column and read back out of one - a shape that had to be
    reconstructed on every thread read would be a shape with a version
    problem the first time a key is added.
    """
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
