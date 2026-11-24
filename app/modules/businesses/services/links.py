"""Which business each page and ad account pair is.

A business is the row the owner's profile lives in. Its pair is written in
``business_links``, read from the stored pairs and never the other way: the
pairs stay what the cabinet writes, and :func:`sync_links` brings the links
level with them. It may be run any number of times.

- a pair whose page has a profile is that profile's business;
- a second pair on the same page is a business of its own, opened with a
  copy of the page's profile. Its row carries the ad account instead of the
  page, which is what keeps it out of every read that asks for a page's
  profile;
- a pair whose account was changed stays the same business: the old link is
  closed and a new one opened;
- a removed pair closes its link; the business and its rows stay;
- a pair whose page has no profile yet waits. Nothing is made for it, since
  a profile row on the page would stop the cabinet falling back to the
  owner's first one.

:func:`fill_rows` then writes the business beside the pair on the rows that
name one, and only where it is still empty.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from metaads import PROVIDER
from sqlalchemy import ColumnElement, Table, and_, exists, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.businesses.constants import LinkKind
from app.modules.businesses.models import Business, BusinessLink
from app.modules.integrations.models import AdAccount, PageAccount, PagePair

logger = logging.getLogger(__name__)

# What a second pair's business starts with: the page's profile as it reads
# on the day the pair is found.
PROFILE_COPIED = (
    "name",
    "category",
    "direction_id",
    "custom_category_id",
    "timezone",
    "country_code",
    "city",
    "lat",
    "lng",
    "contact_phone",
    "website",
    "offer_text",
    "working_hours",
    "locales",
    "special_ad_category",
    "audience_gender",
    "regions",
)


@dataclass
class Synced:
    kept: int = 0
    bound: int = 0
    opened: int = 0
    moved: int = 0
    closed: int = 0
    waiting: int = 0
    blocked: int = 0

    def add(self, other: "Synced") -> None:
        for name in vars(self):
            setattr(self, name, getattr(self, name) + getattr(other, name))

    @property
    def changed(self) -> int:
        return self.bound + self.opened + self.moved + self.closed


def pair_external_id(page: PageAccount, account: AdAccount) -> str:
    return f"{page.external_id}:{account.external_id}"


def _open_pairs() -> ColumnElement[bool]:
    return and_(
        BusinessLink.provider == PROVIDER,
        BusinessLink.kind == LinkKind.META_PAIR,
        BusinessLink.unbound_at.is_(None),
    )


def sync_links(
    db: Session, *, owner_id: uuid.UUID, now: datetime | None = None
) -> Synced:
    """Bring one owner's links level with their stored pairs; flushes."""
    now = now or utcnow()
    done = Synced()
    wanted = {
        (pair.page_id, pair.ad_account_id): (page, account)
        for pair, page, account in db.execute(
            select(PagePair, PageAccount, AdAccount)
            .join(PageAccount, PageAccount.id == PagePair.page_id)
            .join(AdAccount, AdAccount.id == PagePair.ad_account_id)
            .where(PagePair.owner_id == owner_id)
            .order_by(PagePair.created_at, PagePair.id)
        )
    }
    held = {
        (link.page_id, link.ad_account_id): link
        for link in db.scalars(
            select(BusinessLink)
            .where(BusinessLink.owner_id == owner_id, _open_pairs())
            .order_by(BusinessLink.bound_at, BusinessLink.id)
            .with_for_update()
        )
    }
    stale = [link for key, link in held.items() if key not in wanted]
    taken = {link.business_id for link in held.values()}
    done.kept = len(held) - len(stale)
    for key, (page, account) in wanted.items():
        if key in held:
            continue
        old = next((link for link in stale if link.page_id == page.id), None)
        if old is not None:
            stale.remove(old)
            business_id = _move(db, link=old, account=account, now=now)
            done.moved += 1
        else:
            found = _business_for(
                db, owner_id=owner_id, page=page, account=account, taken=taken
            )
            if found is None:
                done.waiting += 1
                continue
            if found == "blocked":
                done.blocked += 1
                continue
            business_id, opened = found
            done.opened += opened
            done.bound += not opened
        taken.add(business_id)
        db.add(
            BusinessLink(
                business_id=business_id,
                owner_id=owner_id,
                provider=PROVIDER,
                kind=LinkKind.META_PAIR,
                page_id=page.id,
                ad_account_id=account.id,
                external_id=pair_external_id(page, account),
                bound_at=now,
            )
        )
        db.flush()
    for link in stale:
        link.unbound_at = now
        done.closed += 1
    db.flush()
    return done


def _move(
    db: Session, *, link: BusinessLink, account: AdAccount, now: datetime
) -> uuid.UUID:
    """Close the link on the account the pair left. A second pair's business
    is keyed by its account, so that follows where no other row holds it."""
    business = link.business
    link.unbound_at = now
    if (
        business.page_id is None
        and business.ad_account_id == link.ad_account_id
        and not _keyed(db, account)
    ):
        business.ad_account_id = account.id
    db.flush()
    return business.id


def _keyed(db: Session, account: AdAccount) -> bool:
    return bool(db.scalar(select(exists().where(Business.ad_account_id == account.id))))


def _business_for(
    db: Session,
    *,
    owner_id: uuid.UUID,
    page: PageAccount,
    account: AdAccount,
    taken: set[uuid.UUID],
) -> tuple[uuid.UUID, bool] | str | None:
    profile = db.scalar(
        select(Business).where(
            Business.user_id == owner_id,
            Business.page_id == page.id,
            Business.ad_account_id.is_(None),
        )
    )
    if profile is None:
        return None
    if profile.id not in taken:
        return profile.id, False
    if _keyed(db, account):
        # The account already keys another business (a second pair on
        # another page); the unique key leaves no row for this one.
        return "blocked"
    business = Business(
        user_id=owner_id,
        ad_account_id=account.id,
        **{name: getattr(profile, name) for name in PROFILE_COPIED},
    )
    db.add(business)
    db.flush()
    return business.id, True


def _pair_rows() -> tuple[Table, ...]:
    from app.modules.ads.models import CampaignLaunch
    from app.modules.chat.models import ChatSession
    from app.modules.crm.models import (
        CrmCard,
        CrmLostReason,
        CrmMember,
        CrmSetup,
        CrmStage,
    )

    return tuple(
        model.__table__
        for model in (
            CrmStage,
            CrmLostReason,
            CrmCard,
            CrmMember,
            CrmSetup,
            ChatSession,
            CampaignLaunch,
        )
    )


def _sole_pages() -> Any:
    """Pages with one open pair: a row that names such a page alone, or with
    an account the pair has since left, can only be that business's."""
    return (
        select(BusinessLink.page_id)
        .where(_open_pairs(), BusinessLink.page_id.is_not(None))
        .group_by(BusinessLink.page_id)
        .having(func.count() == 1)
    )


def fill_rows(db: Session, *, owner_id: uuid.UUID | None = None) -> dict[str, int]:
    """Write the business on rows that name a pair and have none yet."""
    from app.modules.crm.models import CrmCard
    from app.modules.leads.models import Lead, LeadForm

    filled: dict[str, int] = {}
    for table in _pair_rows():
        mine = (table.c.owner_id == owner_id,) if owner_id is not None else ()
        exact = (
            select(BusinessLink.business_id)
            .where(
                _open_pairs(),
                BusinessLink.page_id == table.c.page_id,
                BusinessLink.ad_account_id == table.c.ad_account_id,
            )
            .limit(1)
            .scalar_subquery()
        )
        count = db.execute(
            update(table)
            .where(table.c.business_id.is_(None), exact.is_not(None), *mine)
            .values(business_id=exact)
        ).rowcount
        by_page = (
            select(BusinessLink.business_id)
            .where(_open_pairs(), BusinessLink.page_id == table.c.page_id)
            .limit(1)
            .scalar_subquery()
        )
        count += db.execute(
            update(table)
            .where(
                table.c.business_id.is_(None),
                table.c.page_id.in_(_sole_pages()),
                *mine,
            )
            .values(business_id=by_page)
        ).rowcount
        filled[table.name] = count
    leads = Lead.__table__
    mine = (leads.c.owner_id == owner_id,) if owner_id is not None else ()
    from_card = (
        select(CrmCard.business_id)
        .where(CrmCard.lead_id == leads.c.id, CrmCard.business_id.is_not(None))
        .limit(1)
        .scalar_subquery()
    )
    count = db.execute(
        update(leads)
        .where(leads.c.business_id.is_(None), from_card.is_not(None), *mine)
        .values(business_id=from_card)
    ).rowcount
    from_form = (
        select(BusinessLink.business_id)
        .join(LeadForm, LeadForm.page_id == BusinessLink.page_id)
        .where(_open_pairs(), LeadForm.id == leads.c.form_id)
        .limit(1)
        .scalar_subquery()
    )
    count += db.execute(
        update(leads)
        .where(
            leads.c.business_id.is_(None),
            leads.c.form_id.in_(
                select(LeadForm.id).where(LeadForm.page_id.in_(_sole_pages()))
            ),
            *mine,
        )
        .values(business_id=from_form)
    ).rowcount
    filled[leads.name] = count
    db.flush()
    return filled


def business_of_pair(
    db: Session, *, page_id: uuid.UUID | None, ad_account_id: uuid.UUID | None
) -> uuid.UUID | None:
    """The business a pair is, or the page's only one when the account is
    not (or no longer) its pair's."""
    if page_id is None:
        return None
    links = list(
        db.execute(
            select(BusinessLink.business_id, BusinessLink.ad_account_id).where(
                _open_pairs(), BusinessLink.page_id == page_id
            )
        )
    )
    for business_id, account_id in links:
        if account_id == ad_account_id:
            return business_id
    return links[0][0] if len(links) == 1 else None


def settle(db: Session, *, owner_id: uuid.UUID) -> Synced | None:
    """Links level with the pairs, and the business on the rows a new link
    now reaches, for an owner whose pairs or profile just changed.

    Runs inside the caller's transaction, behind a savepoint: whatever goes
    wrong here is logged and undone, and the caller's own writes commit as
    if this had not been asked for. The next change, or the backfill, does
    the work again.
    """
    try:
        with db.begin_nested():
            done = sync_links(db, owner_id=owner_id)
            if done.changed:
                fill_rows(db, owner_id=owner_id)
            return done
    except SQLAlchemyError:
        logger.exception("business links not settled", extra={"owner": str(owner_id)})
        return None
