"""The preparation screen's page step: each page with the account that pays.

Every row carries its own problems rather than only the chosen one: the
"not ready yet" warning before a choice is drawn from the whole list.
"""

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.billing.selectors import setup_locked
from app.modules.businesses.models import Business
from app.modules.businesses.selectors import profiles_by_page
from app.modules.integrations.models import AdAccount, PageAccount
from app.modules.integrations.selectors import (
    Pair,
    ad_accounts,
    enabled_pages,
    page_pairs,
)
from app.modules.integrations.selectors.connection import pages

# What stops a page from advertising, in the order the screen names them.
Problem = Literal[
    "no_account", "account_off", "account_debt", "no_profile", "page_role"
]
# What a page can advertise without, but is worse off for.
Warning = Literal["account_cap", "no_instagram"]


@dataclass(frozen=True, slots=True)
class PageRow:
    """One page in the step, and why it could not advertise today."""

    page: PageAccount
    payer: AdAccount | None
    profile: Business | None
    problems: tuple[Problem, ...]
    warnings: tuple[Warning, ...]
    # The account was stored by somebody's choice; fixed once setup is done.
    paired: bool = False

    @property
    def ready(self) -> bool:
        return not self.problems


@dataclass(frozen=True, slots=True)
class AccountOption:
    """One ad account in the chosen page's picker."""

    account: AdAccount
    # A campaign for this page was already made on it.
    recommended: bool
    # Meta has switched it off. Listed, never chosen.
    unusable: bool


@dataclass(frozen=True, slots=True)
class PagePick:
    rows: tuple[PageRow, ...]
    chosen: PageRow | None
    options: tuple[AccountOption, ...]

    @property
    def recommended(self) -> tuple[AccountOption, ...]:
        return tuple(o for o in self.options if o.recommended and not o.unusable)

    @property
    def others(self) -> tuple[AccountOption, ...]:
        return tuple(o for o in self.options if not o.recommended and not o.unusable)

    @property
    def unusable(self) -> tuple[AccountOption, ...]:
        return tuple(o for o in self.options if o.unusable)

    @property
    def any_without_instagram(self) -> bool:
        return any(not row.page.has_instagram for row in self.rows)


def page_pick(db: Session, *, owner: User) -> PagePick:
    """The pages the step offers, each with its paying account.

    While preparing, every page the token reached; afterwards only the
    pages the subscription holds.
    """
    locked = setup_locked(db, owner=owner)
    offered = enabled_pages(db, owner=owner) if locked else pages(db, owner=owner)
    accounts = ad_accounts(db, owner=owner)
    paired = _pairs_of(db, owner, offered)
    profiles = profiles_by_page(db, owner=owner)

    rows = tuple(
        _row(
            page,
            pair=paired.get(page.id),
            profile=profiles.get(page.id),
            profile_asked=locked,
        )
        for page in offered
    )
    chosen = next((row for row in rows if row.page.is_current), None)
    return PagePick(
        rows=rows,
        chosen=chosen,
        options=_options(db, owner, chosen=chosen, accounts=accounts),
    )


def _pairs_of(
    db: Session, owner: User, offered: list[PageAccount]
) -> dict[uuid.UUID, Pair]:
    """Each page's pair: the current account's, else the oldest."""
    found: dict[uuid.UUID, Pair] = {}
    for pair in page_pairs(db, owner=owner, pages=offered):
        if pair.page.id not in found or pair.account.is_current:
            found[pair.page.id] = pair
    return found


def _row(
    page: PageAccount,
    *,
    pair: Pair | None,
    profile: Business | None,
    profile_asked: bool,
) -> PageRow:
    payer = pair.account if pair is not None else None
    problems: list[Problem] = []
    warnings: list[Warning] = []
    if payer is None:
        problems.append("no_account")
    elif payer.payment_due:
        problems.append("account_debt")
    elif payer.may_advertise is False:
        problems.append("account_off")
    if payer is not None and payer.cap_reached:
        warnings.append("account_cap")
    # While preparing, the profile is the step after this one.
    if profile_asked and (profile is None or not profile.category):
        problems.append("no_profile")
    if page.may_advertise is False:
        problems.append("page_role")
    if not page.instagram_user_id:
        warnings.append("no_instagram")
    return PageRow(
        page=page,
        payer=payer,
        profile=profile,
        problems=tuple(problems),
        warnings=tuple(warnings),
        paired=pair is not None and pair.stored,
    )


def _options(
    db: Session, owner: User, *, chosen: PageRow | None, accounts: list[AdAccount]
) -> tuple[AccountOption, ...]:
    """The chosen page's accounts: the ones it already ran on first."""
    if chosen is None:
        return ()
    from app.modules.ads.selectors import accounts_that_paid_for

    paid = accounts_that_paid_for(db, owner=owner, page=chosen.page)
    options = [
        AccountOption(
            account=account,
            recommended=account.id in paid,
            unusable=account.may_advertise is False and not account.payment_due,
        )
        for account in accounts
    ]
    options.sort(key=lambda option: (option.unusable, not option.recommended))
    return tuple(options)


__all__ = ["AccountOption", "PagePick", "PageRow", "page_pick"]
