"""The subscription's pairs, each with its boundary, for the readers that judge."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.ads.selectors.pages import pages_advertising
from app.modules.integrations.models import AdAccount


@dataclass(frozen=True, slots=True)
class PairView:
    """One pair's key, its page, its boundary and the accounts inside it."""

    key: str
    page: str
    scope: PageScope
    accounts: tuple[AdAccount, ...]


def pair_views(
    db: Session, *, owner: User, whole: PageScope, accounts: list[AdAccount]
) -> list[PairView]:
    """One view per pair of the subscription, in the switcher's order."""
    views: list[PairView] = []
    for found in pages_advertising(db, owner=owner):
        if found.page is None:
            continue
        page = found.page.external_id
        paired = found.pair_account.external_id if found.pair_account else ""
        scope = whole.only(page, paired)
        held = set(scope.account_of.values())
        views.append(
            PairView(
                key=page if found.first_pair or not paired else f"{page}:{paired}",
                page=page,
                scope=scope,
                accounts=tuple(
                    account for account in accounts if account.external_id in held
                ),
            )
        )
    return views


__all__ = ["PairView", "pair_views"]
