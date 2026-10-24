"""The rungs under a campaign, one line each: groups, adverts, forms, pages.

Kept apart from :mod:`core.chat.context` because each of these is a line in
a list, and the context only decides which lists travel. Same rules as the
rest of the digest: typed fields, values already rendered in the reader's
locale, and nowhere to put a person.

**The words of an advert and the questions of a form are here on purpose.**
They are the business's own advertising, written by the owner for strangers
to read - not anything a lead sent back. A lead's answers never reach this
module; there is no field for them.
"""

from dataclasses import dataclass
from typing import Final

# What each kind of result is called in the context, in the model's own
# language like every other label here. Keyed by ``core.metrics.Outcome``;
# a kind nothing counts has no name, because it has no line.
RESULT_NAMES: Final[dict[str, str]] = {
    "lead": "leads",
    "chat": "conversations",
    "call": "calls",
    "click": "visits to the website",
    "view": "times shown",
    "recall": "people likely to remember it",
    "profile": "visits to the Instagram profile",
    "site_lead": "leads on the website (the provider's count)",
}


@dataclass(frozen=True, slots=True)
class ResultDigest:
    """One kind of result over the window, and what one of them cost.

    **Never added to another kind.** A conversation is not a lead, and an
    account whose chat campaign brought forty of them read "leads 0" when
    only forms were counted - which the assistant then explained as an
    account bringing nothing. Each kind is counted where the provider
    counts it and priced over its own spend.

    ``cost`` is already formatted, and empty where nothing came to divide
    by. For showings it is the price of a thousand, the figure every screen
    prints: one showing costs less than the smallest coin.
    """

    kind: str
    count: int
    cost: str = ""


def result_text(item: ResultDigest) -> str:
    """ "40 conversations, cost each 2 USD" - one kind, said on its own."""
    text = f"{item.count} {RESULT_NAMES.get(item.kind, item.kind)}"
    if item.cost:
        each = "cost per 1000 shown" if item.kind == "view" else "cost each"
        text += f", {each} {item.cost}"
    return text


def results_text(items: tuple[ResultDigest, ...]) -> str:
    """Every kind, one after another, or a plain "nothing counted"."""
    return "; ".join(result_text(item) for item in items) or "nothing counted"


@dataclass(frozen=True, slots=True)
class AdSetDigest:
    """One group of adverts, as much of it as an answer needs.

    The rung under a campaign. A campaign carries a name, a status, what
    was spent and how many enquiries arrived, and every question worth
    asking is one rung below that: which people this is being shown to,
    whether the provider has stopped it, why one group costs three times
    what its neighbour does.

    ``audience`` is who it is shown to in plain words - an age range, the
    places, whether the provider is choosing for itself. Never a targeting
    document: the reader has never seen one and the model does not need to
    quote it to explain a cost.

    ``trouble`` is what the provider says is wrong with this group, in
    whichever words reached the screen. Empty on a group with nothing wrong,
    which is most of them.

    ``cause`` is last night's diagnosis in the card's own words - the name
    and the sentence under it. Found by arithmetic in
    :mod:`core.agent.diagnosis`; the assistant explains it and never picks
    another, which is what keeps the card and the conversation saying one
    thing.
    """

    name: str
    campaign: str
    status: str
    spend: str
    # What it was bought for and how many came, with the price of one -
    # :func:`result_text`. Empty for a kind nothing here counts.
    result: str
    # The Facebook page these adverts run from, by name. The subscription
    # is sold per page and one page's advertising is paid for out of any
    # number of ad accounts, so "whose advertising is this" is answered
    # here and nowhere above: a campaign is not the answer and an ad
    # account is the wrong question.
    page: str = ""
    audience: str = ""
    trouble: str = ""
    cause: str = ""
    # The group's own rate beside the account's, already formatted, from
    # the same diagnosis: "5 USD (account 3 USD)". Empty where it read none.
    shown_cost: str = ""
    click_rate: str = ""
    # How many times one person saw it over the last days of the window.
    frequency: str = ""
    # The one slice of the audience that is dear to reach and takes a real
    # share of the money. Said, never removed - see the diagnosis.
    costly_slice: str = ""
    is_learning: bool = False
    # Not running, by its own switch, its campaign's or its end. Said in
    # English beside the label, which is in the reader's language.
    is_off: bool = False
    # The provider's own advice about this group, its title only.
    advice: str = ""


@dataclass(frozen=True, slots=True)
class AdDigest:
    """One advert: what it cost, what it brought, and what it says.

    ``words`` and ``headline`` are the live advert's own text, trimmed. They
    are what an answer to "why does nobody click" has to be able to read -
    a click rate alone says that people scroll past, never what they
    scrolled past.

    ``ratings`` is the provider's comparison of this advert against the ones
    shown to the same people, in the product's words for each step.
    """

    name: str
    group: str
    status: str
    spend: str
    # The group's result, counted on this advert - see ``AdSetDigest``.
    result: str = ""
    click_rate: str = ""
    # Share of the people shown a video who stayed past three seconds.
    # Empty on an image, which cannot fail to hold anybody.
    hook: str = ""
    ratings: str = ""
    headline: str = ""
    words: str = ""
    form: str = ""
    page: str = ""
    # Not running, by its own switch or its group's - see ``AdSetDigest``.
    is_off: bool = False


@dataclass(frozen=True, slots=True)
class FormDigest:
    """One form a delivering advert collects through, and what it asks."""

    name: str
    questions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PageDigest:
    """One page a delivering advert sends people to, as last night found it."""

    url: str
    state: str
    has_pixel: bool = False


def adset_line(item: AdSetDigest) -> str:
    """One group on one line, with the optional halves left off when empty.

    Appended rather than printed as blanks: a group with no result has no
    cost each, and "cost each -" invites a model to explain a dash. The
    order is fixed so two identical accounts render identically.
    """
    line = f"- {item.name} ({item.campaign}) - {item.status}, spend {item.spend}"
    line += _optional(
        ("result", item.result),
        ("page", item.page),
        # Last night's check, over its own week - not the window the spend
        # and the result above are over. Said on the label, so a rate is
        # never read as the month's.
        ("cost per 1000 shown, last 7 days", item.shown_cost),
        ("clicks per 1000 shown, last 7 days", item.click_rate),
        (
            "each person saw it a day, first half to second half of the week",
            item.frequency,
        ),
        ("dear slice", item.costly_slice),
        ("shown to", item.audience),
    )
    if item.is_off:
        line += ", switched off"
    if item.is_learning:
        line += ", still learning"
    if item.trouble:
        line += f", provider says: {item.trouble}"
    if item.advice:
        line += f", provider suggests: {item.advice}"
    # A cause is about what a running group is doing. One left from a night
    # before it was switched off would be read as a reason to fix it.
    if item.cause and not item.is_off:
        line += f", cause: {item.cause}"
    return line


def ad_line(item: AdDigest) -> str:
    """One advert on one line. Its words last, quoted, so they read as text."""
    line = f"- {item.name} (group {item.group}) - {item.status}, spend {item.spend}"
    if item.is_off:
        line += ", switched off"
    line += _optional(
        ("result", item.result),
        ("clicks per 1000 shown", item.click_rate),
        ("video watched past 3 seconds", item.hook),
        ("provider rates it", item.ratings),
        ("form", item.form),
        ("links to", item.page),
    )
    if item.headline:
        line += f', headline "{item.headline}"'
    if item.words:
        line += f', words "{item.words}"'
    return line


def form_line(item: FormDigest) -> str:
    """A form and its questions, in the order a person meets them."""
    if not item.questions:
        return f"- {item.name}: questions not read yet"
    return f"- {item.name}: {len(item.questions)} questions - " + "; ".join(
        item.questions
    )


def page_line(item: PageDigest) -> str:
    """A page and whether it opened. The pixel matters to a website advert only."""
    pixel = "pixel found" if item.has_pixel else "no pixel found"
    return f"- {item.url} - {item.state}, {pixel}"


def _optional(*pairs: tuple[str, str]) -> str:
    return "".join(f", {label} {value}" for label, value in pairs if value)


__all__ = [
    "RESULT_NAMES",
    "AdDigest",
    "AdSetDigest",
    "FormDigest",
    "PageDigest",
    "ResultDigest",
    "ad_line",
    "adset_line",
    "form_line",
    "page_line",
    "result_text",
    "results_text",
]
