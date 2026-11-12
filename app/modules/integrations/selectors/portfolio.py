"""Which ad accounts a page may be paired with: the page's own portfolio.

The rule the page picker shows and every new pair is checked against:

- a page in a portfolio pairs only with ad accounts of that portfolio - its
  own and those shared into it;
- a personal page (no portfolio) pairs only with personal ad accounts;
- a page whose portfolio is not known pairs with nothing until it is.

Pairs made before this rule are left alone; only a new pair is checked.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from app.modules.integrations.models import AdAccount, PageAccount

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.modules.accounts.models import User

BUSINESS: Final = "business"
PERSONAL: Final = "personal"
UNKNOWN: Final = "unknown"

# Why a page offers no account, or why one account is not for it. Codes for
# the front; the words are ours.
FITS: Final = ""
OTHER_PORTFOLIO: Final = "other_portfolio"
NOT_PERSONAL: Final = "not_personal"
PAGE_UNKNOWN: Final = "page_unknown"
PAGE_UNCHECKED: Final = "page_unchecked"

REASONS: Final[dict[str, str]] = {
    OTHER_PORTFOLIO: "Bu akkaunt sahifa turgan biznes portfoliosida emas.",
    NOT_PERSONAL: "Sahifa shaxsiy - unga faqat shaxsiy reklama akkauntlari mos keladi.",
    PAGE_UNKNOWN: (
        "Sahifa qaysi biznes portfoliosida ekanini Meta aytmadi. Sahifada to'liq "
        "boshqaruv (admin) huquqi kerak - huquqni olib, akkauntlarni yangilang."
    ),
    PAGE_UNCHECKED: "Sahifaning biznes portfoliosi tekshirilmoqda. Birozdan so'ng yangilang.",
}


def account_portfolios(account: AdAccount) -> frozenset[str]:
    """The owner (stored before this rule too) and every portfolio shared into."""
    found = set(account.business_ids or ())
    if account.business_external_id:
        found.add(account.business_external_id)
    return frozenset(found)


def page_portfolios(page: PageAccount) -> frozenset[str]:
    return frozenset(page.business_ids or ())


def misfit(page: PageAccount, account: AdAccount) -> str:
    """Why this account may not pair with this page, or ``FITS``."""
    state = page.business_state or ""
    if state == BUSINESS:
        if page_portfolios(page) & account_portfolios(account):
            return FITS
        return OTHER_PORTFOLIO
    if state == PERSONAL:
        return NOT_PERSONAL if account_portfolios(account) else FITS
    if state == UNKNOWN:
        return PAGE_UNKNOWN
    return PAGE_UNCHECKED


def fits(page: PageAccount, account: AdAccount) -> bool:
    return misfit(page, account) == FITS


def page_blocked(page: PageAccount) -> str:
    """Why no account at all may pair with this page, or ``FITS``."""
    state = page.business_state or ""
    if state == UNKNOWN:
        return PAGE_UNKNOWN
    if state not in (BUSINESS, PERSONAL):
        return PAGE_UNCHECKED
    return FITS


@dataclass(frozen=True, slots=True)
class PageFit:
    """What the picker shows for one page."""

    page: str
    business_state: str
    business_id: str
    business_name: str
    allowed_ad_accounts: tuple[str, ...]
    blocked_reason: str
    blocked_text: str
    # Whether a new ad account may be made for it: only in a portfolio.
    may_create_account: bool


def page_fit(page: PageAccount, accounts: Iterable[AdAccount]) -> PageFit:
    blocked = page_blocked(page)
    allowed = () if blocked else tuple(a.external_id for a in accounts if fits(page, a))
    return PageFit(
        page=page.external_id,
        business_state=page.business_state or "",
        business_id=page.business_external_id or "",
        business_name=page.business_name or "",
        allowed_ad_accounts=allowed,
        blocked_reason=blocked,
        blocked_text=REASONS.get(blocked, ""),
        may_create_account=bool(create_in(page)),
    )


def create_in(page: PageAccount) -> str:
    """The portfolio a new ad account for this page is made in, or "".

    The owner when Meta named it, else the first portfolio holding the page
    as a client - an account made there pairs with the page either way.
    """
    if page.business_state != BUSINESS:
        return ""
    return page.business_external_id or next(iter(page.business_ids or ()), "")


def page_fits(db: "Session", *, owner: "User") -> list[PageFit]:
    """The picker's answer for every Meta page this cabinet holds."""
    from app.modules.integrations.selectors.connection import ad_accounts, pages

    accounts = ad_accounts(db, owner=owner)
    return [page_fit(page, accounts) for page in pages(db, owner=owner)]


def unchecked(db: "Session", *, owner: "User") -> bool:
    """Whether a page of this cabinet has never had its portfolio read."""
    from app.modules.integrations.selectors.connection import pages

    return any(not page.business_state for page in pages(db, owner=owner))
