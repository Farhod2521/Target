import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.integrations.models import AdAccount, PageAccount, PagePair
from app.modules.integrations.selectors.slots import enabled_pages, page_shown


@dataclass(frozen=True, slots=True)
class Pair:
    page: PageAccount
    account: AdAccount
    stored: bool
    first: bool

    @property
    def key(self) -> str:
        return f"{self.page.external_id}:{self.account.external_id}"


def _stored_rows(
    db: Session, *, owner: User, pages: Sequence[PageAccount]
) -> list[PagePair]:
    return list(
        db.scalars(
            select(PagePair)
            .join(AdAccount, AdAccount.id == PagePair.ad_account_id)
            .where(
                PagePair.owner_id == owner.id,
                PagePair.page_id.in_([page.id for page in pages]),
                AdAccount.provider == PROVIDER,
            )
            .order_by(PagePair.created_at)
        )
    )


def page_pairs(
    db: Session, *, owner: User, pages: Sequence[PageAccount] | None = None
) -> list[Pair]:
    shown = enabled_pages(db, owner=owner) if pages is None else list(pages)
    if not shown:
        return []
    stored: dict[uuid.UUID, list[AdAccount]] = defaultdict(list)
    for pair in _stored_rows(db, owner=owner, pages=shown):
        stored[pair.page_id].append(pair.ad_account)
    fallback = _fallback_accounts(db, owner=owner, pages=shown, stored=stored)
    found: list[Pair] = []
    for page in shown:
        accounts = stored.get(page.id)
        if accounts:
            found += [
                Pair(page=page, account=account, stored=True, first=index == 0)
                for index, account in enumerate(accounts)
            ]
        elif page.id in fallback:
            found.append(
                Pair(page=page, account=fallback[page.id], stored=False, first=True)
            )
    return found


def _fallback_accounts(
    db: Session,
    *,
    owner: User,
    pages: Sequence[PageAccount],
    stored: dict[uuid.UUID, list[AdAccount]],
) -> dict[uuid.UUID, AdAccount]:
    waiting = [page for page in pages if page.id not in stored]
    if not waiting:
        return {}
    remembered = {page.ad_account_id for page in waiting if page.ad_account_id}
    accounts = {
        account.id: account
        for account in db.scalars(
            select(AdAccount).where(
                AdAccount.owner_id == owner.id,
                AdAccount.provider == PROVIDER,
                AdAccount.id.in_(remembered),
            )
        )
    }
    current = db.scalar(
        select(AdAccount).where(
            AdAccount.owner_id == owner.id,
            AdAccount.provider == PROVIDER,
            AdAccount.is_current.is_(True),
        )
    )
    found: dict[uuid.UUID, AdAccount] = {}
    for page in waiting:
        account = accounts.get(page.ad_account_id) if page.ad_account_id else None
        account = account or current
        if account is not None:
            found[page.id] = account
    return found


def stored_pairs(
    db: Session, *, owner: User, pages: Sequence[PageAccount]
) -> list[Pair]:
    if not pages:
        return []
    by_page = {page.id: page for page in pages}
    found: list[Pair] = []
    seen: set[uuid.UUID] = set()
    for pair in _stored_rows(db, owner=owner, pages=pages):
        found.append(
            Pair(
                page=by_page[pair.page_id],
                account=pair.ad_account,
                stored=True,
                first=pair.page_id not in seen,
            )
        )
        seen.add(pair.page_id)
    return found


def pair_on(pairs: Sequence[Pair], page: PageAccount | None) -> Pair | None:
    if page is None:
        return None
    own = [pair for pair in pairs if pair.page.id == page.id]
    return next((pair for pair in own if pair.account.is_current), None) or (
        own[0] if own else None
    )


def current_pair(
    db: Session, *, owner: User, pairs: Sequence[Pair] | None = None
) -> Pair | None:
    pairs = page_pairs(db, owner=owner) if pairs is None else pairs
    page = page_shown(_pages_of(pairs))
    if page is None:
        return None
    own = [pair for pair in pairs if pair.page.id == page.id]
    return next((pair for pair in own if pair.account.is_current), own[0])


def pairs_by_page(pairs: Sequence[Pair]) -> dict[str, frozenset[str]]:
    found: dict[str, set[str]] = defaultdict(set)
    for pair in pairs:
        if pair.stored:
            found[pair.page.external_id].add(pair.account.external_id)
    return {page: frozenset(accounts) for page, accounts in found.items()}


def pair_for(
    db: Session, *, owner: User, page_external_id: str, account_external_id: str
) -> Pair | None:
    return next(
        (
            pair
            for pair in page_pairs(db, owner=owner)
            if pair.page.external_id == page_external_id
            and pair.account.external_id == account_external_id
        ),
        None,
    )


def unconfirmed_pages(db: Session, *, owner: User) -> list[PageAccount]:
    paired = select(PagePair.page_id).where(PagePair.owner_id == owner.id)
    return list(
        db.scalars(
            select(PageAccount)
            .where(
                PageAccount.owner_id == owner.id,
                PageAccount.provider == PROVIDER,
                PageAccount.is_active.is_(True),
                PageAccount.id.not_in(paired),
            )
            .order_by(PageAccount.is_current.desc(), PageAccount.name)
        )
    )


def _pages_of(pairs: Sequence[Pair]) -> list[PageAccount]:
    return list({pair.page.id: pair.page for pair in pairs}.values())
