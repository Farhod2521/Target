"""One business of a customer's, from their card: what it is made of, and
each part taken away on its own.

Every write names its reason, which goes to the journal, and answers the
sentence that says what happened. Nothing here touches the advertising
network: the adverts a business ran stay there.
"""

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import Db
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import ADMIN_ROLES, ActionKind, Role
from app.modules.backoffice.permissions import staff_required
from app.modules.backoffice.schemas import MessageOut
from app.modules.backoffice.selectors.card import person
from app.modules.backoffice.services import businesses as services
from app.modules.backoffice.services.journal import record
from app.modules.businesses.constants import TypeState
from app.modules.businesses.models import Business, BusinessLink, BusinessMember
from app.modules.businesses.services import knowledge
from app.modules.crm import services as crm
from app.modules.crm.constants import SetupState
from app.modules.crm.models import CrmCard, CrmSetup
from app.modules.crm.selectors import Scope, office_viewer

router = APIRouter(prefix="/customers/{customer_id}/businesses", tags=["office"])
Admin = Annotated[User, Depends(staff_required(*ADMIN_ROLES))]
Owner = Annotated[User, Depends(staff_required(Role.OWNER))]


class ReasonIn(BaseModel):
    reason: str = Field(
        min_length=1, max_length=500, description="Why - it goes to the journal."
    )


class CrmStateIn(ReasonIn):
    on: bool = Field(description="`true` starts the board, `false` stops it.")


class MoveIn(ReasonIn):
    target: uuid.UUID = Field(
        description="The business that takes this one's place in the subscription."
    )


class DeleteIn(ReasonIn):
    email: str = Field(description="The customer's address, typed back.")
    with_leads: bool = Field(
        False,
        description="Delete the business's leads too. Left out, they stay in "
        "the database, tied to no business.",
    )


class OfficePageOut(BaseModel):
    id: uuid.UUID
    external_id: str
    name: str
    # Whether the page holds a place in the subscription.
    subscribed: bool


class OfficeNetworkOut(BaseModel):
    provider: str
    kind: Literal["meta_pair", "ad_account"]
    # What the network calls it: `page:account` for Meta, the account's id.
    external_id: str
    name: str


class OfficeCrmOut(BaseModel):
    # `none`: never set up. `draft`: being set up. `on` / `off`.
    state: Literal["none", "draft", "on", "off"]
    cards: int


class OfficeKnowledgeOut(BaseModel):
    kind_state: Literal["unset", "guessed", "confirmed"]
    # Pieces the AI wrote, which «clear» takes out: the description, things
    # sold and facts; `pending` is what still waits for the owner's yes.
    by_ai: int
    by_people: int
    pending: int


class OfficeBusinessOut(BaseModel):
    id: uuid.UUID
    name: str
    # The key the CRM's own office routes take as `?pair=`; empty with no pair.
    pair: str
    page: OfficePageOut | None
    networks: list[OfficeNetworkOut]
    members: int
    crm: OfficeCrmOut
    knowledge: OfficeKnowledgeOut


class OfficeBusinessesOut(BaseModel):
    businesses: list[OfficeBusinessOut]


def _customer(db: Db, customer_id: uuid.UUID) -> User:
    customer = person(db, customer_id=customer_id)
    if customer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return customer


def _knowledge_out(db: Db, business: Business) -> OfficeKnowledgeOut:
    row = knowledge.row_of(db, business)
    document = knowledge.document_of(row)
    pieces = [
        *([document["about"]] if document.get("about") else []),
        *(document.get("items") or []),
        *(document.get("facts") or {}).values(),
    ]
    by_ai = sum(
        1 for piece in pieces if str(piece.get("src") or "") in knowledge.AI_SOURCES
    )
    return OfficeKnowledgeOut(
        kind_state=row.type_state if row is not None else TypeState.UNSET.value,  # type: ignore[arg-type]
        by_ai=by_ai,
        by_people=len(pieces) - by_ai,
        pending=len(document.get("pending") or []),
    )


def _crm_out(db: Db, customer: User, pair: BusinessLink | None) -> OfficeCrmOut:
    if pair is None or pair.page_id is None or pair.ad_account_id is None:
        return OfficeCrmOut(state="none", cards=0)
    scope = Scope(
        owner_id=customer.id, page_id=pair.page_id, ad_account_id=pair.ad_account_id
    )
    setup = db.scalar(select(CrmSetup).where(scope.holds(CrmSetup)))
    cards = db.scalar(
        select(func.count()).select_from(CrmCard).where(scope.holds(CrmCard))
    )
    return OfficeCrmOut(
        state=str(setup.state) if setup is not None else "none",  # type: ignore[arg-type]
        cards=int(cards or 0),
    )


def _out(db: Db, customer: User, business: Business) -> OfficeBusinessOut:
    links = services.links_of(db, business)
    pair = services.pair_of(db, business)
    page = services.page_of(db, business)
    members = db.scalar(
        select(func.count())
        .select_from(BusinessMember)
        .where(
            BusinessMember.business_id == business.id,
            BusinessMember.is_active.is_(True),
        )
    )
    return OfficeBusinessOut(
        id=business.id,
        name=business.name,
        pair=pair.external_id if pair is not None else "",
        page=OfficePageOut(
            id=page.id,
            external_id=page.external_id,
            name=page.name,
            subscribed=bool(page.is_active),
        )
        if page is not None
        else None,
        networks=[
            OfficeNetworkOut(
                provider=link.provider,
                kind=link.kind,  # type: ignore[arg-type]
                external_id=link.external_id,
                name=(link.ad_account.name if link.ad_account is not None else "")
                or (link.page.name if link.page is not None else ""),
            )
            for link in links
        ],
        members=int(members or 0),
        crm=_crm_out(db, customer, pair),
        knowledge=_knowledge_out(db, business),
    )


@router.get("", response_model=OfficeBusinessesOut)
def businesses(customer_id: uuid.UUID, db: Db, actor: Admin) -> OfficeBusinessesOut:
    """The customer's businesses: every profile that advertises from
    something, or stands for a page."""
    customer = _customer(db, customer_id)
    linked = select(BusinessLink.business_id).where(BusinessLink.unbound_at.is_(None))
    rows = db.scalars(
        select(Business)
        .where(
            Business.user_id == customer.id,
            Business.id.in_(linked) | Business.page_id.is_not(None),
        )
        .order_by(Business.name, Business.created_at, Business.id)
    )
    return OfficeBusinessesOut(
        businesses=[_out(db, customer, business) for business in rows]
    )


@router.post("/{business_id}/knowledge/clear", responses={200: {"model": MessageOut}})
def clear_knowledge(
    customer_id: uuid.UUID, business_id: uuid.UUID, body: ReasonIn, db: Db, actor: Admin
) -> dict[str, Any]:
    """Take out what the AI wrote of this business - the description, the
    things sold, the facts, everything waiting for a yes, and a kind nobody
    confirmed. What a person wrote stays."""
    customer = _customer(db, customer_id)
    business = services.business_of(db, customer=customer, business_id=business_id)
    gone = services.clear_ai_knowledge(
        db, customer=customer, business=business, actor=actor, reason=body.reason
    )
    db.commit()
    total = sum(gone.values())
    return {
        "message": f"AI yozgan ma'lumotlar tozalandi: {total} ta."
        if total
        else "AI yozgan ma'lumot yo'q edi.",
        "cleared": gone,
    }


@router.post("/{business_id}/crm/state", responses={200: {"model": MessageOut}})
def crm_state(
    customer_id: uuid.UUID,
    business_id: uuid.UUID,
    body: CrmStateIn,
    db: Db,
    actor: Admin,
) -> dict[str, Any]:
    """Stop this business's board, or start it again. Stopped, nothing on
    it is lost. A CRM never set up is the owner's to set up first."""
    customer = _customer(db, customer_id)
    business = services.business_of(db, customer=customer, business_id=business_id)
    pair = services.pair_of(db, business)
    viewer = office_viewer(
        db, customer=customer, staff=actor, wanted=pair.external_id if pair else ""
    )
    if pair is None or viewer.pair is None or viewer.pair.key != pair.external_id:
        raise services.BusinessHasNoPair
    placed = 0
    if body.on:
        placed = crm.enable_crm(db, viewer=viewer)
    else:
        crm.disable_crm(db, viewer=viewer)
    record(
        db,
        customer=customer,
        actor=actor,
        kind=ActionKind.CRM_STATE_CHANGED,
        reason=body.reason,
        detail={
            "pair": pair.external_id,
            "business": str(business.id),
            "state": SetupState.ON if body.on else SetupState.OFF,
            "placed": placed,
        },
    )
    db.commit()
    return {
        "message": f"CRM yoqildi. Doskaga tushgan lidlar: {placed}."
        if body.on
        else "CRM to'xtatildi."
    }


@router.post("/{business_id}/crm/erase", responses={200: {"model": MessageOut}})
def crm_erase(
    customer_id: uuid.UUID, business_id: uuid.UUID, body: ReasonIn, db: Db, actor: Owner
) -> dict[str, Any]:
    """This business's CRM alone, gone as if never set up: cards, columns,
    reasons, managers. The leads stay, and the owner sets it up again from
    the first step. Owner only."""
    customer = _customer(db, customer_id)
    business = services.business_of(db, customer=customer, business_id=business_id)
    gone = services.erase_business_crm(
        db, customer=customer, business=business, actor=actor, reason=body.reason
    )
    db.commit()
    return {
        "message": f"Biznes CRM'i o'chirildi: {gone.cards} ta karta, "
        f"{gone.managers} ta menejer."
    }


@router.post(
    "/{business_id}/networks/{provider}/remove",
    responses={200: {"model": MessageOut}},
)
def remove_network(
    customer_id: uuid.UUID,
    business_id: uuid.UUID,
    provider: str,
    body: ReasonIn,
    db: Db,
    actor: Admin,
) -> dict[str, Any]:
    """Untie one network from the business: `meta` takes the page and ad
    account pair away (both stay connected), any other its account there."""
    customer = _customer(db, customer_id)
    business = services.business_of(db, customer=customer, business_id=business_id)
    services.remove_network(
        db,
        customer=customer,
        business=business,
        provider=provider.strip().lower(),
        actor=actor,
        reason=body.reason,
    )
    db.commit()
    return {"message": "Tarmoq biznesdan uzildi."}


@router.post("/{business_id}/subscription/add", responses={200: {"model": MessageOut}})
def subscribe(
    customer_id: uuid.UUID, business_id: uuid.UUID, body: ReasonIn, db: Db, actor: Admin
) -> dict[str, Any]:
    """Switch the business's page on in a free place of the subscription.
    With no place free it is refused: a place past the plan is given by
    `POST /pages/{page_id}/add`."""
    customer = _customer(db, customer_id)
    business = services.business_of(db, customer=customer, business_id=business_id)
    services.subscribe(
        db, customer=customer, business=business, actor=actor, reason=body.reason
    )
    db.commit()
    return {"message": "Biznes obunaga qo'shildi."}


@router.post(
    "/{business_id}/subscription/remove", responses={200: {"model": MessageOut}}
)
def unsubscribe(
    customer_id: uuid.UUID, business_id: uuid.UUID, body: ReasonIn, db: Db, actor: Admin
) -> dict[str, Any]:
    """Take the business's page out of the subscription; the place is free
    for another business. Nothing it collected is lost."""
    customer = _customer(db, customer_id)
    business = services.business_of(db, customer=customer, business_id=business_id)
    services.unsubscribe(
        db,
        customer=customer,
        business=business,
        actor=actor,
        reason=body.reason,
        now=utcnow(),
    )
    db.commit()
    return {"message": "Biznes obunadan olib tashlandi."}


@router.post("/{business_id}/subscription/move", responses={200: {"model": MessageOut}})
def move_place(
    customer_id: uuid.UUID, business_id: uuid.UUID, body: MoveIn, db: Db, actor: Admin
) -> dict[str, Any]:
    """Hand this business's place in the subscription to another business
    of the same customer."""
    customer = _customer(db, customer_id)
    business = services.business_of(db, customer=customer, business_id=business_id)
    target = services.business_of(db, customer=customer, business_id=body.target)
    services.move_place(
        db,
        customer=customer,
        business=business,
        target=target,
        actor=actor,
        reason=body.reason,
        now=utcnow(),
    )
    db.commit()
    return {"message": "Obunadagi o'rin boshqa biznesga o'tkazildi."}


@router.post("/{business_id}/delete", responses={200: {"model": MessageOut}})
def delete(
    customer_id: uuid.UUID, business_id: uuid.UUID, body: DeleteIn, db: Db, actor: Owner
) -> dict[str, Any]:
    """The whole business: its CRM, networks, people, knowledge, its place
    in the subscription and the business itself. The page and the account
    stay connected. Owner only; the customer's address is typed back."""
    customer = _customer(db, customer_id)
    business = services.business_of(db, customer=customer, business_id=business_id)
    gone = services.delete_business(
        db,
        customer=customer,
        business=business,
        actor=actor,
        typed_email=body.email,
        reason=body.reason,
        with_leads=body.with_leads,
        now=utcnow(),
    )
    db.commit()
    return {"message": "Biznes o'chirildi.", "deleted": gone}
