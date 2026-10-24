"""The campaigns one page's figures are summed over."""

from dataclasses import dataclass
from typing import Final

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.integrations.models import AdAccount, PageAccount
from app.modules.metrics.selectors.facts import Scope, campaigns_scope
from app.modules.metrics.selectors.lead_gap import form_groups

CAMPAIGN_FIELD: Final = "campaign_external_id"


@dataclass(frozen=True, slots=True)
class PageCampaigns:
    page: PageAccount | None
    ids: frozenset[str]
    accounts: tuple[AdAccount, ...] = ()
    sole: bool = False
    foreign: frozenset[str] = frozenset()
    second_account: AdAccount | None = None
    pair_account: AdAccount | None = None

    @property
    def home(self) -> AdAccount | None:
        return self.accounts[0] if self.accounts else None

    @property
    def currency(self) -> str:
        return self.home.currency if self.home is not None else ""

    @property
    def name(self) -> str:
        if self.page is None:
            return ""
        page = "" if self.sole else self.page.name or self.page.external_id
        if self.second_account is None:
            return page
        account = self.second_account.name or self.second_account.external_id
        return f"{page} · {account}" if page else account

    @property
    def key(self) -> str:
        if self.page is None:
            return ""
        if self.second_account is None:
            return self.page.external_id
        return f"{self.page.external_id}:{self.second_account.external_id}"

    @property
    def condition(self) -> Scope:
        return campaigns_scope(self.ids)


def page_campaigns(db: Session, *, owner: User) -> PageCampaigns:
    from app.modules.ads.selectors import page_advertising

    return _campaigns(db, owner=owner, found=page_advertising(db, owner=owner))


def pages_campaigns(db: Session, *, owner: User) -> tuple[PageCampaigns, ...]:
    from app.modules.ads.selectors import pages_advertising

    return tuple(_campaigns(db, owner=owner, found=found) for found in pages_advertising(db, owner=owner))


def _campaigns(db: Session, *, owner: User, found: object) -> PageCampaigns:
    here, foreign = _one_currency(db, owner=owner, found=found)
    return PageCampaigns(
        page=found.page,  # type: ignore[attr-defined]
        ids=here,
        accounts=found.accounts,  # type: ignore[attr-defined]
        sole=found.sole,  # type: ignore[attr-defined]
        foreign=foreign,
        second_account=found.pair_account if not found.first_pair else None,  # type: ignore[attr-defined]
        pair_account=found.pair_account,  # type: ignore[attr-defined]
    )


def _one_currency(db: Session, *, owner: User, found: object) -> tuple[frozenset[str], frozenset[str]]:
    """Figures in two currencies do not add up: keep the home account's."""
    from app.modules.ads.models import Campaign

    accounts = found.accounts  # type: ignore[attr-defined]
    here = found.here  # type: ignore[attr-defined]
    if len({account.currency for account in accounts}) < 2:
        return here, frozenset()
    home = accounts[0].currency
    foreign = frozenset(
        str(external_id)
        for external_id in db.scalars(
            select(Campaign.external_id)
            .join(AdAccount, AdAccount.id == Campaign.ad_account_id)
            .where(
                Campaign.owner_id == owner.id,
                Campaign.external_id.in_(list(here)),
                AdAccount.currency != home,
            )
        )
    )
    return here - foreign, foreign


def kind_scope(*, campaign_ids: frozenset[str]) -> Scope:
    return campaigns_scope(campaign_ids)


def form_scope(db: Session, *, owner: User) -> Scope:
    """Everything except the ad sets whose result is not a form."""
    from app.modules.ads.models import AdSet

    forms = form_groups(owner).with_only_columns(AdSet.id)
    other = list(
        db.scalars(
            select(AdSet.external_id).where(
                AdSet.owner_id == owner.id,
                AdSet.optimization_goal_raw != "",
                AdSet.id.not_in(forms),
            )
        )
    )
    return lambda model: model.adset_external_id.not_in(other)


def has_form_groups(
    db: Session,
    *,
    owner: User,
    account: AdAccount | None = None,
    campaign_ids: frozenset[str] | None = None,
) -> bool:
    from app.modules.ads.models import AdSet, Campaign

    query = select(AdSet.id).join(Campaign, Campaign.id == AdSet.campaign_id).where(
        AdSet.owner_id == owner.id
    )
    if campaign_ids is not None:
        query = query.where(Campaign.external_id.in_(list(campaign_ids)))
    elif account is not None:
        query = query.where(Campaign.ad_account_id == account.id)
    if db.scalar(query.limit(1)) is None:
        return True
    forms = form_groups(owner).with_only_columns(AdSet.id)
    return (
        db.scalar(
            query.where(or_(AdSet.optimization_goal_raw == "", AdSet.id.in_(forms))).limit(1)
        )
        is not None
    )
