"""One customer as the board's side panel shows them."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.modules.accounts.models import User
from app.modules.public.models import ConsultRequest
from app.modules.sales.constants import Group
from app.modules.sales.models import SalesActivity, SalesClaim, SaleSource, SalesSegment
from app.modules.sales.selectors.arizas import consult_by_id, queued_ariza
from app.modules.sales.selectors.pool import annotated_account, group_now
from app.modules.sales.selectors.search import subject_q

HISTORY_LINES = 20
RECENT_BILLS = 5
FB_CONNECTED = "connected"
FB_BROKEN = "broken"
FB_NONE = "none"


@dataclass(frozen=True, slots=True)
class ClientCard:
    client: User | None
    claim: SalesClaim | None
    queued_group: str | None
    history: list[SalesActivity]
    bills: list[object]
    paid_count: int
    facebook: str
    launches: int
    consult: ConsultRequest | None = None
    telegram: str = ""
    facebook_name: str = ""

    @property
    def subject_id(self) -> uuid.UUID:
        if self.client is not None:
            return self.client.id
        assert self.consult is not None
        return self.consult.id


def customer(db: Session, *, client_id: uuid.UUID, now: datetime) -> User | None:
    return annotated_account(db, client_id=client_id, now=now)


def open_claim(db: Session, *, client_id: uuid.UUID) -> SalesClaim | None:
    return db.scalars(
        select(SalesClaim)
        .options(
            joinedload(SalesClaim.manager),
            joinedload(SalesClaim.reason),
            joinedload(SalesClaim.invoice),
        )
        .where(subject_q(SalesClaim, client_id), SalesClaim.closed_at.is_(None))
        .limit(1)
    ).first()


def _lines(query: object) -> object:
    return (
        query.options(  # type: ignore[attr-defined]
            joinedload(SalesActivity.actor), joinedload(SalesActivity.reason)
        )
        .order_by(SalesActivity.created_at.desc())
        .limit(HISTORY_LINES)
    )


def history(db: Session, *, client_id: uuid.UUID) -> list[SalesActivity]:
    return list(
        db.scalars(
            _lines(select(SalesActivity).where(SalesActivity.owner_id == client_id))  # type: ignore[arg-type]
        )
    )


def _facebook(db: Session, *, client: User) -> tuple[str, str]:
    from app.modules.integrations.constants import USABLE_CONNECTION_STATUSES
    from app.modules.integrations.models import ProviderConnection

    connection = db.scalars(
        select(ProviderConnection)
        .where(ProviderConnection.owner_id == client.id)
        .order_by(ProviderConnection.created_at.desc())
        .limit(1)
    ).first()
    if connection is None:
        return FB_NONE, ""
    name = connection.external_user_name
    if connection.status in USABLE_CONNECTION_STATUSES:
        return FB_CONNECTED, name
    return FB_BROKEN, name


def _telegram(db: Session, *, client: User) -> str:
    from app.modules.notifications.models import TelegramChat

    return (
        db.scalar(
            select(TelegramChat.username)
            .where(TelegramChat.owner_id == client.id, TelegramChat.username != "")
            .order_by(TelegramChat.is_active.desc(), TelegramChat.linked_at.desc())
            .limit(1)
        )
        or ""
    )


def _with_sources(db: Session, bills: list[object]) -> list[object]:
    ids = [bill.id for bill in bills]  # type: ignore[attr-defined]
    sources = {}
    if ids:
        sources = {
            row.invoice_id: row
            for row in db.scalars(
                select(SaleSource)
                .options(joinedload(SaleSource.manager))
                .where(SaleSource.invoice_id.in_(ids))
            )
        }
    for bill in bills:
        bill.sale = sources.get(bill.id)  # type: ignore[attr-defined]
    return bills


def client_card(
    db: Session,
    *,
    client: User,
    now: datetime,
    ending_days: int,
    extra: list[SalesSegment],
) -> ClientCard:
    from app.modules.ads.constants import LaunchStatus
    from app.modules.ads.models import CampaignLaunch
    from app.modules.billing.constants import InvoiceStatus
    from app.modules.billing.models import Invoice

    claim = open_claim(db, client_id=client.id)
    paid = (Invoice.owner_id == client.id, Invoice.status == str(InvoiceStatus.PAID))
    facebook, facebook_name = _facebook(db, client=client)
    bills = list(
        db.scalars(
            select(Invoice)
            .options(joinedload(Invoice.plan))
            .where(*paid)
            .order_by(Invoice.paid_at.desc())
            .limit(RECENT_BILLS)
        )
    )
    return ClientCard(
        client=client,
        claim=claim,
        queued_group=(
            None
            if claim is not None
            else group_now(
                db, client_id=client.id, now=now, ending_days=ending_days, extra=extra
            )
        ),
        history=history(db, client_id=client.id),
        bills=_with_sources(db, bills),  # type: ignore[arg-type]
        paid_count=db.scalar(select(func.count(Invoice.id)).where(*paid)) or 0,
        facebook=facebook,
        facebook_name=facebook_name,
        telegram=_telegram(db, client=client),
        launches=db.scalar(
            select(func.count(CampaignLaunch.id)).where(
                CampaignLaunch.owner_id == client.id,
                CampaignLaunch.status == str(LaunchStatus.CREATED),
            )
        )
        or 0,
    )


def ariza(db: Session, *, consult_id: uuid.UUID) -> ConsultRequest | None:
    return consult_by_id(db, consult_id=consult_id)


def ariza_card(db: Session, *, consult: ConsultRequest, now: datetime) -> ClientCard:
    claim = open_claim(db, client_id=consult.id)
    queued = (
        claim is None and queued_ariza(db, consult_id=consult.id, now=now) is not None
    )
    same_number = select(ConsultRequest.id).where(
        ConsultRequest.phone_e164 == consult.phone_e164
    )
    lines = list(
        db.scalars(
            _lines(  # type: ignore[arg-type]
                select(SalesActivity).where(
                    SalesActivity.owner_id.is_(None),
                    SalesActivity.consult_id.in_(same_number),
                )
            )
        )
    )
    return ClientCard(
        client=None,
        consult=consult,
        claim=claim,
        queued_group=str(Group.ARIZA) if queued else None,
        history=lines,
        bills=[],
        paid_count=0,
        facebook=FB_NONE,
        launches=0,
    )
