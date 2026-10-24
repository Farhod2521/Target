"""The rungs under a campaign, one line each: groups, adverts, forms, pages."""

from dataclasses import dataclass
from typing import Final

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
    """One kind of result over the window, and what one of them cost."""

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
    """One group of adverts, as much of it as an answer needs."""

    name: str
    campaign: str
    status: str
    spend: str
    result: str
    page: str = ""
    audience: str = ""
    trouble: str = ""
    cause: str = ""
    shown_cost: str = ""
    click_rate: str = ""
    frequency: str = ""
    costly_slice: str = ""
    is_learning: bool = False
    is_off: bool = False
    advice: str = ""


@dataclass(frozen=True, slots=True)
class AdDigest:
    """One advert: what it cost, what it brought, and what it says."""

    name: str
    group: str
    status: str
    spend: str
    result: str = ""
    click_rate: str = ""
    hook: str = ""
    ratings: str = ""
    headline: str = ""
    words: str = ""
    form: str = ""
    page: str = ""
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
    """One group on one line, with the optional halves left off when empty."""
    line = f"- {item.name} ({item.campaign}) - {item.status}, spend {item.spend}"
    line += _optional(
        ("result", item.result),
        ("page", item.page),
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
