"""The renewal board, «Uzaytirish»: paying Standart and Pro clients whose
term runs out. A card opens three days before the end and is the default
manager's; the term ending, the client's bill and their payment move it on
their own, and the manager's buttons do the rest. Each term has its own
card: the next one opens when the renewed term runs out in its turn."""

import uuid
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import Select, and_, exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.dates import localtime
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.billing.constants import (
    LIVE_SUBSCRIPTION_STATUSES,
    InvoiceKind,
    InvoiceStatus,
)
from app.modules.billing.models import Invoice, Plan, Subscription
from app.modules.boards.access import Access, works_on
from app.modules.boards.constants import (
    ATTEMPTS_MAX,
    DECLINE_REASON_LABELS,
    RENEWAL_ACTIONS,
    RENEWAL_BILL_FROM,
    RENEWAL_DECLINE_DAYS,
    RENEWAL_OPEN_DAYS,
    RENEWAL_PLAN_CODES,
    RENEWAL_SILENT_COLUMNS,
    REPORT_MAX_DAYS,
    SWEEP_BATCH,
    Board,
    CardAction,
    DeclineReason,
    EventKind,
    RenewalColumn,
)
from app.modules.boards.exceptions import (
    ActionNotHere,
    CardClosed,
    NoteRequired,
    NotOnBoard,
    ReasonRequired,
    ReportPeriodInvalid,
)
from app.modules.boards.models import BoardCard, BoardCardEvent, BoardSetting
from app.modules.boards.selectors import ensure_board
from app.modules.boards.services import move, record

BOARD = str(Board.RENEWAL)
_LIVE = [str(status) for status in LIVE_SUBSCRIPTION_STATUSES]


def _renewal_plans() -> Select[Any]:
    return select(Plan.id).where(Plan.code.in_(RENEWAL_PLAN_CODES))


def _paid_bill(owner_id: Any) -> Any:
    """A Standart or Pro bill this client paid: what makes them a paying
    client. A plan the office gave without a payment leaves none."""
    return and_(
        Invoice.owner_id == owner_id,
        Invoice.kind == str(InvoiceKind.PLAN),
        Invoice.status == str(InvoiceStatus.PAID),
        Invoice.plan_id.in_(_renewal_plans()),
    )


def default_manager(db: Session) -> User | None:
    """Who every new card goes to, while they still work the board."""
    manager_id = db.scalar(
        select(BoardSetting.manager_id).where(BoardSetting.board == BOARD)
    )
    if manager_id is None:
        return None
    manager = db.get(User, manager_id)
    if manager is None or not works_on(db, manager, Board.RENEWAL):
        return None
    return manager


def workers(db: Session) -> list[User]:
    """Everybody who holds the board's own role: who a card can go to."""
    people = db.scalars(
        select(User)
        .where(User.is_staff.is_(True), User.is_active.is_(True))
        .order_by(User.date_joined, User.id)
    )
    return [person for person in people if works_on(db, person, Board.RENEWAL)]


class Hands:
    """Who the next card goes to. The chosen manager takes every card; with
    nobody chosen the role is enough, and the cards are shared out: each to
    whoever holds the fewest open ones."""

    def __init__(self, db: Session) -> None:
        chosen = default_manager(db)
        self.people = [chosen] if chosen else workers(db)
        held = dict(
            db.execute(
                select(BoardCard.manager_id, func.count())
                .where(
                    BoardCard.board == BOARD,
                    BoardCard.closed_at.is_(None),
                    BoardCard.manager_id.is_not(None),
                )
                .group_by(BoardCard.manager_id)
            ).all()
        )
        self.load = {person.id: int(held.get(person.id, 0)) for person in self.people}

    def next(self) -> User | None:
        if not self.people:
            return None
        person = min(self.people, key=lambda one: self.load[one.id])
        self.load[person.id] += 1
        return person


def hand_out(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """The open cards nobody holds go to the team as soon as there is one:
    a role given after the cards were opened is enough to receive them."""
    hands = Hands(db)
    if not hands.people:
        return 0
    cards = list(
        db.scalars(
            select(BoardCard)
            .where(
                BoardCard.board == BOARD,
                BoardCard.closed_at.is_(None),
                BoardCard.manager_id.is_(None),
            )
            .order_by(BoardCard.term_ends_at, BoardCard.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    for card in cards:
        person = hands.next()
        assert person is not None
        card.manager_id = person.id
        record(
            db,
            card=card,
            kind=EventKind.ASSIGNED,
            now=now,
            body=person.full_name or person.email,
        )
    db.commit()
    return len(cards)


def date_words(moment: datetime) -> str:
    return localtime(moment).strftime("%d.%m.%Y")


# -- what happens on its own -------------------------------------------------


def open_cards(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """A card for every paying Standart or Pro client whose term ends
    within three days, or ended in the last thirty: into Tugayapti or
    Tugagan, the team's (``Hands``). One card per term, and none while the
    client's earlier card is still worked (``follow_terms`` moves its date).
    The first run after the board is switched on loads the terms that have
    ended already the same way."""
    carded = exists().where(
        BoardCard.board == BOARD,
        BoardCard.owner_id == Subscription.owner_id,
        BoardCard.term_ends_at == Subscription.expires_at,
    )
    worked = exists().where(
        BoardCard.board == BOARD,
        BoardCard.owner_id == Subscription.owner_id,
        BoardCard.closed_at.is_(None),
    )
    rows = list(
        db.execute(
            select(Subscription.owner_id, Subscription.expires_at, Plan.code)
            .join(Plan, Plan.id == Subscription.plan_id)
            .join(User, User.id == Subscription.owner_id)
            .where(
                Subscription.status.in_(_LIVE),
                Plan.code.in_(RENEWAL_PLAN_CODES),
                Subscription.expires_at <= now + timedelta(days=RENEWAL_OPEN_DAYS),
                Subscription.expires_at > now - timedelta(days=RENEWAL_DECLINE_DAYS),
                User.crm_owner_id.is_(None),
                User.is_staff.is_(False),
                User.is_superuser.is_(False),
                User.is_active.is_(True),
                exists().where(_paid_bill(Subscription.owner_id)),
                ~carded,
                ~worked,
            )
            .order_by(Subscription.expires_at, Subscription.owner_id)
            .limit(limit)
        )
    )
    if not rows:
        return 0
    hands = Hands(db)
    opened = 0
    for owner_id, ends_at, plan_code in rows:
        ended = ends_at <= now
        to = str(RenewalColumn.ENDED if ended else RenewalColumn.ENDING)
        card = BoardCard(
            board=BOARD,
            owner_id=owner_id,
            column_code=to,
            plan_code=plan_code,
            term_ends_at=ends_at,
            opened_at=now,
            column_since=now,
            reasons=[],
        )
        try:
            with db.begin_nested():
                db.add(card)
                db.flush()
        except IntegrityError:
            # Another run opened this term's card a moment ago.
            continue
        manager = hands.next()
        card.manager_id = manager.id if manager else None
        record(
            db,
            card=card,
            kind=EventKind.TERM_ENDED if ended else EventKind.TERM_ENDING,
            now=now,
            to_column=to,
            body=f"Obuna muddati: {date_words(ends_at)}",
            ref="opened",
        )
        opened += 1
    db.commit()
    return opened


def mark_renewed(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """The client paid Standart or Pro after the card opened: the card goes
    to Uzaytirdi from any column, Rad etdi too, and keeps the bill. Only the
    client's latest card: an older term's card is history. A bill renews one
    card."""
    later = BoardCard.__table__.alias("later")
    used = BoardCard.__table__.alias("used")
    bill = (
        select(Invoice.id)
        .where(
            _paid_bill(BoardCard.owner_id),
            Invoice.paid_at >= BoardCard.opened_at,
            ~exists().where(used.c.invoice_id == Invoice.id),
        )
        .order_by(Invoice.paid_at, Invoice.id)
        .limit(1)
        .correlate(BoardCard)
        .scalar_subquery()
    )
    rows = list(
        db.execute(
            select(BoardCard, bill)
            .where(
                BoardCard.board == BOARD,
                BoardCard.column_code != str(RenewalColumn.RENEWED),
                bill.is_not(None),
                ~exists().where(
                    later.c.board == BOARD,
                    later.c.owner_id == BoardCard.owner_id,
                    later.c.term_ends_at > BoardCard.term_ends_at,
                ),
            )
            .order_by(BoardCard.opened_at)
            .limit(limit)
            .with_for_update(of=BoardCard, skip_locked=True)
            .execution_options(populate_existing=True)
        )
    )
    for card, bill_id in rows:
        invoice = db.get(Invoice, bill_id)
        assert invoice is not None
        card.invoice_id = invoice.id
        card.closed_at = invoice.paid_at or now
        card.close_reason = ""
        card.close_note = ""
        card.due_at = None
        move(
            db,
            card=card,
            to=str(RenewalColumn.RENEWED),
            kind=EventKind.RENEWED,
            now=now,
            body=invoice.plan.name if invoice.plan else "",
            ref=f"renewed:{invoice.id}",
        )
    db.commit()
    return len(rows)


def follow_terms(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """A worked card whose client's term ends at another moment now, with no
    payment (``mark_renewed`` ran first): the office gave or took days. The
    card takes the new date and stays with its manager; one that stood in
    Tugagan while the term runs again steps back to Tugayapti."""
    taken = BoardCard.__table__.alias("taken")
    rows = list(
        db.execute(
            select(BoardCard, Subscription.expires_at)
            .join(Subscription, Subscription.owner_id == BoardCard.owner_id)
            .where(
                BoardCard.board == BOARD,
                BoardCard.closed_at.is_(None),
                Subscription.status.in_(_LIVE),
                Subscription.plan_id.in_(_renewal_plans()),
                Subscription.expires_at != BoardCard.term_ends_at,
                ~exists().where(
                    taken.c.board == BOARD,
                    taken.c.owner_id == BoardCard.owner_id,
                    taken.c.term_ends_at == Subscription.expires_at,
                ),
            )
            .order_by(BoardCard.opened_at)
            .limit(limit)
            .with_for_update(of=BoardCard, skip_locked=True)
            .execution_options(populate_existing=True)
        )
    )
    for card, ends_at in rows:
        card.term_ends_at = ends_at
        body = f"Yangi muddat: {date_words(ends_at)}"
        if card.column_code == RenewalColumn.ENDED and ends_at > now:
            move(
                db,
                card=card,
                to=str(RenewalColumn.ENDING),
                kind=EventKind.TERM_MOVED,
                now=now,
                body=body,
            )
        else:
            record(db, card=card, kind=EventKind.TERM_MOVED, now=now, body=body)
    db.commit()
    return len(rows)


def mark_ended(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """The term ended and the card still stands in Tugayapti: to Tugagan. A
    card the manager moved on stays where they put it."""
    rows = list(
        db.scalars(
            select(BoardCard)
            .where(
                BoardCard.board == BOARD,
                BoardCard.closed_at.is_(None),
                BoardCard.column_code == str(RenewalColumn.ENDING),
                BoardCard.term_ends_at <= now,
            )
            .order_by(BoardCard.term_ends_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    )
    for card in rows:
        move(
            db,
            card=card,
            to=str(RenewalColumn.ENDED),
            kind=EventKind.TERM_ENDED,
            now=now,
        )
    db.commit()
    return len(rows)


def _open_bills(now: datetime) -> Any:
    """Standart and Pro bills a client opened and may still pay."""
    from app.modules.boards.view import open_bills

    return open_bills(now).where(Invoice.plan_id.in_(_renewal_plans())).subquery()


def bills_opened(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """The client opened a Standart or Pro bill: the card goes to «To'lov
    kutilmoqda». Once per bill, so a card the manager moved on stays."""
    bills = _open_bills(now)
    seen = exists().where(
        BoardCardEvent.card_id == BoardCard.id,
        BoardCardEvent.ref == func.concat("bill:", bills.c.id),
    )
    rows = list(
        db.execute(
            select(BoardCard, bills.c.id)
            .join(bills, bills.c.owner_id == BoardCard.owner_id)
            .where(
                BoardCard.board == BOARD,
                BoardCard.closed_at.is_(None),
                BoardCard.column_code.in_(RENEWAL_BILL_FROM),
                ~seen,
            )
            .order_by(bills.c.created_at)
            .limit(limit)
            .with_for_update(of=BoardCard, skip_locked=True)
            .execution_options(populate_existing=True)
        )
    )
    moved: set[uuid.UUID] = set()
    for card, bill_id in rows:
        if card.id in moved:
            continue
        moved.add(card.id)
        move(
            db,
            card=card,
            to=str(RenewalColumn.AWAITING),
            kind=EventKind.BILL_OPENED,
            now=now,
            ref=f"bill:{bill_id}",
        )
    db.commit()
    return len(moved)


def bills_unpaid(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """A card its client's bill put in «To'lov kutilmoqda», and no bill of
    theirs can be paid any more: to «Qayta aloqa», due now, so the manager
    calls. A card the manager put there with «To'laydi» is theirs to move.
    Runs after ``mark_renewed``: who paid is in Uzaytirdi, not here."""
    bills = _open_bills(now)
    by_bill = (
        select(BoardCardEvent.ref)
        .where(
            BoardCardEvent.card_id == BoardCard.id,
            BoardCardEvent.kind == str(EventKind.BILL_OPENED),
            BoardCardEvent.created_at >= BoardCard.column_since,
        )
        .limit(1)
        .correlate(BoardCard)
        .scalar_subquery()
    )
    rows = list(
        db.execute(
            select(BoardCard, by_bill)
            .where(
                BoardCard.board == BOARD,
                BoardCard.closed_at.is_(None),
                BoardCard.column_code == str(RenewalColumn.AWAITING),
                by_bill.is_not(None),
                ~exists().where(bills.c.owner_id == BoardCard.owner_id),
            )
            .order_by(BoardCard.column_since)
            .limit(limit)
            .with_for_update(of=BoardCard, skip_locked=True)
            .execution_options(populate_existing=True)
        )
    )
    for card, ref in rows:
        if card.due_at is None or card.due_at > now:
            card.due_at = now
        move(
            db,
            card=card,
            to=str(RenewalColumn.CALLBACK),
            kind=EventKind.BILL_UNPAID,
            now=now,
            ref=str(ref).replace("bill:", "unpaid:", 1),
        )
    db.commit()
    return len(rows)


def decline_silent(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """Thirty days after the term ended and nobody reached the client (the
    card is in Tugagan or Bog'lanilmadi): to Rad etdi, «javob bermadi»."""
    rows = list(
        db.scalars(
            select(BoardCard)
            .where(
                BoardCard.board == BOARD,
                BoardCard.closed_at.is_(None),
                BoardCard.column_code.in_(RENEWAL_SILENT_COLUMNS),
                BoardCard.term_ends_at <= now - timedelta(days=RENEWAL_DECLINE_DAYS),
            )
            .order_by(BoardCard.term_ends_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    )
    for card in rows:
        card.closed_at = now
        card.close_reason = str(DeclineReason.NO_ANSWER)
        card.close_note = ""
        card.due_at = None
        move(
            db,
            card=card,
            to=str(RenewalColumn.DECLINED),
            kind=EventKind.SILENT,
            now=now,
        )
    db.commit()
    return len(rows)


def sweep(db: Session, *, now: datetime) -> int:
    ensure_board(db, board=Board.RENEWAL, now=now)
    db.commit()
    done = mark_renewed(db, now=now)
    done += follow_terms(db, now=now)
    done += open_cards(db, now=now)
    done += hand_out(db, now=now)
    done += mark_ended(db, now=now)
    done += bills_opened(db, now=now)
    done += bills_unpaid(db, now=now)
    done += decline_silent(db, now=now)
    return done


# -- what the manager does ----------------------------------------------------

_MOVES: dict[CardAction, tuple[RenewalColumn, EventKind]] = {
    CardAction.CONTACTED: (RenewalColumn.CONTACTED, EventKind.CONTACTED),
    CardAction.NO_CONTACT: (RenewalColumn.NO_CONTACT, EventKind.NO_CONTACT),
    CardAction.CALLBACK: (RenewalColumn.CALLBACK, EventKind.CALLBACK),
    CardAction.WILL_PAY: (RenewalColumn.AWAITING, EventKind.WILL_PAY),
    CardAction.DECLINE: (RenewalColumn.DECLINED, EventKind.DECLINED),
}


def act(
    db: Session,
    *,
    card: BoardCard,
    user: User,
    action: CardAction,
    reason: str,
    note: str,
    due: datetime | None,
    said: str,
    now: datetime,
) -> BoardCard:
    """One button of a renewal card. «Rad etdi» asks for its reason, and
    «Boshqa» for the words; «Bog'lanib bo'lmadi» counts the attempt."""
    if card.closed_at is not None:
        raise CardClosed
    if action not in RENEWAL_ACTIONS.get(card.column_code, ()):
        raise ActionNotHere
    body = said
    if action == CardAction.DECLINE:
        if reason not in DeclineReason.values:
            raise ReasonRequired
        if reason == DeclineReason.OTHER and not note:
            raise NoteRequired
        card.close_reason = reason
        card.close_note = note
        card.closed_at = now
        label = str(DECLINE_REASON_LABELS[DeclineReason(reason)])
        body = f"{label}. {note}" if note else label
    elif action == CardAction.CONTACTED:
        card.contact_mark = str(CardAction.CONTACTED)
    elif action == CardAction.NO_CONTACT:
        card.contact_mark = str(CardAction.NO_CONTACT)
        card.attempts = min(card.attempts + 1, ATTEMPTS_MAX)
    to, kind = _MOVES[action]
    card.due_at = due
    move(db, card=card, to=str(to), kind=kind, now=now, actor=user, body=body)
    db.commit()
    return card


def manager_view(db: Session) -> dict[str, Any]:
    manager = default_manager(db)
    return {
        "manager": {
            "id": str(manager.id),
            "name": manager.full_name or manager.email,
            "email": manager.email,
        }
        if manager
        else None
    }


def set_manager(
    db: Session, *, to_id: uuid.UUID | None, actor: User, now: datetime
) -> int:
    """The manager every new card goes to. The cards still worked pass to
    the new one; the finished ones keep who worked them. Empty: new cards
    are shared among everybody with the board's role. How many cards changed hands."""
    ensure_board(db, board=Board.RENEWAL, now=now)
    setting = db.scalar(
        select(BoardSetting).where(BoardSetting.board == BOARD).with_for_update()
    )
    assert setting is not None
    if to_id is None:
        setting.manager_id = None
        db.commit()
        return 0
    manager = db.get(User, to_id)
    if manager is None or not works_on(db, manager, Board.RENEWAL):
        raise NotOnBoard
    setting.manager_id = manager.id
    cards = list(
        db.scalars(
            select(BoardCard)
            .where(
                BoardCard.board == BOARD,
                BoardCard.closed_at.is_(None),
                BoardCard.manager_id.is_distinct_from(manager.id),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    for card in cards:
        card.manager_id = manager.id
        record(
            db,
            card=card,
            kind=EventKind.ASSIGNED,
            now=now,
            actor=actor,
            body=manager.full_name or manager.email,
        )
    db.commit()
    return len(cards)


# -- what a card and the board show --------------------------------------------


def briefs(
    db: Session, cards: list[BoardCard], *, now: datetime
) -> dict[uuid.UUID, dict[str, Any]]:
    """What a renewal card shows besides the client: the plan and the term,
    the pages, this month's adverts, spend and applications, and how many
    times they paid. A fixed number of queries whatever the cards."""
    from app.modules.backoffice.selectors.customers import activity_of
    from app.modules.integrations.models import PageAccount

    mine = [card for card in cards if card.board == BOARD]
    if not mine:
        return {}
    owners = list({card.owner_id for card in mine})
    plans = dict(
        db.execute(
            select(Plan.code, Plan.name).where(
                Plan.code.in_({card.plan_code for card in mine})
            )
        ).all()
    )
    pages: dict[uuid.UUID, list[str]] = {}
    for owner_id, name in db.execute(
        select(PageAccount.owner_id, PageAccount.name)
        .where(PageAccount.owner_id.in_(owners), PageAccount.is_active.is_(True))
        .order_by(PageAccount.is_current.desc(), PageAccount.name)
    ):
        if name and name not in pages.setdefault(owner_id, []):
            pages[owner_id].append(name)
    payments = dict(
        db.execute(
            select(Invoice.owner_id, func.count(Invoice.id))
            .where(
                Invoice.owner_id.in_(owners),
                Invoice.kind == str(InvoiceKind.PLAN),
                Invoice.status == str(InvoiceStatus.PAID),
            )
            .group_by(Invoice.owner_id)
        ).all()
    )
    bills = {
        bill.id: bill
        for bill in db.scalars(
            select(Invoice).where(
                Invoice.id.in_([card.invoice_id for card in mine if card.invoice_id])
            )
        )
    }
    activity = activity_of(db, owners, now=now)
    out: dict[uuid.UUID, dict[str, Any]] = {}
    for card in mine:
        ends_at = card.term_ends_at
        assert ends_at is not None
        seen = activity.get(card.owner_id)
        bill = bills.get(card.invoice_id) if card.invoice_id else None
        out[card.id] = {
            "plan_code": card.plan_code,
            "plan_name": str(plans.get(card.plan_code, card.plan_code)),
            "term_ends_at": ends_at,
            "ended": ends_at <= now,
            "days": days_between(ends_at, now),
            "pages": pages.get(card.owner_id, []),
            "ads_running": seen.running if seen else 0,
            "leads_month": seen.leads if seen else 0,
            "spend_month": [
                {"currency": currency, "minor": minor}
                for currency, minor in (seen.spend if seen else ())
            ],
            "payments": int(payments.get(card.owner_id, 0)),
            "last_login": card.owner.last_login,
            "decline_reason": card.close_reason,
            "decline_label": decline_label(card.close_reason),
            "paid": {"minor": bill.amount_minor, "currency": bill.currency}
            if bill
            else None,
        }
    return out


def days_between(ends_at: datetime, now: datetime) -> int:
    """Whole days to the term's end, rounded up; after it, whole days since,
    as a negative number: 0 on the day itself."""
    seconds = (ends_at - now).total_seconds()
    if seconds > 0:
        return int(-(-seconds // 86_400))
    return -int(-seconds // 86_400)


def decline_label(code: str) -> str:
    if code in DeclineReason.values:
        return str(DECLINE_REASON_LABELS[DeclineReason(code)])
    return ""


def order(code: str, now: datetime) -> tuple[Any, ...]:
    """Qayta aloqa by its set time, the late ones on top. Uzaytirdi and Rad
    etdi by when they got there. Elsewhere by the term: the fewest days left
    first, then the most recently ended."""
    if code == RenewalColumn.CALLBACK:
        return (
            BoardCard.due_at.asc().nulls_last(),
            BoardCard.term_ends_at,
            BoardCard.id,
        )
    if code in (RenewalColumn.RENEWED, RenewalColumn.DECLINED):
        return (BoardCard.column_since.desc(), BoardCard.id)
    running = BoardCard.term_ends_at > now
    away = func.abs(func.extract("epoch", BoardCard.term_ends_at - now))
    return (running.desc(), away.asc(), BoardCard.id)


def day_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """The office's days ``start`` to ``end``, both whole."""
    zone = localtime(utcnow()).tzinfo
    first = datetime.combine(start, time.min, zone)
    return first, datetime.combine(end, time.min, zone) + timedelta(days=1)


def report(
    db: Session, *, user: User, access: Access, start: date, end: date
) -> dict[str, Any]:
    """The terms that came due in the period, by plan: how many, how many
    renewed and the share, the money the renewals brought, how many
    declined and why. A manager's report counts their own cards."""
    if end < start or (end - start).days > REPORT_MAX_DAYS:
        raise ReportPeriodInvalid
    first, after = day_bounds(start, end)
    scope = [
        BoardCard.board == BOARD,
        BoardCard.term_ends_at >= first,
        BoardCard.term_ends_at < after,
    ]
    if not access.leads_board(Board.RENEWAL):
        scope.append(BoardCard.manager_id == user.id)
    counts: dict[str, dict[str, int]] = {}
    for plan_code, column, total in db.execute(
        select(BoardCard.plan_code, BoardCard.column_code, func.count())
        .where(*scope)
        .group_by(BoardCard.plan_code, BoardCard.column_code)
    ):
        counts.setdefault(plan_code, {})[column] = int(total)
    money: dict[str, dict[str, int]] = {}
    for plan_code, currency, total in db.execute(
        select(BoardCard.plan_code, Invoice.currency, func.sum(Invoice.amount_minor))
        .join(Invoice, Invoice.id == BoardCard.invoice_id)
        .where(*scope, BoardCard.column_code == str(RenewalColumn.RENEWED))
        .group_by(BoardCard.plan_code, Invoice.currency)
    ):
        money.setdefault(plan_code, {})[currency] = int(total or 0)
    reasons: dict[str, dict[str, int]] = {}
    for plan_code, reason, total in db.execute(
        select(BoardCard.plan_code, BoardCard.close_reason, func.count())
        .where(*scope, BoardCard.column_code == str(RenewalColumn.DECLINED))
        .group_by(BoardCard.plan_code, BoardCard.close_reason)
    ):
        reasons.setdefault(plan_code, {})[reason] = int(total)
    names = dict(
        db.execute(
            select(Plan.code, Plan.name).where(Plan.code.in_(RENEWAL_PLAN_CODES))
        ).all()
    )

    def line(code: str, name: str, codes: tuple[str, ...]) -> dict[str, Any]:
        by_column: dict[str, int] = {}
        paid: dict[str, int] = {}
        why: dict[str, int] = {}
        for plan_code in codes:
            for column, total in counts.get(plan_code, {}).items():
                by_column[column] = by_column.get(column, 0) + total
            for currency, total in money.get(plan_code, {}).items():
                paid[currency] = paid.get(currency, 0) + total
            for reason, total in reasons.get(plan_code, {}).items():
                why[reason] = why.get(reason, 0) + total
        due = sum(by_column.values())
        renewed = by_column.get(str(RenewalColumn.RENEWED), 0)
        declined = by_column.get(str(RenewalColumn.DECLINED), 0)
        return {
            "code": code,
            "name": name,
            "due": due,
            "renewed": renewed,
            "declined": declined,
            "open": due - renewed - declined,
            "rate": round(renewed * 100 / due) if due else 0,
            "paid": [
                {"currency": currency, "minor": minor}
                for currency, minor in sorted(paid.items(), key=lambda p: -p[1])
            ],
            "reasons": [
                {
                    "code": str(reason),
                    "label": str(DECLINE_REASON_LABELS[reason]),
                    "count": why.get(str(reason), 0),
                }
                for reason in DeclineReason
                if why.get(str(reason), 0)
            ],
        }

    return {
        "date_from": start,
        "date_to": end,
        "total": line("", "Jami", RENEWAL_PLAN_CODES),
        "plans": [
            line(code, str(names.get(code, code.title())), (code,))
            for code in RENEWAL_PLAN_CODES
        ],
    }
