"""Which Facebook page each advert speaks for, and which accounts pay for a page."""

import uuid
from collections import Counter
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from metaads import PROVIDER as META
from metaads.writing import is_dry_run_id
from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.orm import Session, aliased

from app.modules.accounts.models import User
from app.modules.ads import refs as ref_field
from app.modules.ads.constants import Delivery, LaunchStatus, LaunchStep
from app.modules.ads.models import Ad, AdCreative, AdSet, Campaign, CampaignLaunch
from app.modules.ads.selectors.launched import campaign_launch, launch_pages
from app.modules.ads.selectors.page_boundary import NO_PAGE, PageScope
from app.modules.integrations.models import AdAccount, PageAccount
from core.ads import page_of_post, page_of_promoted

# -- the page an ad set promotes ------------------------------------------------------


def pages_by_adset(db: Session, *, owner: User, adset_ids: Iterable[str]) -> dict[str, str]:
    ids = list(adset_ids)
    if not ids:
        return {}
    promoted = dict(
        db.execute(
            select(AdSet.external_id, AdSet.promoted_object_raw).where(
                AdSet.owner_id == owner.id, AdSet.external_id.in_(ids)
            )
        ).all()
    )
    return pages_by_promoted(db, owner=owner, promoted=promoted, adset_ids=ids)


def pages_by_promoted(
    db: Session, *, owner: User, promoted: dict[str, Any], adset_ids: list[str]
) -> dict[str, str]:
    found = {
        external_id: page
        for external_id in adset_ids
        if (page := page_of_promoted(promoted.get(external_id)))
    }
    missing = [external_id for external_id in adset_ids if external_id not in found]
    if missing:
        found.update(_from_adverts(db, owner=owner, adset_ids=missing))
    return found


def _from_adverts(db: Session, *, owner: User, adset_ids: list[str]) -> dict[str, str]:
    adverts = list(
        db.execute(
            select(AdSet.external_id, Ad.creative_external_id)
            .join(AdSet, AdSet.id == Ad.adset_id)
            .where(
                Ad.owner_id == owner.id,
                AdSet.external_id.in_(adset_ids),
                Ad.creative_external_id != "",
            )
            .order_by(Ad.external_id)
        ).all()
    )
    creatives = {creative for _group, creative in adverts}
    pages = {}
    if creatives:
        pages = {
            external_id: page or page_of_post(post)
            for external_id, page, post in db.execute(
                select(
                    AdCreative.external_id, AdCreative.page_id, AdCreative.post_external_id
                ).where(
                    AdCreative.owner_id == owner.id, AdCreative.external_id.in_(creatives)
                )
            )
        }
    found: dict[str, str] = {}
    for group, creative_id in adverts:
        page = pages.get(creative_id, "")
        if group and page and group not in found:
            found[group] = page
    return found


def live_groups_by_page(db: Session, *, owner: User) -> dict[str, int]:
    ids = list(
        db.scalars(
            select(AdSet.external_id).where(
                AdSet.owner_id == owner.id, AdSet.delivery == str(Delivery.ACTIVE)
            )
        )
    )
    return dict(Counter(pages_by_adset(db, owner=owner, adset_ids=ids).values()))


# -- who pays -------------------------------------------------------------------------


def paying_accounts(
    db: Session,
    *,
    owner: User,
    campaign_ids: Collection[str],
    launch_accounts: Collection[uuid.UUID] = (),
) -> tuple[AdAccount, ...]:
    from app.modules.integrations.selectors import active_ad_account

    used = select(Campaign.ad_account_id).where(
        Campaign.owner_id == owner.id, Campaign.external_id.in_(list(campaign_ids))
    )
    held = tuple(
        db.scalars(
            select(AdAccount)
            .where(
                AdAccount.owner_id == owner.id,
                AdAccount.provider == META,
                AdAccount.is_active.is_(True),
                or_(AdAccount.id.in_(used), AdAccount.id.in_(list(launch_accounts))),
            )
            .order_by(AdAccount.is_current.desc(), AdAccount.name)
        )
    )
    if held:
        return held
    current = active_ad_account(db, owner=owner)
    return (current,) if current is not None else ()


def accounts_that_paid_for(
    db: Session, *, owner: User, page: PageAccount
) -> frozenset[uuid.UUID]:
    return frozenset(
        db.scalars(
            select(CampaignLaunch.ad_account_id)
            .where(
                CampaignLaunch.owner_id == owner.id,
                CampaignLaunch.page_id == page.id,
                CampaignLaunch.status == str(LaunchStatus.CREATED),
            )
            .distinct()
        )
    )


def accounts_that_paid_by_page(
    db: Session, *, owner: User
) -> dict[uuid.UUID, frozenset[uuid.UUID]]:
    found: dict[uuid.UUID, set[uuid.UUID]] = {}
    rows = db.execute(
        select(CampaignLaunch.page_id, CampaignLaunch.ad_account_id)
        .where(
            CampaignLaunch.owner_id == owner.id,
            CampaignLaunch.status == str(LaunchStatus.CREATED),
            CampaignLaunch.page_id.is_not(None),
        )
        .distinct()
    )
    for page_id, account_id in rows:
        found.setdefault(page_id, set()).add(account_id)
    return {page_id: frozenset(ids) for page_id, ids in found.items()}


# -- one page's advertising -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PageAdvertising:
    page: PageAccount | None = None
    sole: bool = False
    here: frozenset[str] = frozenset()
    elsewhere: frozenset[str] = frozenset()
    accounts: tuple[AdAccount, ...] = ()
    unplaced: int = 0
    pair_account: AdAccount | None = None
    first_pair: bool = True

    @property
    def campaign_ids(self) -> frozenset[str]:
        return self.here | self.elsewhere

    @property
    def home(self) -> AdAccount | None:
        return self.accounts[0] if self.accounts else None


Launches = list[tuple[uuid.UUID | None, uuid.UUID, tuple[str, ...]]]


def page_advertising(db: Session, *, owner: User) -> PageAdvertising:
    from app.modules.integrations.selectors import (
        active_ad_account,
        enabled_pages,
        page_shown,
        pair_on,
        stored_pairs,
    )

    pages = enabled_pages(db, owner=owner)
    page = page_shown(pages)
    if page is None:
        current = active_ad_account(db, owner=owner)
        return PageAdvertising(accounts=(current,) if current else ())
    pair = pair_on(stored_pairs(db, owner=owner, pages=pages), page)
    launches = _launches(db, owner=owner)
    return _advertising(
        db,
        owner=owner,
        page=page,
        sole=len(pages) == 1,
        launches=launches,
        placed=_placed_by_mirror(db, owner=owner, launches=launches, pages=pages),
        account=pair.account if pair is not None else None,
        first=pair is None or pair.first,
    )


def pages_advertising(db: Session, *, owner: User) -> tuple[PageAdvertising, ...]:
    from app.modules.integrations.selectors import enabled_pages, stored_pairs

    pages = enabled_pages(db, owner=owner)
    if not pages:
        return (page_advertising(db, owner=owner),)
    launches = _launches(db, owner=owner)
    sole = len(pages) == 1
    placed = _placed_by_mirror(db, owner=owner, launches=launches, pages=pages)
    pairs = stored_pairs(db, owner=owner, pages=pages)
    paired = {pair.page.id for pair in pairs}
    return tuple(
        _advertising(
            db,
            owner=owner,
            page=pair.page,
            sole=sole,
            launches=launches,
            placed=placed,
            account=pair.account,
            first=pair.first,
        )
        for pair in pairs
    ) + tuple(
        _advertising(db, owner=owner, page=page, sole=sole, launches=launches, placed=placed)
        for page in pages
        if page.id not in paired
    )


def _advertising(
    db: Session,
    *,
    owner: User,
    page: PageAccount,
    sole: bool,
    launches: Launches,
    placed: dict[str, uuid.UUID],
    account: AdAccount | None = None,
    first: bool = True,
) -> PageAdvertising:
    if account is not None:
        launches = [row for row in launches if row[1] == account.id]
    mine = []
    for page_id, account_id, campaigns in launches:
        if page_id == page.id or (sole and page_id is None):
            mine.append((account_id, campaigns))
        elif page_id is None:
            found = tuple(one for one in campaigns if placed.get(one) == page.id)
            if found:
                mine.append((account_id, found))
    here = frozenset(campaign for _account_id, ids in mine for campaign in ids)
    elsewhere, unplaced = _built_elsewhere(
        db,
        owner=owner,
        page=page,
        sole=sole,
        ours=frozenset(campaign for *_rest, ids in launches for campaign in ids),
        account=account,
    )
    if not sole:
        unplaced += sum(
            1
            for page_id, _account_id, ids in launches
            if page_id is None
            for campaign in ids
            if campaign not in placed
        )
    return PageAdvertising(
        page=page,
        sole=sole,
        here=here,
        elsewhere=elsewhere,
        unplaced=unplaced,
        accounts=(account,)
        if account is not None
        else paying_accounts(
            db,
            owner=owner,
            campaign_ids=here | elsewhere,
            launch_accounts={account_id for account_id, _ids in mine},
        ),
        pair_account=account,
        first_pair=first,
    )


def _placed_by_mirror(
    db: Session, *, owner: User, launches: Launches, pages: Sequence[PageAccount]
) -> dict[str, uuid.UUID]:
    unplaced = [
        campaign
        for page_id, _account_id, campaigns in launches
        if page_id is None
        for campaign in campaigns
    ]
    if not unplaced:
        return {}
    groups = list(
        db.execute(
            select(Campaign.external_id, AdSet.external_id)
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .where(AdSet.owner_id == owner.id, Campaign.external_id.in_(unplaced))
        ).all()
    )
    by_adset = pages_by_adset(db, owner=owner, adset_ids=[group for _c, group in groups])
    known = {page.external_id: page.id for page in pages}
    found: dict[str, uuid.UUID] = {}
    for campaign, group in groups:
        page = known.get(by_adset.get(group, ""))
        if page is not None and campaign not in found:
            found[campaign] = page
    return found


def _launches(db: Session, *, owner: User) -> Launches:
    return [
        (
            page_id,
            account_id,
            tuple(
                external_id
                for external_id in ref_field.ref_ids(created_refs or {}, LaunchStep.CAMPAIGN)
                if not is_dry_run_id(external_id)
            ),
        )
        for page_id, account_id, created_refs in db.execute(
            select(
                CampaignLaunch.page_id, CampaignLaunch.ad_account_id, CampaignLaunch.created_refs
            ).where(CampaignLaunch.owner_id == owner.id)
        )
    ]


def campaign_on_page(db: Session, *, owner: User, campaign: Campaign) -> bool:
    from app.modules.integrations.selectors import (
        enabled_pages,
        page_shown,
        pair_on,
        stored_pairs,
    )

    if campaign.provider != META:
        return False
    pages = enabled_pages(db, owner=owner)
    page = page_shown(pages)
    if page is None:
        return False
    sole = len(pages) == 1
    pair = pair_on(stored_pairs(db, owner=owner, pages=pages), page)
    if (
        pair is not None
        and campaign.ad_account_id is not None
        and campaign.ad_account_id != pair.account.id
    ):
        return False
    launch = campaign_launch(db, owner=owner, campaign_external_id=campaign.external_id)
    if launch is not None:
        return launch.page_id == page.id if launch.page_id is not None else sole
    groups = list(
        db.scalars(
            select(AdSet.external_id).where(
                AdSet.owner_id == owner.id, AdSet.campaign_id == campaign.id
            )
        )
    )
    found = pages_by_adset(db, owner=owner, adset_ids=groups)
    if any(found.get(group) == page.external_id for group in groups):
        return True
    return sole and (not groups or any(group not in found for group in groups))


def _built_elsewhere(
    db: Session,
    *,
    owner: User,
    page: PageAccount,
    sole: bool,
    ours: frozenset[str],
    account: AdAccount | None = None,
) -> tuple[frozenset[str], int]:
    on_account = true() if account is None else Campaign.ad_account_id == account.id
    rows = list(
        db.execute(
            select(AdSet.external_id, Campaign.external_id, AdSet.promoted_object_raw)
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .where(
                AdSet.owner_id == owner.id,
                AdSet.provider == META,
                on_account,
                Campaign.external_id != "",
                Campaign.external_id.not_in(ours),
            )
        ).all()
    )
    groups = [(group, campaign) for group, campaign, _ in rows]
    found = pages_by_promoted(
        db,
        owner=owner,
        promoted={group: promoted for group, _, promoted in rows},
        adset_ids=[group for group, _ in groups],
    )
    kept = {
        campaign
        for group, campaign in groups
        if found.get(group) == page.external_id or (sole and group not in found)
    }
    with_groups = select(AdSet.campaign_id).where(AdSet.owner_id == owner.id)
    groupless = list(
        db.scalars(
            select(Campaign.external_id).where(
                Campaign.owner_id == owner.id,
                Campaign.provider == META,
                on_account,
                Campaign.external_id != "",
                Campaign.external_id.not_in(ours),
                Campaign.id.not_in(with_groups),
            )
        )
    )
    if sole:
        kept.update(groupless)
        return frozenset(str(campaign) for campaign in kept), 0
    placed = {campaign for group, campaign in groups if group in found}
    unplaced = {campaign for _group, campaign in groups if campaign not in placed}
    paying = aliased(AdAccount)
    count = db.scalar(
        select(func.count(Campaign.id))
        .join(paying, paying.id == Campaign.ad_account_id)
        .where(
            Campaign.owner_id == owner.id,
            Campaign.provider == META,
            on_account,
            or_(paying.is_active.is_(True), _observed(paying)),
            or_(Campaign.external_id.in_(unplaced), Campaign.external_id.in_(groupless)),
        )
    )
    return frozenset(str(campaign) for campaign in kept), count or 0


def _observed(account: Any) -> Any:
    return and_(account.is_active.is_(False), account.leads_seen_at.is_not(None))


def page_accounts(db: Session, *, owner: User) -> tuple[AdAccount, ...]:
    from app.modules.integrations.selectors import active_ad_account

    paying = page_advertising(db, owner=owner).accounts
    current = active_ad_account(db, owner=owner)
    if current is None or not current.is_active or current in paying:
        return paying
    return (current, *paying)


# -- the page the cabinet is showing --------------------------------------------------


def page_scope(db: Session, *, owner: User) -> PageScope:
    groups, accounts, switched_off = _groups_of(db, owner=owner)
    pages, current, paired, current_account = _pages_of(db, owner=owner)
    found = pages_by_adset(
        db,
        owner=owner,
        adset_ids=[adset_id for adset_id in groups if adset_id not in switched_off],
    )
    launched = launch_pages(db, owner=owner)
    only = next(iter(pages)) if len(pages) == 1 else NO_PAGE
    page_of: dict[str, str] = {}
    guessed: set[str] = set()
    outside: set[str] = set(switched_off)
    for adset_id in groups:
        if adset_id in switched_off:
            continue
        page = launched.get(groups[adset_id], "") or found.get(adset_id, NO_PAGE)
        if page and page not in pages:
            outside.add(adset_id)
            continue
        if not page:
            guessed.add(adset_id)
        page = page or only or _sole_page_of(accounts.get(adset_id), paired)
        if not _paired(page, accounts.get(adset_id), paired):
            outside.add(adset_id)
            continue
        page_of[adset_id] = page
    campaign_of = {
        adset_id: campaign for adset_id, campaign in groups.items() if adset_id in page_of
    }
    kept = set(campaign_of.values())
    return PageScope(
        pages=pages,
        page_of=page_of,
        campaign_of=campaign_of,
        blocked=frozenset(campaign for campaign in groups.values() if campaign not in kept),
        outside=frozenset(outside),
        current=current,
        account_of={
            adset_id: account
            for adset_id, account in accounts.items()
            if adset_id in page_of and account
        },
        current_account=current_account,
        guessed=frozenset(guessed & page_of.keys()),
    )


def _paired(page: str, account: str | None, paired: dict[str, frozenset[str]]) -> bool:
    if not account:
        return True
    if page == NO_PAGE:
        return not paired or any(account in held for held in paired.values())
    held = paired.get(page)
    return held is None or account in held


def _sole_page_of(account: str | None, paired: dict[str, frozenset[str]]) -> str:
    if not account:
        return NO_PAGE
    pages = [page for page, held in paired.items() if account in held]
    return pages[0] if len(pages) == 1 else NO_PAGE


def _groups_of(
    db: Session, *, owner: User
) -> tuple[dict[str, str], dict[str, str], set[str]]:
    groups: dict[str, str] = {}
    accounts: dict[str, str] = {}
    switched_off: set[str] = set()
    rows = db.execute(
        select(
            AdSet.external_id,
            Campaign.external_id,
            AdAccount.external_id,
            AdAccount.is_active,
            AdAccount.leads_seen_at,
        )
        .join(Campaign, Campaign.id == AdSet.campaign_id)
        .outerjoin(AdAccount, AdAccount.id == Campaign.ad_account_id)
        .where(AdSet.owner_id == owner.id, AdSet.provider == META, Campaign.external_id != "")
    )
    for adset_id, campaign, account, active, seen in rows:
        groups[adset_id] = campaign
        accounts[adset_id] = account or ""
        if active is False and seen is None:
            switched_off.add(adset_id)
    return groups, accounts, switched_off


def _pages_of(
    db: Session, *, owner: User
) -> tuple[dict[str, str], str, dict[str, frozenset[str]], str]:
    from app.modules.integrations.selectors import (
        enabled_pages,
        page_shown,
        pair_on,
        pairs_by_page,
        stored_pairs,
    )

    shown = enabled_pages(db, owner=owner)
    pairs = stored_pairs(db, owner=owner, pages=shown)
    pages = {page.external_id: page.name or page.external_id for page in shown}
    page = page_shown(shown)
    pair = pair_on(pairs, page)
    return (
        pages,
        page.external_id if page is not None else "",
        pairs_by_page(pairs),
        pair.account.external_id if pair is not None else "",
    )


def current_page_scope(db: Session, *, owner: User) -> PageScope:
    whole = page_scope(db, owner=owner)
    return whole.only(whole.current, whole.current_account)
