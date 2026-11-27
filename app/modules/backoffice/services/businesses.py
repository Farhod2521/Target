"""What the office does to one business of a customer's, each on its own.

A business is one page and ad account pair with what hangs on it: the
knowledge the AI reads, the pair's CRM, the accounts on other networks,
the people who work in it, and the page's place in the subscription. Each
part is taken away by its own press, so that support removes what is wrong
and nothing beside it; deleting the business is all of them at once.

Nothing here reaches the advertising network: the adverts a business ran
stay where they are.
"""

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session

from app.common import tokens
from app.common.db import on_commit, utcnow
from app.common.deletion import ProtectedRows, delete_rows
from app.modules.accounts.models import User
from app.modules.backoffice.constants import ActionKind
from app.modules.backoffice.exceptions import (
    BusinessEmailMismatch,
    BusinessHasNoPage,
    BusinessHasNoPair,
    BusinessLeadsHeld,
    UnknownCustomerBusiness,
)
from app.modules.backoffice.services.journal import record
from app.modules.businesses.constants import LinkKind
from app.modules.businesses.models import (
    Business,
    BusinessKnowledge,
    BusinessLink,
    BusinessMember,
)
from app.modules.businesses.selectors.access import works_elsewhere
from app.modules.businesses.services import knowledge, networks
from app.modules.businesses.services import members as member_services
from app.modules.crm.models import (
    CrmCard,
    CrmLostReason,
    CrmMember,
    CrmSetup,
    CrmStage,
)
from app.modules.crm.selectors import Scope
from app.modules.integrations.models import PageAccount, PagePair
from app.modules.leads.constants import MANUAL_PROVIDER, SignalSource, SignalStatus
from app.modules.leads.models import Lead, LeadSignal

META = "meta"


def business_of(db: Session, *, customer: User, business_id: uuid.UUID) -> Business:
    business = db.get(Business, business_id)
    if business is None or business.user_id != customer.id:
        raise UnknownCustomerBusiness
    return business


def links_of(db: Session, business: Business) -> list[BusinessLink]:
    return list(
        db.scalars(
            select(BusinessLink)
            .where(
                BusinessLink.business_id == business.id,
                BusinessLink.unbound_at.is_(None),
            )
            .order_by(BusinessLink.bound_at, BusinessLink.id)
        )
    )


def pair_of(db: Session, business: Business) -> BusinessLink | None:
    """The business's page and ad account pair, while it has one."""
    return next(
        (
            link
            for link in links_of(db, business)
            if link.kind == LinkKind.META_PAIR
            and link.page_id is not None
            and link.ad_account_id is not None
        ),
        None,
    )


def page_of(db: Session, business: Business) -> PageAccount | None:
    """The page whose place in the subscription is the business's."""
    pair = pair_of(db, business)
    page_id = pair.page_id if pair is not None else business.page_id
    return db.get(PageAccount, page_id) if page_id is not None else None


# -- the knowledge the AI wrote ---------------------------------------------------------


def clear_ai_knowledge(
    db: Session, *, customer: User, business: Business, actor: User, reason: str
) -> dict[str, int]:
    gone = knowledge.clear_ai(db, business=business, actor=actor)
    record(
        db,
        customer=customer,
        actor=actor,
        kind=ActionKind.BUSINESS_AI_CLEARED,
        reason=reason,
        detail={"business": str(business.id), "name": business.name, **gone},
    )
    return gone


# -- the CRM of the business's pair -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class CrmGone:
    cards: int = 0
    stages: int = 0
    reasons: int = 0
    managers: int = 0
    logins_closed: int = 0
    manual_leads: int = 0


def _count(db: Session, model: Any, scope: Scope) -> int:
    return int(
        db.scalar(select(func.count()).select_from(model).where(scope.holds(model)))
        or 0
    )


def _erase_crm(db: Session, *, customer: User, scope: Scope) -> CrmGone:
    """One pair's CRM, gone as if it was never set up: cards with their
    history, columns, lost reasons, the setup and its managers. The leads
    stay, and so do the seats bought and every other pair's CRM. A manager
    who works nowhere else of the owner's loses the login."""
    from app.modules.accounts.services import remove_member_login

    # Taking the setup first holds ``place_lead`` off, which locks it
    # before it lays a card.
    list(db.scalars(select(CrmSetup.id).where(scope.holds(CrmSetup)).with_for_update()))
    rows = list(db.scalars(select(CrmMember).where(scope.holds(CrmMember))))
    people = {row.user_id: row.id for row in rows}
    carded = select(CrmCard.lead_id).where(scope.holds(CrmCard))
    db.execute(
        update(LeadSignal)
        .where(
            LeadSignal.owner_id == customer.id,
            LeadSignal.lead_id.in_(carded),
            LeadSignal.source == SignalSource.INTERNAL,
            LeadSignal.status == SignalStatus.PENDING,
        )
        .values(status=SignalStatus.WITHDRAWN, updated_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    # The customers typed in by hand lived only on this board.
    typed = list(
        db.scalars(
            select(Lead.id).where(
                Lead.owner_id == customer.id,
                Lead.provider == MANUAL_PROVIDER,
                Lead.id.in_(carded),
            )
        )
    )
    counts = {
        "cards": _count(db, CrmCard, scope),
        "stages": _count(db, CrmStage, scope),
        "reasons": _count(db, CrmLostReason, scope),
        "managers": len(rows),
    }
    for row in rows:
        db.expunge(row)
    for model in (CrmCard, CrmStage, CrmLostReason, CrmMember, CrmSetup):
        delete_rows(db, model.__table__, scope.holds(model))
    if typed:
        delete_rows(db, Lead.__table__, Lead.id.in_(typed))
    db.expire_all()
    # The memberships that stood for those managers follow them out.
    member_services.mirror_crm_members(db, owner_id=customer.id)
    closed: list[str] = []
    for user_id in people:
        if works_elsewhere(db, user_id=user_id):
            continue
        login = db.get(User, user_id)
        if login is not None and login.crm_owner_id == customer.id:
            closed.append(str(login.id))
            remove_member_login(db, user=login)

    def sign_out() -> None:
        for subject in closed:
            tokens.revoke_all(subject=subject, now=utcnow())

    on_commit(db, sign_out)
    return CrmGone(**counts, logins_closed=len(closed), manual_leads=len(typed))


def erase_business_crm(
    db: Session, *, customer: User, business: Business, actor: User, reason: str
) -> CrmGone:
    """The owner sets the CRM up again from its first step afterwards."""
    pair = pair_of(db, business)
    if pair is None or pair.page_id is None or pair.ad_account_id is None:
        raise BusinessHasNoPair
    gone = _erase_crm(
        db,
        customer=customer,
        scope=Scope(
            owner_id=customer.id,
            page_id=pair.page_id,
            ad_account_id=pair.ad_account_id,
        ),
    )
    record(
        db,
        customer=customer,
        actor=actor,
        kind=ActionKind.BUSINESS_CRM_ERASED,
        reason=reason,
        detail={"business": str(business.id), "name": business.name, **asdict(gone)},
    )
    return gone


# -- the networks it advertises on ------------------------------------------------------


def _remove_pair(
    db: Session, *, customer: User, pair: BusinessLink, actor: User
) -> dict[str, str]:
    from app.modules.integrations.models import AdAccount
    from app.modules.integrations.services.cabinet import remove_page_pair

    page = db.get(PageAccount, pair.page_id)
    account = db.get(AdAccount, pair.ad_account_id)
    if page is None or account is None:
        raise BusinessHasNoPair
    remove_page_pair(
        db,
        owner=customer,
        page_external_id=page.external_id,
        account_external_id=account.external_id,
        actor=actor,
    )
    return {"page": page.external_id, "account": account.external_id}


def remove_network(
    db: Session,
    *,
    customer: User,
    business: Business,
    provider: str,
    actor: User,
    reason: str,
) -> dict[str, str]:
    """Untie one network from the business. For Meta that is the page and
    ad account pair: the page and the account stay connected, and the
    pair's CRM and leads stay in the database. Another network's account
    stays the owner's, tied to no business."""
    if provider == META:
        pair = pair_of(db, business)
        if pair is None:
            raise BusinessHasNoPair
        detail = _remove_pair(db, customer=customer, pair=pair, actor=actor)
    else:
        link = networks.unbind(db, business=business, provider=provider)
        detail = {"account": link.external_id}
    record(
        db,
        customer=customer,
        actor=actor,
        kind=ActionKind.BUSINESS_NETWORK_REMOVED,
        reason=reason,
        detail={
            "business": str(business.id),
            "name": business.name,
            "provider": provider,
            **detail,
        },
    )
    return detail


# -- the page's place in the subscription -----------------------------------------------


def _page(db: Session, business: Business) -> PageAccount:
    page = page_of(db, business)
    if page is None:
        raise BusinessHasNoPage
    return page


def subscribe(
    db: Session, *, customer: User, business: Business, actor: User, reason: str
) -> PageAccount:
    """Switch the business's page on in a free place of the subscription.
    Refused when there is none: a place past the plan is given by the
    page's own «add» press, which may take money."""
    from app.modules.integrations.services.cabinet import enable_page

    page = _page(db, business)
    enable_page(db, user=customer, external_id=page.external_id)
    record(
        db,
        customer=customer,
        actor=actor,
        kind=ActionKind.BUSINESS_SUBSCRIBED,
        reason=reason,
        detail={
            "business": str(business.id),
            "name": business.name,
            "page": page.external_id,
        },
    )
    return page


def unsubscribe(
    db: Session,
    *,
    customer: User,
    business: Business,
    actor: User,
    reason: str,
    now: datetime,
) -> PageAccount:
    """Take the business's page out of the subscription; its place is free
    for another. Nothing the business collected is lost."""
    from app.modules.integrations.services.cabinet import release_page

    page = _page(db, business)
    release_page(db, page=page, actor=actor, now=now)
    record(
        db,
        customer=customer,
        actor=actor,
        kind=ActionKind.BUSINESS_UNSUBSCRIBED,
        reason=reason,
        detail={
            "business": str(business.id),
            "name": business.name,
            "page": page.external_id,
        },
    )
    return page


def move_place(
    db: Session,
    *,
    customer: User,
    business: Business,
    target: Business,
    actor: User,
    reason: str,
    now: datetime,
) -> PageAccount:
    """Hand this business's place in the subscription to another business
    of the customer's; nothing either collected moves."""
    from app.modules.integrations.services.cabinet import swap_page

    source, to = _page(db, business), _page(db, target)
    swap_page(db, source=source, target=to, actor=actor, now=now)
    record(
        db,
        customer=customer,
        actor=actor,
        kind=ActionKind.BUSINESS_SLOT_MOVED,
        reason=reason,
        detail={
            "from": str(business.id),
            "from_name": business.name,
            "to": str(target.id),
            "to_name": target.name,
        },
    )
    return to


# -- the whole of it --------------------------------------------------------------------


def delete_business(
    db: Session,
    *,
    customer: User,
    business: Business,
    actor: User,
    typed_email: str,
    reason: str,
    with_leads: bool,
    now: datetime,
) -> dict[str, Any]:
    """Everything of one business: its CRM, the networks tied to it, its
    people, what is known of it, its page's place in the subscription and
    the business itself. The page and the ad account stay connected, to be
    paired again as a new business. Its leads stay unless ``with_leads``.

    The customer's address has to be typed back: nothing brings it back.
    """
    from app.modules.accounts.services import remove_member_login
    from app.modules.integrations.services.cabinet import release_page

    if typed_email.strip().lower() != customer.email.lower():
        raise BusinessEmailMismatch
    business_id, name = business.id, business.name
    worked = int(
        db.scalar(
            select(func.count())
            .select_from(BusinessMember)
            .where(
                BusinessMember.business_id == business_id,
                BusinessMember.is_active.is_(True),
            )
        )
        or 0
    )
    pair = pair_of(db, business)
    page = page_of(db, business)
    crm = CrmGone()
    if pair is not None and pair.page_id and pair.ad_account_id:
        crm = _erase_crm(
            db,
            customer=customer,
            scope=Scope(
                owner_id=customer.id,
                page_id=pair.page_id,
                ad_account_id=pair.ad_account_id,
            ),
        )
        business = business_of(db, customer=customer, business_id=business_id)
    untied = []
    for link in links_of(db, business):
        if link.kind == LinkKind.AD_ACCOUNT:
            networks.unbind(db, business=business, provider=link.provider, now=now)
            untied.append(link.provider)
    people = [
        member
        for member in db.scalars(
            select(BusinessMember).where(
                BusinessMember.business_id == business_id,
                BusinessMember.is_active.is_(True),
            )
        )
    ]
    closed: list[str] = []
    for member in people:
        user_id = member.user_id
        member_services.remove_member(db, member=member, now=now)
        if works_elsewhere(db, user_id=user_id):
            continue
        login = db.get(User, user_id)
        if login is not None and login.crm_owner_id == customer.id:
            closed.append(str(login.id))
            remove_member_login(db, user=login)
    pair = pair_of(db, business)
    if pair is not None:
        _remove_pair(db, customer=customer, pair=pair, actor=actor)
        untied.append(META)
    released = False
    if page is not None:
        db.refresh(page)
        paired_still = db.scalar(
            select(PagePair.id).where(PagePair.page_id == page.id).limit(1)
        )
        if page.is_active and paired_still is None:
            release_page(db, page=page, actor=actor, now=now)
            released = True
    leads = 0
    if with_leads:
        mine = and_(Lead.owner_id == customer.id, Lead.business_id == business_id)
        leads = int(db.scalar(select(func.count()).select_from(Lead).where(mine)) or 0)
        try:
            delete_rows(db, Lead.__table__, mine)
        except ProtectedRows:
            raise BusinessLeadsHeld from None
    knew = db.scalar(
        select(func.count())
        .select_from(BusinessKnowledge)
        .where(BusinessKnowledge.business_id == business_id)
    )
    db.flush()
    db.expire_all()
    delete_rows(db, Business.__table__, Business.id == business_id)

    def sign_out() -> None:
        for subject in closed:
            tokens.revoke_all(subject=subject, now=utcnow())

    on_commit(db, sign_out)
    detail: dict[str, Any] = {
        "business": str(business_id),
        "name": name,
        "networks": untied,
        "members": worked,
        "logins_closed": len(closed) + crm.logins_closed,
        "knowledge": bool(knew),
        "page_released": released,
        "leads": leads,
        "crm": asdict(crm),
    }
    record(
        db,
        customer=customer,
        actor=actor,
        kind=ActionKind.BUSINESS_DELETED,
        reason=reason,
        detail=detail,
    )
    return detail


__all__ = [
    "BusinessHasNoPair",
    "CrmGone",
    "business_of",
    "clear_ai_knowledge",
    "delete_business",
    "erase_business_crm",
    "links_of",
    "move_place",
    "page_of",
    "pair_of",
    "remove_network",
    "subscribe",
    "unsubscribe",
]
