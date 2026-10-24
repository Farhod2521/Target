"""The office's sales board, as JSON for the office frontend.

Every route answers 404 to staff without a sales role, as Django's
``staff_required`` did. What the board's templates were given is what these
return; the dialog's refusals come back as the DomainError body.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import Db
from app.common.cache import cache
from app.common.config import settings
from app.common.db import get_db, utcnow
from app.common.exceptions import DomainError
from app.modules.accounts.models import User
from app.modules.backoffice.constants import SALES_LEAD_ROLES, SALES_ROLES, Role
from app.modules.backoffice.permissions import roles_of, staff_required
from app.modules.sales import selectors, services
from app.modules.sales.constants import (
    ACTIVITY_KIND_LABELS,
    COLUMN_CARDS,
    GROUP_LABELS,
    HOLD_TERM_LABELS,
    STAGE_LABELS,
    HoldTerm,
    Stage,
)
from app.modules.sales.models import (
    ContactHold,
    LostReason,
    SalesActivity,
    SalesClaim,
    SalesSegment,
)
from app.modules.sales.selectors import (
    ALL,
    POOL,
    ClientCard,
    Column,
    ManagerMonth,
    Rule,
    Scope,
    Span,
)

router = APIRouter(prefix="/office/sales", tags=["sales"])
Seller = Annotated[User, Depends(staff_required(*SALES_ROLES))]
Lead = Annotated[User, Depends(staff_required(*SALES_LEAD_ROLES))]

NO_ANSWER = "no_answer"
CALLBACK = "callback"
THINKING = "thinking"
USING = "using"
AWAITING = "awaiting"
LOST = "lost"
OUTCOMES = {
    NO_ANSWER: "Javob bermadi",
    CALLBACK: "Qayta aloqa",
    THINKING: "O'ylab ko'radi",
    USING: "Foydalanmoqda",
    AWAITING: "To'lov kutilmoqda",
    LOST: "Rad etdi",
}
OWN, WATCH, QUEUE, GONE = "own", "watch", "queue", "gone"
TAKEN = str(Stage.TAKEN)
REFUSED = "lost"
ASKS = (CALLBACK, THINKING, LOST)
TARGETS = (TAKEN, NO_ANSWER, USING, AWAITING, *ASKS)
ORDER_KEY = "sales_card_order:{user}"
ORDER_SECONDS = 30 * 24 * 60 * 60


# -- who is looking --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Viewer:
    user: User
    is_lead: bool
    is_owner: bool
    chip: str
    manager: str
    term: str
    now: datetime
    rule: Rule
    extra: list[SalesSegment]

    @property
    def scope(self) -> Scope:
        if not self.is_lead:
            return Scope(manager_id=self.user.id, term=self.term)
        return Scope(manager_id=_uuid(self.manager), term=self.term)


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def viewer(
    user: Seller,
    db: Session = Depends(get_db),
    g: str = Query(ALL),
    m: str = Query(""),
    q: str = Query(""),
) -> Viewer:
    held = roles_of(db, user)
    now = utcnow()
    return Viewer(
        user=user,
        is_lead=bool(held & {str(role) for role in SALES_LEAD_ROLES}),
        is_owner=str(Role.OWNER) in held,
        chip=g or ALL,
        manager=m if _uuid(m) is not None else "",
        term=selectors.search_term(q),
        now=now,
        rule=selectors.rule_at(db, at=now),
        extra=selectors.segments(db),
    )


Who = Annotated[Viewer, Depends(viewer)]


# -- how things are drawn --------------------------------------------------------


def _person(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": str(user.id),
        "name": user.full_name or user.email,
        "email": user.email,
    }


def _plan_line(subscription: Any) -> dict[str, Any] | None:
    if subscription is None:
        return None
    return {
        "plan": subscription.plan.name,
        "status": subscription.status,
        "expires_at": subscription.expires_at,
    }


def card_out(card: SalesClaim) -> dict[str, Any]:
    subject = card.owner
    consult = card.consult
    return {
        "id": str(card.id),
        "client_id": str(card.subject_id),
        "name": (
            (subject.full_name or subject.email)
            if subject is not None
            else (consult.name if consult else "")
        ),
        "phone": subject.phone if subject else (consult.phone_e164 if consult else ""),
        "is_request": subject is None,
        "group": card.group,
        "group_label": GROUP_LABELS.get(card.group, card.group),  # type: ignore[call-overload]
        "stage": card.stage,
        "outcome": card.outcome,
        "column": selectors.column_of(card),
        "attempts": card.attempts,
        "callback_at": card.callback_at,
        "claimed_at": card.claimed_at,
        "expires_at": card.expires_at,
        "extended_at": card.extended_at,
        "contacted_at": card.contacted_at,
        "closed_at": card.closed_at,
        "manager": _person(card.manager),
        "reason": card.reason.label if card.reason else "",
        "invoice": card.invoice.number if card.invoice else "",
        "live": _plan_line(getattr(card, "live", None)),
    }


def pooled_out(row: Any) -> dict[str, Any]:
    if getattr(row, "is_request", False):
        return {
            "client_id": str(row.id),
            "is_request": True,
            "name": row.name,
            "phone": row.phone_e164,
            "group": row.group,
            "group_label": GROUP_LABELS[row.group],
            "asked_at": row.asked_at,
            "last_closed": row.last_closed,
            "last_reason": row.last_reason,
        }
    group = getattr(row, "group", None)
    return {
        "client_id": str(row.id),
        "is_request": False,
        "name": row.full_name or row.email,
        "email": row.email,
        "phone": row.phone,
        "date_joined": row.date_joined,
        "group": group,
        "group_label": GROUP_LABELS.get(group, "") if group else "",
        **{
            name: getattr(row, name, None)
            for name in (
                "live_expires",
                "live_plan_name",
                "live_status",
                "live_started",
                "last_plan_name",
                "last_ended",
                "has_paid",
                "is_referred",
                "last_outcome",
                "last_closed",
                "last_reason",
                "asked_at",
                "is_problem",
                "is_asked",
            )
        },
        "live_plan_id": str(row.live_plan_id)
        if getattr(row, "live_plan_id", None)
        else None,
    }


def column_out(column: Column) -> dict[str, Any]:
    return {
        "key": column.key,
        "label": column.label,
        "total": column.total,
        "hidden": column.hidden,
        "cards": [card_out(card) for card in column.cards],
    }


def line_out(line: SalesActivity) -> dict[str, Any]:
    return {
        "id": str(line.id),
        "kind": line.kind,
        "label": ACTIVITY_KIND_LABELS.get(line.kind, line.kind),  # type: ignore[call-overload]
        "actor": _person(line.actor),
        "reason": line.reason.label if line.reason else "",
        "body": line.body,
        "callback_at": line.callback_at,
        "created_at": line.created_at,
    }


def hold_out(row: ContactHold | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": str(row.id),
        "client_id": str(row.owner_id or row.consult_id),
        "name": (
            (row.owner.full_name or row.owner.email)
            if row.owner
            else (row.consult.name if row.consult else "")
        ),
        "until": row.until,
        "forever": row.until is None,
        "set_by": _person(row.set_by),
        "reason": row.reason.label if row.reason else "",
        "created_at": row.created_at,
    }


def reason_out(row: LostReason) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "label": row.label,
        "position": row.position,
        "archived_at": row.archived_at,
    }


def segment_out(row: SalesSegment) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "key": selectors.segment_key(row),
        "plan": {"id": str(row.plan_id), "code": row.plan.code, "name": row.plan.name},
        "days": row.days,
    }


def month_out(row: ManagerMonth) -> dict[str, Any]:
    return {
        "manager_id": str(row.manager_id),
        "name": row.name,
        "claimed": row.claimed,
        "contacted": row.contacted,
        "sold": row.sold,
        "base_minor": row.base_minor,
        "commission_minor": row.commission_minor,
        "currency": row.currency,
        "open_now": row.open_now,
        "conversion": row.conversion,
    }


def span_out(span: Span) -> dict[str, Any]:
    return {"month": span.month.isoformat()[:7], "start": span.start, "end": span.end}


def who_out(who: Viewer) -> dict[str, Any]:
    return {
        "user": _person(who.user),
        "is_lead": who.is_lead,
        "is_owner": who.is_owner,
        "chip": who.chip,
        "manager": who.manager,
        "term": who.term,
        "rule": {
            "percent": who.rule.percent,
            "ending_days": who.rule.ending_days,
            "set": who.rule.set,
        },
        "segments": [segment_out(row) for row in who.extra],
    }


# -- the manager's own card order ------------------------------------------------


def _saved_order(user: User) -> dict[str, list[str]]:
    return cache.get(ORDER_KEY.format(user=user.id)) or {}


def arrange(user: User, columns: list[Column]) -> list[Column]:
    saved = _saved_order(user)
    for column in columns:
        if column.key in saved:
            rank = {client: index for index, client in enumerate(saved[column.key])}
            fresh = [c for c in column.cards if str(c.subject_id) not in rank]
            known = [c for c in column.cards if str(c.subject_id) in rank]
            known.sort(key=lambda c: rank[str(c.subject_id)])
            column.cards = fresh + known
    return columns


class ReorderIn(BaseModel):
    stage: str
    c: list[str] = Field(default_factory=list)


@router.post("/order", status_code=status.HTTP_204_NO_CONTENT)
def reorder(body: ReorderIn, user: Seller) -> Response:
    if body.stage not in {str(stage) for stage in Stage}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST)
    ids: list[str] = []
    for value in body.c[:COLUMN_CARDS]:
        found = _uuid(value)
        if found is not None:
            ids.append(str(found))
    saved = dict(_saved_order(user))
    saved[body.stage] = ids
    cache.set(ORDER_KEY.format(user=user.id), saved, timeout=ORDER_SECONDS)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -- the board ---------------------------------------------------------------------


def _pool(db: Session, who: Viewer, *, offset: int = 0) -> dict[str, Any]:
    found = selectors.chips(
        db,
        now=who.now,
        ending_days=who.rule.ending_days,
        extra=who.extra,
        term=who.term,
    )
    total = next((chip.count for chip in found if chip.key == who.chip), found[0].count)
    cards = selectors.pool_rows(
        db,
        now=who.now,
        ending_days=who.rule.ending_days,
        key=who.chip,
        extra=who.extra,
        offset=offset,
        limit=COLUMN_CARDS,
        term=who.term,
    )
    shown = offset + len(cards)
    return {
        "chips": [
            {"key": chip.key, "label": chip.label, "count": chip.count}
            for chip in found
        ],
        "pool_cards": [pooled_out(row) for row in cards],
        "pool_total": total,
        "pool_next": shown if shown < total else None,
    }


@router.get("")
def board(db: Db, who: Who) -> dict[str, Any]:
    drawn = arrange(who.user, selectors.columns(db, scope=who.scope, now=who.now))
    queued = _pool(db, who)
    return {
        "who": who_out(who),
        "columns": [column_out(column) for column in drawn],
        "held": selectors.open_count(db, manager=who.user),
        "managers": (
            [_person(person) for person in selectors.managers(db)]
            if who.is_lead
            else []
        ),
        "cursor": selectors.board_cursor(db, scope=who.scope),
        "nothing_found": bool(who.term)
        and not queued["pool_total"]
        and not any(column.total for column in drawn),
        "stages": STAGE_LABELS,
        "outcomes": OUTCOMES,
        "hold_terms": HOLD_TERM_LABELS,
        **queued,
    }


@router.get("/pool")
def pool(db: Db, who: Who, offset: int = Query(0, ge=0)) -> dict[str, Any]:
    return {"who": who_out(who), **_pool(db, who, offset=offset)}


def placement_context(
    db: Session, who: Viewer, *, client_id: uuid.UUID
) -> dict[str, Any]:
    card = selectors.card_in_scope(
        db, client_id=client_id, scope=who.scope, now=who.now
    )
    pooled = None
    if card is None or selectors.column_of(card) == "":
        card = None
        pooled = selectors.queued_client(
            db,
            client_id=client_id,
            now=who.now,
            ending_days=who.rule.ending_days,
            key=who.chip,
            extra=who.extra,
            term=who.term,
        )
    found = selectors.chips(
        db,
        now=who.now,
        ending_days=who.rule.ending_days,
        extra=who.extra,
        term=who.term,
    )
    return {
        "client_id": str(client_id),
        "placed": card_out(card) if card is not None else None,
        "column": (
            selectors.column_of(card) if card is not None else (POOL if pooled else "")
        ),
        "pooled": pooled_out(pooled) if pooled is not None else None,
        "totals": selectors.column_totals(db, scope=who.scope, now=who.now),
        "pool_total": next(
            (chip.count for chip in found if chip.key == who.chip), found[0].count
        ),
        "held": selectors.open_count(db, manager=who.user),
    }


@router.get("/cards/{client_id}")
def placement(client_id: uuid.UUID, db: Db, who: Who) -> dict[str, Any]:
    return placement_context(db, who, client_id=client_id)


@router.get("/pulse", response_model=None)
def pulse(db: Db, who: Who, cursor: str = Query("")) -> Response | dict[str, Any]:
    current = selectors.board_cursor(db, scope=who.scope)
    if cursor == current:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    drawn = arrange(who.user, selectors.columns(db, scope=who.scope, now=who.now))
    return {
        "columns": [column_out(column) for column in drawn],
        "cursor": current,
        "held": selectors.open_count(db, manager=who.user),
    }


# -- one customer ------------------------------------------------------------------


def _mode(who: Viewer, card: ClientCard) -> str:
    if card.claim is not None:
        if card.claim.manager_id == who.user.id:
            return OWN
        return WATCH if who.is_lead else GONE
    if card.queued_group is not None:
        return QUEUE
    return WATCH if who.is_lead else GONE


def _card(db: Session, who: Viewer, client_id: uuid.UUID) -> ClientCard:
    client = selectors.customer(db, client_id=client_id, now=who.now)
    if client is None:
        consult = selectors.ariza(db, consult_id=client_id)
        if consult is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        return selectors.ariza_card(db, consult=consult, now=who.now)
    return selectors.client_card(
        db,
        client=client,
        now=who.now,
        ending_days=who.rule.ending_days,
        extra=who.extra,
    )


def _bill(bill: Any) -> dict[str, Any]:
    sale = getattr(bill, "sale", None)
    return {
        "id": str(bill.id),
        "number": bill.number,
        "plan": bill.plan.name if bill.plan else "",
        "amount_minor": bill.amount_minor,
        "currency": bill.currency,
        "paid_at": bill.paid_at,
        "source": sale.source if sale else "",
        "manager": _person(sale.manager) if sale else None,
    }


def _dialog(
    db: Session,
    who: Viewer,
    client_id: uuid.UUID,
    *,
    refusal: str = "",
    with_placement: bool = False,
) -> dict[str, Any]:
    card = _card(db, who, client_id)
    mode = _mode(who, card)
    if mode in (OWN, WATCH) and card.client is not None:
        services.note_viewed(db, client=card.client, actor=who.user)
        db.commit()
    client = card.client
    result: dict[str, Any] = {
        "mode": mode,
        "refusal": refusal,
        "card": {
            "subject_id": str(card.subject_id),
            "client": pooled_out(client) if client is not None else None,
            "consult": (
                {
                    "id": str(card.consult.id),
                    "name": card.consult.name,
                    "phone": card.consult.phone_e164,
                    "created_at": card.consult.created_at,
                }
                if card.consult is not None
                else None
            ),
            "claim": card_out(card.claim) if card.claim is not None else None,
            "queued_group": card.queued_group,
            "history": [line_out(line) for line in card.history],
            "bills": [_bill(bill) for bill in card.bills],
            "paid_count": card.paid_count,
            "facebook": card.facebook,
            "facebook_name": card.facebook_name,
            "telegram": card.telegram,
            "launches": card.launches,
        },
        "hold": (
            hold_out(selectors.hold_for(db, client_id=client_id, now=who.now))
            if mode == WATCH
            else None
        ),
        "reasons": [reason_out(row) for row in selectors.live_reasons(db)],
        "outcomes": OUTCOMES,
        "hold_terms": HOLD_TERM_LABELS,
        "held": selectors.open_count(db, manager=who.user),
    }
    if with_placement:
        result["placement"] = placement_context(db, who, client_id=client_id)
    return result


@router.get("/clients/{client_id}")
def dialog(client_id: uuid.UUID, db: Db, who: Who) -> dict[str, Any]:
    return _dialog(db, who, client_id)


def _refused(
    db: Session, who: Viewer, client_id: uuid.UUID, exc: DomainError
) -> dict[str, Any]:
    db.rollback()
    return _dialog(db, who, client_id, refusal=exc.message, with_placement=True)


@router.post("/clients/{client_id}/take")
def take(client_id: uuid.UUID, db: Db, who: Who) -> dict[str, Any]:
    try:
        services.claim_client(db, manager=who.user, client_id=client_id, now=who.now)
        db.commit()
    except DomainError as exc:
        return _refused(db, who, client_id, exc)
    return _dialog(db, who, client_id, with_placement=True)


class OutcomeIn(BaseModel):
    outcome: str
    callback_at: datetime | None = None
    reason: uuid.UUID | None = None
    term: HoldTerm = HoldTerm.DAYS_90
    note: str = Field(default="", max_length=2000)


def apply_outcome(
    db: Session, who: Viewer, client_id: uuid.UUID, body: OutcomeIn
) -> None:
    from app.common.dates import office_zone

    callback_at = body.callback_at
    if callback_at is not None and callback_at.tzinfo is None:
        callback_at = callback_at.replace(tzinfo=office_zone())
    reason = selectors.reason_by_id(db, reason_id=body.reason) if body.reason else None
    user, now, note = who.user, who.now, body.note
    if body.outcome == NO_ANSWER:
        services.record_no_answer(
            db, manager=user, client_id=client_id, note=note, now=now
        )
    elif body.outcome == CALLBACK:
        services.mark_callback(
            db,
            manager=user,
            client_id=client_id,
            callback_at=callback_at,
            note=note,
            now=now,
        )
    elif body.outcome == THINKING:
        services.mark_thinking(
            db,
            manager=user,
            client_id=client_id,
            callback_at=callback_at,
            reason=reason,
            note=note,
            now=now,
        )
    elif body.outcome == USING:
        services.mark_using(db, manager=user, client_id=client_id, note=note, now=now)
    elif body.outcome == AWAITING:
        services.mark_awaiting(
            db, manager=user, client_id=client_id, note=note, now=now
        )
    elif body.outcome == LOST:
        services.close_as_lost(
            db,
            manager=user,
            client_id=client_id,
            reason=reason,
            term=body.term,
            note=note,
            now=now,
        )


def moved(db: Session, who: Viewer, client_id: uuid.UUID) -> dict[str, Any]:
    return {"message": "Saqlandi.", **placement_context(db, who, client_id=client_id)}


@router.post("/clients/{client_id}/outcome")
def outcome(client_id: uuid.UUID, body: OutcomeIn, db: Db, who: Who) -> dict[str, Any]:
    if body.outcome not in OUTCOMES:
        return _dialog(db, who, client_id, refusal="Natijani tanlang.")
    try:
        apply_outcome(db, who, client_id, body)
        db.commit()
    except DomainError as exc:
        return _refused(db, who, client_id, exc)
    return moved(db, who, client_id)


class NoteIn(BaseModel):
    body: str = Field(default="", max_length=2000)


@router.post("/clients/{client_id}/note")
def note(client_id: uuid.UUID, body: NoteIn, db: Db, who: Who) -> dict[str, Any]:
    try:
        services.add_note(
            db, manager=who.user, client_id=client_id, body=body.body, now=who.now
        )
        db.commit()
    except DomainError as exc:
        return _refused(db, who, client_id, exc)
    return _dialog(db, who, client_id, with_placement=True)


@router.post("/clients/{client_id}/give-back")
def give_back(client_id: uuid.UUID, db: Db, who: Who) -> dict[str, Any]:
    try:
        services.return_to_pool(
            db, manager=who.user, client_id=client_id, note="", now=who.now
        )
        db.commit()
    except DomainError as exc:
        return _refused(db, who, client_id, exc)
    return moved(db, who, client_id)


class DropIn(OutcomeIn):
    to: str
    origin: str = Field(default="", alias="from")
    outcome: str = ""


@router.post("/clients/{client_id}/drop")
def drop(client_id: uuid.UUID, body: DropIn, db: Db, who: Who) -> dict[str, Any]:
    """A card dragged to another column: the move, and any question it asks."""
    to, origin = body.to, body.origin
    if to not in TARGETS:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    user, now = who.user, who.now
    try:
        if origin == REFUSED:
            services.reopen_card(db, manager=user, client_id=client_id, now=now)
        if to in ASKS:
            apply_outcome(db, who, client_id, body.model_copy(update={"outcome": to}))
        elif to == TAKEN and origin in ("", POOL):
            services.claim_client(db, manager=user, client_id=client_id, now=now)
        elif to == TAKEN:
            services.move_to_taken(
                db, manager=user, client_id=client_id, note="", now=now
            )
        elif to == NO_ANSWER:
            services.record_no_answer(
                db, manager=user, client_id=client_id, note="", now=now
            )
        elif to == USING:
            services.mark_using(db, manager=user, client_id=client_id, note="", now=now)
        else:
            services.mark_awaiting(
                db, manager=user, client_id=client_id, note="", now=now
            )
        db.commit()
    except DomainError:
        db.rollback()
        raise
    return moved(db, who, client_id)


# -- a seller's own month, and the team's -------------------------------------------


@router.get("/mine")
def mine(db: Db, who: Who) -> dict[str, Any]:
    from app.modules.referrals.selectors import available_minor

    span = selectors.current_span(now=who.now)
    ranked = selectors.standing(db, span=span, reader=who.user)
    me = ranked.mine.row
    currency = me.currency or settings.billing_currency
    return {
        "span": span_out(span),
        "me": month_out(me),
        "place": ranked.mine.place,
        "ranked": len(ranked.table),
        "to_next": ranked.to_next,
        "next_place": ranked.next_place,
        "currency": currency,
        "percent": who.rule.percent,
        "wallet_minor": available_minor(db, owner=who.user, currency=currency),
        "held": selectors.open_count(db, manager=who.user),
        "sales": [
            _share(row)
            for row in selectors.sales_of(db, manager_id=who.user.id, span=span)
        ],
        "months": [
            {
                "month": row.month.isoformat()[:7],
                "claimed": row.claimed,
                "contacted": row.contacted,
                "sold": row.sold,
                "base_minor": row.base_minor,
                "commission_minor": row.commission_minor,
                "currency": row.currency,
            }
            for row in selectors.months_of(db, manager=who.user)
        ],
    }


def _share(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "client": _person(row.client),
        "invoice": row.invoice.number if row.invoice else "",
        "plan": row.invoice.plan.name if row.invoice and row.invoice.plan else "",
        "base_minor": row.base_minor,
        "percent": row.percent,
        "amount_minor": row.amount_minor,
        "currency": row.currency,
        "earned_at": row.earned_at,
    }


@router.get("/team")
def team(db: Db, who: Who) -> dict[str, Any]:
    span = selectors.current_span(now=who.now)
    ranked = selectors.standing(db, span=span, reader=who.user)
    previous = selectors.span_of((span.start - timedelta(days=1)).date())
    last = next(
        (row for row in selectors.closed_month(db, month=previous.month) if row.sold),
        None,
    )
    currency = next(
        (item.row.currency for item in ranked.table if item.row.currency),
        settings.billing_currency,
    )

    def ranked_out(item: Any) -> dict[str, Any]:
        return {"place": item.place, **month_out(item.row)}

    return {
        "span": span_out(span),
        "podium": [ranked_out(item) for item in ranked.table[:3] if item.row.sold],
        "table": [ranked_out(item) for item in ranked.table],
        "mine": ranked_out(ranked.mine),
        "to_next": ranked.to_next,
        "next_place": ranked.next_place,
        "currency": currency,
        "previous": span_out(previous),
        "last_winner": month_out(last) if last else None,
    }


# -- the lead's screens ------------------------------------------------------------


def _month(raw: str, *, default: Span) -> Span:
    try:
        year, month = (int(part) for part in raw.split("-"))
        return selectors.span_of(date(year, month, 1))
    except ValueError:
        return default


@router.get("/report")
def report(
    db: Db, lead: Lead, oy: str = Query(""), m: str = Query("")
) -> dict[str, Any]:
    now = utcnow()
    current = selectors.current_span(now=now)
    span = _month(oy, default=current)
    live = span.month == current.month
    closed = not live and selectors.is_closed(db, month=span.month)
    rows = (
        selectors.live_month(db, span=span)
        if live or not closed
        else selectors.closed_month(db, month=span.month)
    )
    picked = _uuid(m)
    currency = next(
        (row.currency for row in rows if row.currency), settings.billing_currency
    )
    months: list[date] = []
    for month in [current.month, *selectors.closed_months(db)]:
        if month not in months:
            months.append(month)
    total = ManagerMonth(manager_id=uuid.UUID(int=0), name="")
    for row in rows:
        total.claimed += row.claimed
        total.contacted += row.contacted
        total.sold += row.sold
        total.base_minor += row.base_minor
        total.commission_minor += row.commission_minor
    return {
        "span": span_out(span),
        "live": live,
        "closed": closed,
        "months": [month.isoformat()[:7] for month in months[:13]],
        "rows": [month_out(row) for row in rows],
        "currency": currency,
        "totals": month_out(total),
        "picked": str(picked) if picked else None,
        "picked_sales": (
            [
                _share(row)
                for row in selectors.sales_of(db, manager_id=picked, span=span)
            ]
            if picked
            else []
        ),
        "reasons": [vars_of(share) for share in selectors.reasons_in(db, span=span)],
        "sources": [vars_of(share) for share in selectors.sources_in(db, span=span)],
    }


def vars_of(share: Any) -> dict[str, Any]:
    return {"label": share.label, "count": share.count, "width": share.width}


@router.get("/holds")
def holds(db: Db, lead: Lead, page: int = Query(1, ge=1)) -> dict[str, Any]:
    query = selectors.active_holds(now=utcnow())
    total = selectors.count_of(db, query)
    size = selectors.HOLDS_PAGE
    rows = db.scalars(query.offset((page - 1) * size).limit(size)).unique()
    return {
        "page": page,
        "pages": max((total + size - 1) // size, 1),
        "total": total,
        "rows": [hold_out(row) for row in rows],
    }


@router.post("/holds/{hold_id}/lift")
def lift(hold_id: uuid.UUID, db: Db, lead: Lead) -> dict[str, Any]:
    services.lift_hold(db, hold_id=hold_id, actor=lead, now=utcnow())
    db.commit()
    return {"message": "Mijoz navbatga qaytdi."}


@router.get("/settings")
def settings_screen(db: Db, who: Who, lead: Lead) -> dict[str, Any]:
    return {
        "who": who_out(who),
        "rule": {"percent": who.rule.percent, "ending_days": who.rule.ending_days},
        "may_set_percent": who.is_owner,
        "history": [
            {
                "percent": row.percent,
                "ending_days": row.ending_days,
                "valid_from": row.valid_from,
                "set_by": _person(row.set_by),
            }
            for row in selectors.rule_history(db)
        ],
        "reasons": [reason_out(row) for row in selectors.all_reasons(db)],
        "segments": [segment_out(row) for row in who.extra],
    }


class RuleIn(BaseModel):
    percent: int | None = Field(default=None, ge=0, le=100)
    ending_days: int = Field(ge=1, le=60)


@router.post("/settings")
def save_rule(body: RuleIn, db: Db, who: Who, lead: Lead) -> dict[str, Any]:
    if who.is_owner and body.percent is not None:
        changed = services.set_rule(
            db,
            actor=who.user,
            percent=body.percent,
            ending_days=body.ending_days,
            now=who.now,
        )
    else:
        changed = services.set_ending_days(
            db, actor=who.user, ending_days=body.ending_days, now=who.now
        )
    db.commit()
    if changed is None:
        return {"changed": False, "message": "O'zgarish yo'q."}
    return {"changed": True, "message": "Yangi qoida shu daqiqadan amal qiladi."}


class ReasonIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)


@router.post("/settings/reasons", status_code=status.HTTP_201_CREATED)
def reason_add(body: ReasonIn, db: Db, lead: Lead) -> dict[str, Any]:
    row = services.add_reason(db, actor=lead, label=body.label, now=utcnow())
    db.commit()
    return {"message": "Sabab qo'shildi.", "reason": reason_out(row)}


class ReasonChangeIn(BaseModel):
    action: str = ""
    label: str = Field(default="", max_length=120)


@router.post("/settings/reasons/{reason_id}")
def reason_change(
    reason_id: uuid.UUID, body: ReasonChangeIn, db: Db, lead: Lead
) -> dict[str, Any]:
    reason = selectors.reason_by_id(db, reason_id=reason_id)
    if reason is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    now = utcnow()
    if body.action == "archive":
        services.archive_reason(db, actor=lead, reason=reason, now=now)
    elif body.action == "restore":
        services.restore_reason(db, actor=lead, reason=reason, now=now)
    else:
        if not body.label.strip():
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Sabab matnini yozing."
            )
        services.rename_reason(db, actor=lead, reason=reason, label=body.label, now=now)
    db.commit()
    return {"message": "Saqlandi.", "reason": reason_out(reason)}


class SegmentIn(BaseModel):
    plan: uuid.UUID
    days: int = Field(ge=1, le=365)


@router.post("/settings/segments", status_code=status.HTTP_201_CREATED)
def segment_add(body: SegmentIn, db: Db, lead: Lead) -> dict[str, Any]:
    from app.modules.billing.models import Plan

    plan = db.get(Plan, body.plan)
    if plan is None or not plan.is_active:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Tarif va kunlar sonini tanlang.",
        )
    row = services.add_segment(db, actor=lead, plan=plan, days=body.days, now=utcnow())
    db.commit()
    return {"message": "Filtr qo'shildi.", "segment": segment_out(row)}


@router.delete("/settings/segments/{segment_id}")
def segment_remove(segment_id: uuid.UUID, db: Db, lead: Lead) -> dict[str, Any]:
    segment = selectors.segment_by_id(db, segment_id=segment_id)
    if segment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    services.remove_segment(db, actor=lead, segment=segment, now=utcnow())
    db.commit()
    return {"message": "Filtr olib tashlandi."}
