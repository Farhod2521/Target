"""Which pair the waiting list is about, and the accounts that pay for it."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.selectors.launched import all_launched_campaign_ids
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.ads.selectors.pages import page_scope, paying_accounts
from app.modules.integrations.models import AdAccount, PageAccount
from app.modules.integrations.selectors.pairs import Pair, pair_on, stored_pairs
from app.modules.integrations.selectors.slots import enabled_pages, page_shown
from app.modules.leads.selectors.reads import ShownPage, shown_pair


@dataclass(frozen=True, slots=True)
class InboxPage:
    """The page, its boundary, and its paying accounts, current first.

    ``page`` is ``None`` when the cabinet is pointed at no page in the
    subscription; ``scope`` then holds nothing.
    """

    page: PageAccount | None
    sole: bool
    scope: PageScope
    accounts: tuple[AdAccount, ...]
    second_account: AdAccount | None = None
    lead_view: ShownPage | None = None

    @property
    def home(self) -> AdAccount | None:
        """The account a day and a currency are read from."""
        return self.accounts[0] if self.accounts else None

    @property
    def shown(self) -> ShownPage:
        """The same page, as the customers' side of the product draws it."""
        if self.lead_view is not None:
            return self.lead_view
        return ShownPage(page=self.page, sole=self.sole)

    @property
    def page_id(self) -> str:
        """The page's own id, for the keys that count one page's own things."""
        if self.page is None:
            return ""
        if self.second_account is not None:
            return f"{self.page.external_id}:{self.second_account.external_id}"
        return self.page.external_id

    @property
    def page_name(self) -> str:
        """Which page a line is about, where a reader needs telling."""
        if self.page is None:
            return ""
        page = "" if self.sole else self.page.name or self.page.external_id
        if self.second_account is None:
            return page
        account = self.second_account.name or self.second_account.external_id
        return f"{page} · {account}" if page else account


def built_here(db: Session, *, owner: User, view: InboxPage) -> PageScope:
    """The page's boundary drawn around what this product launched."""
    return view.scope.built_here(all_launched_campaign_ids(db, owner=owner))


def inbox_page(db: Session, *, owner: User) -> InboxPage:
    """The page the owner is on."""
    whole = page_scope(db, owner=owner)
    pages = enabled_pages(db, owner=owner)
    pairs = stored_pairs(db, owner=owner, pages=pages)
    pair = pair_on(pairs, page_shown(pages))
    return _view(
        db, owner=owner, whole=whole, page_id=whole.current, pair=pair, pairs=pairs
    )


def inbox_pages(db: Session, *, owner: User) -> tuple[InboxPage, ...]:
    """Every page of the subscription, one view each - what the phone reads."""
    whole = page_scope(db, owner=owner)
    if not whole.pages:
        return (_view(db, owner=owner, whole=whole, page_id=""),)
    pages = enabled_pages(db, owner=owner)
    pairs = stored_pairs(db, owner=owner, pages=pages)
    paired = {pair.page.id for pair in pairs}
    views = [
        _view(
            db,
            owner=owner,
            whole=whole,
            page_id=pair.page.external_id,
            row=pair.page,
            pair=pair,
            pairs=pairs,
        )
        for pair in pairs
        if pair.page.external_id in whole.pages
    ]
    views += [
        _view(db, owner=owner, whole=whole, page_id=page.external_id, row=page)
        for page in pages
        if page.id not in paired and page.external_id in whole.pages
    ]
    return tuple(views)


def _view(
    db: Session,
    *,
    owner: User,
    whole: PageScope,
    page_id: str,
    row: PageAccount | None = None,
    pair: Pair | None = None,
    pairs: list[Pair] | None = None,
) -> InboxPage:
    """One pair of an already-read boundary, with the accounts paying for it."""
    stored = pair if pair is not None and pair.stored else None
    scope = whole.only(page_id, stored.account.external_id if stored else "")
    page = row or _page_row(db, owner=owner, page_id=page_id)
    sole = len(whole.pages) == 1
    return InboxPage(
        page=page,
        sole=sole,
        scope=scope,
        accounts=(stored.account,)
        if stored is not None
        else paying_accounts(db, owner=owner, campaign_ids=scope.campaign_ids),
        second_account=stored.account
        if stored is not None and not stored.first
        else None,
        lead_view=shown_pair(pair=pair, pairs=pairs or [], sole=sole)
        if pair is not None and page is not None
        else None,
    )


def _page_row(db: Session, *, owner: User, page_id: str) -> PageAccount | None:
    if not page_id:
        return None
    return db.scalar(
        select(PageAccount)
        .where(
            PageAccount.owner_id == owner.id,
            PageAccount.external_id == page_id,
            PageAccount.is_active.is_(True),
        )
        .limit(1)
    )


__all__ = ["InboxPage", "built_here", "inbox_page", "inbox_pages"]
