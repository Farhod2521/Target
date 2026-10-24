"""What every look-up shares: the subscription's edges, the window, the words."""

from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.money import format_minor
from app.modules.accounts.models import User
from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.chat.selectors.result_counts import figure_sums
from app.modules.chat.selectors.scope import (
    in_subscription,
    subscribed_accounts,
    subscribed_pages,
)
from app.modules.leads.models import LeadForm


def window(db: Session, *, owner: User, days: int) -> tuple[date, date]:
    """The last ``days`` days on the cabinet's own calendar, today included."""
    from app.modules.metrics.selectors.dashboard import cabinet_today

    today = cabinet_today(db, owner=owner)
    return today - timedelta(days=days - 1), today


def money(amount_minor: int, currency: str) -> str:
    """An amount with its currency, and nought said as nought."""
    return format_minor(amount_minor=amount_minor, currency=currency) or "0"


def page_currency(db: Session, *, owner: User) -> str:
    """What figures about the page this conversation is on are written in."""
    from app.modules.metrics.selectors.scope import page_campaigns

    accounts = subscribed_accounts(db, owner=owner)
    account = accounts[0] if accounts else None
    return page_campaigns(db, owner=owner).currency or (
        account.currency if account is not None else ""
    )


def outside(kind: str, external_id: str) -> str:
    """What a look-up answers about something the subscription does not cover."""
    return (
        f"Not in this subscription: {kind} {external_id}. This product is paid "
        "for per Facebook page, and this one belongs to a page that is not "
        "switched on in the subscription - so none of its figures, names or "
        "settings are available here."
    )


def elsewhere(kind: str, external_id: str) -> str:
    """What a look-up answers about something another page of the subscription runs."""
    return (
        f"On another page of this subscription: {kind} {external_id}. This "
        "conversation is about the page the owner is on; the owner switches "
        "to that page in the cabinet to ask about it, so none of its figures, "
        "names or settings are given here."
    )


def unbuilt(kind: str, external_id: str) -> str:
    """What a look-up answers about Ads Manager's advertising on this plan."""
    return (
        f"Built in Ads Manager, not by this product: {kind} {external_id}. It "
        "runs on this page, but the owner's current plan answers only about "
        "the advertising made here. Every other plan answers about what they "
        "built in Ads Manager too. Say that plainly and suggest moving to "
        "another plan on the plans screen; give none of its figures, names or "
        "settings."
    )


BUILT_IN_ADS_MANAGER = "built in Ads Manager, not by this product"


def origin(scope: PageScope, *, level: str, external_id: str, parent: str = "") -> str:
    """`` - built in Ads Manager...`` for such an object, or nothing."""
    if scope.was_built_elsewhere(level=level, external_id=external_id, parent=parent):
        return f" - {BUILT_IN_ADS_MANAGER}"
    return ""


def refused(
    *, scope: PageScope, kind: str, level: str, external_id: str, parent: str = ""
) -> str:
    """Why this object was found and will not be described."""
    if scope.was_built_elsewhere(level=level, external_id=external_id, parent=parent):
        return unbuilt(kind, external_id)
    on_other = scope.on_other_page(level=level, external_id=external_id, parent=parent)
    return (elsewhere if on_other else outside)(kind, external_id)


def named(name: str, fallback: str) -> str:
    """A name in quotes, or the id when the provider sent no name."""
    return f'"{name or fallback}"'


def section(title: str, rows: list[str], *, empty: str) -> list[str]:
    """A heading and its rows, or the heading and what their absence means."""
    return [f"## {title}", *(rows or [f"- {empty}"])]


def trimmed(text: str, limit: int) -> str:
    """One line, no longer than ``limit``."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 3].rstrip() + "..."


LEVEL_WORDS: Final[dict[str, str]] = {
    "campaign": "campaign",
    "adset": "ad group",
    "ad": "advert",
    "form": "lead form",
}
_NAMED: Final[dict[str, Any]] = {
    "campaign": Campaign,
    "adset": AdSet,
    "ad": Ad,
    "form": LeadForm,
}


def names_by_level(
    db: Session, *, owner: User, targets: Iterable[tuple[str, str]]
) -> dict[tuple[str, str], str]:
    """``{(level, id): name}`` for the objects a history names. A query a level."""
    wanted: dict[str, set[str]] = {}
    for level, external_id in targets:
        if level in _NAMED and external_id:
            wanted.setdefault(level, set()).add(external_id)
    found: dict[tuple[str, str], str] = {}
    for level, ids in wanted.items():
        model = _NAMED[level]
        rows = db.execute(
            select(model.external_id, model.name).where(
                model.owner_id == owner.id, model.external_id.in_(ids)
            )
        )
        found.update({(level, str(each)): str(name) for each, name in rows})
    return found


__all__ = [
    "BUILT_IN_ADS_MANAGER",
    "LEVEL_WORDS",
    "elsewhere",
    "figure_sums",
    "in_subscription",
    "money",
    "named",
    "names_by_level",
    "origin",
    "outside",
    "page_currency",
    "refused",
    "section",
    "subscribed_accounts",
    "subscribed_pages",
    "trimmed",
    "unbuilt",
    "window",
]
