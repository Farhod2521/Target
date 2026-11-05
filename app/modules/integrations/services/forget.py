"""Forgetting everything an owner brought in through Meta.

What is ours goes: the connection, pages, ad accounts, pixels, adverts and
their figures, leads, forms, the CRM with its managers, the assistant's
findings, brand kits. Nothing is asked of Meta: adverts and audiences stay in
Ads Manager as they are.

What the owner bought stays: the subscription, its extra pages, the seats.
The subscription is unbound and its setup asked again, so the next Meta
login starts like a first one. One business profile is kept pageless; the
next page adopts it.

The journal stays as well: ``action_logs`` and the office's own rows are the
answer to "what happened before".
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from metaads import PROVIDER
from sqlalchemy import ColumnElement, Select, and_, func, or_, select, update
from sqlalchemy.orm import Session

from app.common import storage
from app.common.db import on_commit, utcnow
from app.common.deletion import delete_rows
from app.modules.accounts.models import User
from app.modules.ads.models import (
    AdCreative,
    Campaign,
    CampaignLaunch,
    GoalCampaign,
    InterestTerm,
    LapseHold,
    LaunchCreative,
    MediaAsset,
)
from app.modules.agent.models import (
    AdSetDiagnosis,
    AgentFix,
    AgentRun,
    AgentSuggestion,
)
from app.modules.billing.constants import LIVE_SUBSCRIPTION_STATUSES
from app.modules.billing.models import Subscription
from app.modules.businesses.models import Business
from app.modules.content_studio.models import BrandKit
from app.modules.crm.models import CrmCard, CrmMember
from app.modules.destinations.models import FormSheet, SheetLink
from app.modules.integrations.models import (
    AdAccount,
    CustomAudience,
    PageAccount,
    PagePair,
    PixelAccount,
    ProviderConnection,
)
from app.modules.leads.models import Lead, LeadForm, RawLeadEvent
from app.modules.metrics.models import MetricsBreakdown, MetricsDaily

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MetaHoldings:
    """How much one owner has from Meta: what the dialog shows before, the
    journal keeps after."""

    connected: bool
    pages: int
    ad_accounts: int
    pixels: int
    launches: int
    campaigns: int
    leads: int
    cards: int
    managers: int
    audiences: int
    brand_kits: int

    @property
    def anything(self) -> bool:
        return self.connected or any(
            (self.pages, self.ad_accounts, self.leads, self.launches, self.campaigns)
        )

    def as_detail(self) -> dict[str, int | bool]:
        return {
            "connected": self.connected,
            "pages": self.pages,
            "ad_accounts": self.ad_accounts,
            "pixels": self.pixels,
            "launches": self.launches,
            "campaigns": self.campaigns,
            "leads": self.leads,
            "cards": self.cards,
            "managers": self.managers,
            "audiences": self.audiences,
            "brand_kits": self.brand_kits,
        }


@dataclass
class Forgotten:
    holdings: MetaHoldings
    rows: dict[str, int] = field(default_factory=dict)
    files: int = 0
    kept_business: bool = False


def _pages(owner: User) -> Select[Any]:
    return select(PageAccount.id).where(
        PageAccount.owner_id == owner.id, PageAccount.provider == PROVIDER
    )


def _accounts(owner: User) -> Select[Any]:
    return select(AdAccount.id).where(
        AdAccount.owner_id == owner.id, AdAccount.provider == PROVIDER
    )


def _count(db: Session, model: Any, *where: ColumnElement[bool]) -> int:
    return int(db.scalar(select(func.count()).select_from(model).where(*where)) or 0)


def meta_holdings(db: Session, *, owner: User) -> MetaHoldings:
    mine = owner.id
    return MetaHoldings(
        connected=_count(
            db,
            ProviderConnection,
            ProviderConnection.owner_id == mine,
            ProviderConnection.provider == PROVIDER,
        )
        > 0,
        pages=_count(db, PageAccount, PageAccount.id.in_(_pages(owner))),
        ad_accounts=_count(db, AdAccount, AdAccount.id.in_(_accounts(owner))),
        pixels=_count(
            db, PixelAccount, PixelAccount.ad_account_id.in_(_accounts(owner))
        ),
        launches=_count(
            db,
            CampaignLaunch,
            CampaignLaunch.owner_id == mine,
            CampaignLaunch.provider == PROVIDER,
        ),
        campaigns=_count(db, Campaign, Campaign.ad_account_id.in_(_accounts(owner))),
        leads=_count(db, Lead, Lead.owner_id == mine, Lead.provider == PROVIDER),
        cards=_count(db, CrmCard, CrmCard.owner_id == mine),
        managers=_count(db, CrmMember, CrmMember.owner_id == mine),
        audiences=_count(
            db, CustomAudience, CustomAudience.ad_account_id.in_(_accounts(owner))
        ),
        brand_kits=_count(db, BrandKit, BrandKit.page_id.in_(_pages(owner))),
    )


def forget_meta(db: Session, *, owner: User, actor: User) -> Forgotten:
    """Everything Meta brought, gone from our side; the caller commits.

    Takes the connection row first, so a reconnect running at the same moment
    waits for this to finish rather than writing into what is being removed.
    """
    from app.modules.crm.services import erase_crm

    db.scalars(
        select(ProviderConnection.id)
        .where(
            ProviderConnection.owner_id == owner.id,
            ProviderConnection.provider == PROVIDER,
        )
        .with_for_update()
    ).all()
    holdings = meta_holdings(db, owner=owner)
    done = Forgotten(holdings=holdings)
    if not holdings.anything:
        return done
    files = _files(db, owner=owner)
    done.kept_business = _keep_one_business(db, owner=owner)
    erase_crm(db, owner=owner, actor=actor)
    _unbind_subscriptions(db, owner=owner)
    rows = done.rows
    forms = select(LeadForm.id).where(
        LeadForm.owner_id == owner.id, LeadForm.provider == PROVIDER
    )
    db.execute(
        update(SheetLink)
        .where(SheetLink.owner_id == owner.id, SheetLink.only_form_id.in_(forms))
        .values(only_form_id=None, updated_at=utcnow())
    )

    def gone(label: str, model: Any, *where: ColumnElement[bool]) -> None:
        count = delete_rows(db, model.__table__, and_(*where))
        if count:
            rows[label] = rows.get(label, 0) + count

    mine = owner.id
    gone("leads", Lead, Lead.owner_id == mine, Lead.provider == PROVIDER)
    gone(
        "raw_lead_events",
        RawLeadEvent,
        RawLeadEvent.provider == PROVIDER,
        or_(
            RawLeadEvent.owner_id == mine,
            and_(
                RawLeadEvent.owner_id.is_(None),
                RawLeadEvent.page_external_id.in_(_unshared_pages(owner)),
            ),
        ),
    )
    gone(
        "form_sheets",
        FormSheet,
        FormSheet.owner_id == mine,
        FormSheet.form_id.in_(forms),
    )
    gone("lead_forms", LeadForm, LeadForm.id.in_(forms))
    gone(
        "suggestions",
        AgentSuggestion,
        AgentSuggestion.owner_id == mine,
        AgentSuggestion.target_provider == PROVIDER,
    )
    gone("fixes", AgentFix, AgentFix.owner_id == mine)
    gone(
        "diagnoses",
        AdSetDiagnosis,
        AdSetDiagnosis.owner_id == mine,
        AdSetDiagnosis.provider == PROVIDER,
    )
    gone(
        "agent_runs",
        AgentRun,
        AgentRun.owner_id == mine,
        AgentRun.id.not_in(
            select(AgentSuggestion.run_id).where(AgentSuggestion.run_id.is_not(None))
        ),
    )
    gone(
        "launches",
        CampaignLaunch,
        CampaignLaunch.owner_id == mine,
        or_(
            CampaignLaunch.provider == PROVIDER,
            CampaignLaunch.ad_account_id.in_(_accounts(owner)),
            CampaignLaunch.page_id.in_(_pages(owner)),
        ),
    )
    gone(
        "goal_campaigns", GoalCampaign, GoalCampaign.ad_account_id.in_(_accounts(owner))
    )
    gone(
        "media",
        MediaAsset,
        MediaAsset.owner_id == mine,
        MediaAsset.provider == PROVIDER,
    )
    gone(
        "interests",
        InterestTerm,
        InterestTerm.owner_id == mine,
        InterestTerm.provider == PROVIDER,
    )
    for label, model in (("metrics", MetricsDaily), ("breakdowns", MetricsBreakdown)):
        gone(label, model, model.owner_id == mine, model.provider == PROVIDER)
    gone("creatives", AdCreative, AdCreative.ad_account_id.in_(_accounts(owner)))
    gone("pairs", PagePair, PagePair.owner_id == mine)
    # A page let go at a renewal keeps a hold on its adverts; with the page gone
    # there is nothing left to hold.
    gone("lapse_holds", LapseHold, LapseHold.page_id.in_(_pages(owner)))
    gone("pixels", PixelAccount, PixelAccount.ad_account_id.in_(_accounts(owner)))
    gone("pages", PageAccount, PageAccount.id.in_(_pages(owner)))
    gone("ad_accounts", AdAccount, AdAccount.id.in_(_accounts(owner)))
    gone(
        "connection",
        ProviderConnection,
        ProviderConnection.owner_id == mine,
        ProviderConnection.provider == PROVIDER,
    )
    owner.prepared_at = None
    db.flush()

    def unlink() -> None:
        for name in files:
            storage.delete(name)

    on_commit(db, unlink)
    done.files = len(files)
    logger.warning(
        "meta.forgotten",
        extra={"owner": str(owner.id), "actor": str(actor.id), "rows": rows},
    )
    return done


def _unshared_pages(owner: User) -> Select[Any]:
    shared = select(PageAccount.external_id).where(PageAccount.owner_id != owner.id)
    return select(PageAccount.external_id).where(
        PageAccount.owner_id == owner.id,
        PageAccount.provider == PROVIDER,
        PageAccount.external_id != "",
        PageAccount.external_id.not_in(shared),
    )


def _files(db: Session, *, owner: User) -> list[str]:
    """Uploads that only the rows going now point at."""
    names: list[str] = []
    launches = select(CampaignLaunch.id).where(
        CampaignLaunch.owner_id == owner.id,
        or_(
            CampaignLaunch.provider == PROVIDER,
            CampaignLaunch.ad_account_id.in_(_accounts(owner)),
            CampaignLaunch.page_id.in_(_pages(owner)),
        ),
    )
    names.extend(
        db.scalars(
            select(LaunchCreative.media_upload).where(
                LaunchCreative.launch_id.in_(launches)
            )
        )
    )
    for row in db.execute(
        select(
            BrandKit.logo,
            BrandKit.logo_trimmed,
            BrandKit.logo_on_dark,
            BrandKit.logo_on_light,
        ).where(BrandKit.page_id.in_(_pages(owner)))
    ):
        names.extend(row)
    return [name for name in names if name]


def _keep_one_business(db: Session, *, owner: User) -> bool:
    """The profile the owner typed in outlives the pages: the current page's,
    else the newest, becomes pageless unless a pageless one is already there."""
    if db.scalar(
        select(Business.id).where(
            Business.user_id == owner.id,
            Business.page_id.is_(None),
            Business.ad_account_id.is_(None),
        )
    ):
        return False
    keep = db.scalar(
        select(Business)
        .join(PageAccount, PageAccount.id == Business.page_id)
        .where(Business.user_id == owner.id, PageAccount.provider == PROVIDER)
        .order_by(PageAccount.is_current.desc(), Business.updated_at.desc())
        .limit(1)
    )
    if keep is None:
        return False
    keep.page_id = None
    keep.updated_at = utcnow()
    db.flush()
    return True


def _unbind_subscriptions(db: Session, *, owner: User) -> None:
    """Every bill keeps its plan, days, pages and seats; none keeps the ad
    account, and the live one asks for its setup again."""
    now = utcnow()
    db.execute(
        update(Subscription)
        .where(
            Subscription.owner_id == owner.id,
            Subscription.ad_account_id.in_(_accounts(owner)),
        )
        .values(ad_account_id=None, updated_at=now)
    )
    db.execute(
        update(Subscription)
        .where(
            Subscription.owner_id == owner.id,
            Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
            Subscription.setup_completed_at.is_not(None),
        )
        .values(setup_completed_at=None, updated_at=now)
    )


__all__ = ["Forgotten", "MetaHoldings", "forget_meta", "meta_holdings"]
