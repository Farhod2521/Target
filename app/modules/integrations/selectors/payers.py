import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.integrations.models import AdAccount, PageAccount
from app.modules.integrations.selectors.pairs import stored_pairs
from app.modules.integrations.selectors.portfolio import misfit


@dataclass(frozen=True, slots=True)
class PayerOption:
    account: AdAccount
    recommended: bool
    unusable: bool
    # Why this account may not be newly paired with the page - a code from
    # ``portfolio`` - or "". Accounts already paired with it keep "".
    not_for_page: str = ""


@dataclass(frozen=True, slots=True)
class PagePayer:
    page: PageAccount | None
    payer: AdAccount | None
    options: tuple[PayerOption, ...]
    paired: tuple[AdAccount, ...] = ()

    @property
    def addable(self) -> tuple[PayerOption, ...]:
        taken = {account.id for account in self.paired}
        return tuple(
            o for o in self.options if not o.unusable and o.account.id not in taken
        )

    @property
    def recommended(self) -> tuple[PayerOption, ...]:
        return tuple(o for o in self.options if o.recommended and not o.unusable)

    @property
    def others(self) -> tuple[PayerOption, ...]:
        return tuple(o for o in self.options if not o.recommended and not o.unusable)

    @property
    def unusable(self) -> tuple[PayerOption, ...]:
        return tuple(o for o in self.options if o.unusable)


def page_payers(
    db: Session, *, owner: User, pages: Sequence[PageAccount]
) -> tuple[PagePayer, ...]:
    from app.modules.ads.selectors import accounts_that_paid_by_page

    accounts = _accounts(db, owner)
    history = accounts_that_paid_by_page(db, owner=owner) if pages else {}
    paired: dict[uuid.UUID, list[AdAccount]] = {}
    for pair in stored_pairs(db, owner=owner, pages=pages):
        paired.setdefault(pair.page.id, []).append(pair.account)
    return tuple(
        _payer(
            page,
            accounts=accounts,
            paid=history.get(page.id, frozenset()),
            paired=tuple(paired.get(page.id, ())),
        )
        for page in pages
    )


def new_page_payer(db: Session, *, owner: User) -> PagePayer:
    return _payer(None, accounts=_accounts(db, owner), paid=frozenset())


def confirm_payer(
    db: Session, *, owner: User, page: PageAccount, shown: AdAccount
) -> PagePayer:
    payer = _payer(page, accounts=_accounts(db, owner), paid=frozenset())
    return PagePayer(page=page, payer=shown, options=payer.options)


def _accounts(db: Session, owner: User) -> list[AdAccount]:
    return list(
        db.scalars(
            select(AdAccount)
            .where(AdAccount.owner_id == owner.id, AdAccount.provider == PROVIDER)
            .order_by(AdAccount.is_current.desc(), AdAccount.name)
        )
    )


def _payer(
    page: PageAccount | None,
    *,
    accounts: list[AdAccount],
    paid: frozenset[uuid.UUID],
    paired: tuple[AdAccount, ...] = (),
) -> PagePayer:
    by_pk = {account.id: account for account in accounts}
    current = next((account for account in accounts if account.is_current), None)
    chosen = next((account for account in paired if account.is_current), None)
    if chosen is None and paired:
        chosen = paired[0]
    if chosen is None and page and page.ad_account_id:
        chosen = by_pk.get(page.ad_account_id)
    kept = {account.id for account in paired}
    if page is not None and page.ad_account_id:
        kept.add(page.ad_account_id)
    options = []
    for account in accounts:
        reason = "" if page is None or account.id in kept else misfit(page, account)
        options.append(
            PayerOption(
                account=account,
                recommended=account.id in paid,
                unusable=(account.may_advertise is False and not account.payment_due)
                or not account.is_reachable
                or bool(reason),
                not_for_page=reason,
            )
        )
    options.sort(key=lambda option: (option.unusable, not option.recommended))
    # The cabinet's current account is suggested only where it may go.
    if (
        chosen is None
        and current is not None
        and page is not None
        and page.business_state
        and misfit(page, current)
    ):
        current = next((o.account for o in options if not o.unusable), None)
    return PagePayer(
        page=page, payer=chosen or current, options=tuple(options), paired=paired
    )
