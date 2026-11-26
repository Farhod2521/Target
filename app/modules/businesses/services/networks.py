"""The other networks a business advertises on.

A business starts as a Meta pair, and that pair is read from the cabinet's
stored pairs (``links.sync_links``). Any other network is tied on here, by
the owner: one of their accounts on that network becomes the business's.

- a business holds one account of a network, and an account is one
  business's; the database's two unique indexes say so, and the refusals
  below say it in words first;
- a member is given, on the new network, what they hold on the business's
  other networks: the lowest of those levels, and nothing where one of them
  is closed to them. The owner may change it afterwards;
- untying closes the link, which stays as the record of what the business
  ran from; the grants over that network are taken back;
- the leads the account brought are written onto the business.
"""

import uuid
from datetime import datetime

from metaads import PROVIDER as META
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.audit.constants import EventName
from app.modules.audit.services.emit import emit
from app.modules.businesses.constants import GrantArea, GrantLevel, LinkKind
from app.modules.businesses.exceptions import (
    AccountBound,
    AccountNotInUse,
    MetaIsPair,
    NetworkTaken,
    NoPairForCrm,
    UnknownAccount,
    UnknownNetwork,
)
from app.modules.businesses.models import (
    Business,
    BusinessLink,
    BusinessMember,
    BusinessMemberGrant,
)
from app.modules.integrations.models import AdAccount

_RANK = {GrantLevel.VIEW.value: 1, GrantLevel.EDIT.value: 2}


def _open(business_id: uuid.UUID):  # type: ignore[no-untyped-def]
    return select(BusinessLink).where(
        BusinessLink.business_id == business_id, BusinessLink.unbound_at.is_(None)
    )


def available(db: Session, *, business: Business) -> list[AdAccount]:
    """The owner's accounts that may be tied to this business now: in use,
    on a network the business has none on, and no other business's."""
    held = {link.provider for link in db.scalars(_open(business.id))}
    bound = select(BusinessLink.ad_account_id).where(
        BusinessLink.kind == LinkKind.AD_ACCOUNT,
        BusinessLink.unbound_at.is_(None),
        BusinessLink.ad_account_id.is_not(None),
    )
    return list(
        db.scalars(
            select(AdAccount)
            .where(
                AdAccount.owner_id == business.user_id,
                AdAccount.provider.not_in({META, *held}),
                or_(AdAccount.is_active.is_(True), AdAccount.is_current.is_(True)),
                AdAccount.id.not_in(bound),
            )
            .order_by(AdAccount.provider, AdAccount.name, AdAccount.id)
        )
    )


def _inherit(db: Session, *, business: Business, provider: str) -> None:
    """Each member's standing on the business's other networks, carried to
    the new one."""
    others = sorted(
        {link.provider for link in db.scalars(_open(business.id))} - {provider}
    )
    if not others:
        return
    for member in db.scalars(
        select(BusinessMember).where(
            BusinessMember.business_id == business.id,
            BusinessMember.is_active.is_(True),
        )
    ):
        held = {(grant.area, grant.provider): grant.level for grant in member.grants}
        for area in GrantArea.values:
            if (area, provider) in held:
                continue
            levels = [held.get((area, other)) for other in others]
            if any(level is None for level in levels):
                continue
            member.grants.append(
                BusinessMemberGrant(
                    area=area,
                    provider=provider,
                    level=min(levels, key=lambda level: _RANK[level]),  # type: ignore[index]
                )
            )


def bind(
    db: Session,
    *,
    business: Business,
    account_id: uuid.UUID,
    now: datetime | None = None,
) -> BusinessLink:
    """Tie one of the owner's accounts to the business; flushes."""
    from app.modules.businesses.services.links import fill_network_leads

    now = now or utcnow()
    account = db.scalar(
        select(AdAccount).where(
            AdAccount.id == account_id, AdAccount.owner_id == business.user_id
        )
    )
    if account is None:
        raise UnknownAccount
    if account.provider == META:
        raise MetaIsPair
    if not (account.is_active or account.is_current):
        raise AccountNotInUse
    links = list(db.scalars(_open(business.id).with_for_update()))
    if not any(link.kind == LinkKind.META_PAIR for link in links):
        raise NoPairForCrm
    if any(link.provider == account.provider for link in links):
        raise NetworkTaken
    taken = db.scalar(
        select(BusinessLink.id).where(
            BusinessLink.provider == account.provider,
            BusinessLink.kind == LinkKind.AD_ACCOUNT,
            BusinessLink.external_id == account.external_id,
            BusinessLink.unbound_at.is_(None),
        )
    )
    if taken is not None:
        raise AccountBound
    link = BusinessLink(
        business_id=business.id,
        owner_id=business.user_id,
        provider=account.provider,
        kind=LinkKind.AD_ACCOUNT,
        ad_account_id=account.id,
        external_id=account.external_id,
        bound_at=now,
    )
    try:
        with db.begin_nested():
            db.add(link)
    except IntegrityError:
        # Tied by another request between the look and the write.
        raise AccountBound from None
    _inherit(db, business=business, provider=account.provider)
    db.flush()
    fill_network_leads(db, link=link)
    emit(
        db,
        owner_id=business.user_id,
        name=EventName.BUSINESS_NETWORK_BOUND,
        aggregate_type="business",
        aggregate_id=business.id,
        payload={
            "provider": account.provider,
            "ad_account": str(account.id),
            "external_id": account.external_id,
            "name": account.name,
        },
        occurred_at=now,
    )
    return link


def unbind(
    db: Session, *, business: Business, provider: str, now: datetime | None = None
) -> BusinessLink:
    """Untie the business's account on a network; flushes."""
    now = now or utcnow()
    if provider == META:
        raise MetaIsPair
    link = db.scalar(
        _open(business.id)
        .where(
            BusinessLink.provider == provider, BusinessLink.kind == LinkKind.AD_ACCOUNT
        )
        .with_for_update()
    )
    if link is None:
        raise UnknownNetwork
    link.unbound_at = now
    for member in db.scalars(
        select(BusinessMember).where(BusinessMember.business_id == business.id)
    ):
        for grant in [one for one in member.grants if one.provider == provider]:
            member.grants.remove(grant)
    db.flush()
    account = link.ad_account
    emit(
        db,
        owner_id=business.user_id,
        name=EventName.BUSINESS_NETWORK_UNBOUND,
        aggregate_type="business",
        aggregate_id=business.id,
        payload={
            "provider": provider,
            "ad_account": str(link.ad_account_id or ""),
            "external_id": link.external_id,
            "name": account.name if account is not None else "",
        },
        occurred_at=now,
    )
    return link
