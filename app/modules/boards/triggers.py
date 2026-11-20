"""What moves cards on its own. Each rule reads the database since the
board went live and writes each fact once, so running it again changes
nothing."""

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Date, and_, cast, exists, func, or_, select, tuple_
from sqlalchemy.orm import Session, aliased

from app.modules.accounts.models import User
from app.modules.ads.constants import LAUNCH_LOG_PREFIX, Delivery, LaunchStatus
from app.modules.ads.failure_kinds import (
    META_CODE_WORDS,
    META_PROVIDER,
    PASSING_CODES,
    SYSTEM_CODES,
)
from app.modules.ads.models import Campaign, CampaignLaunch, GoogleLaunch
from app.modules.audit.constants import (
    ACTION_TYPE_LABELS,
    ActionStatus,
    ActionType,
    ActorType,
)
from app.modules.audit.models import ActionLog
from app.modules.billing.constants import (
    DEFAULT_PLAN_CODE,
    LIVE_SUBSCRIPTION_STATUSES,
    InvoiceKind,
    InvoiceStatus,
    SubscriptionStatus,
)
from app.modules.billing.models import Invoice, Plan, Subscription
from app.modules.boards import confirm, notices
from app.modules.boards.constants import (
    BILL_FROM_COLUMNS,
    CAMPAIGN_FRESH_HOURS,
    IDLE_NO_LAUNCH_DAYS,
    META_ERROR_WAIT_MINUTES,
    NO_SPEND_HOURS,
    NO_SPEND_LOOKBACK_DAYS,
    NOTE_MAX,
    OFFER_COLUMNS,
    OFFER_HOURS,
    OFFER_STEPS,
    SALES_NOTES_CARRIED,
    SETUP_GRACE_MINUTES,
    START_TALKED_COLUMNS,
    SURVEY_LOOKBACK_HOURS,
    SWEEP_BATCH,
    Board,
    EventKind,
    SalesColumn,
    SupportColumn,
    TicketReason,
)
from app.modules.boards.models import BoardCard, BoardCardEvent, SurveyHelpOption
from app.modules.boards.offer import (
    OFFERED_REF,
    column_at,
    start_paid_at,
)
from app.modules.boards.selectors import ensure_board, live_since
from app.modules.boards.services import move, record
from app.modules.boards.tickets import raise_ticket
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.models import MetricsDaily
from app.modules.surveys.models import SurveyQuestion, SurveyResponse

# Paid once already: such a client is not a first-time sign-up.
_PAID_BEFORE = (str(InvoiceStatus.PAID), str(InvoiceStatus.REFUNDED))
# What a Start payment leaves of an older «Sotildi» line: the client is a
# lead again, and the full plan they buy later is the sale.
_SOLD_REF = "sold"
_SOLD_BY_START_REF = "sold:start"


def _full_plans() -> Any:
    """The plans whose payment is a sale: not Start, not a one-time one."""
    return select(Plan.id).where(
        Plan.code != DEFAULT_PLAN_CODE, Plan.is_one_time.is_(False)
    )


def open_leads(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """A Sales card in Ishlanmagan for everybody who signed up after the
    board went live and has not paid. Staff, CRM logins and blocked
    accounts are not leads; nor is an account given a running plan."""
    since = live_since(db, board=Board.SALES)
    if since is None:
        return 0
    # A plan paid for, as «Sotildi» and a lead added by hand read it: a
    # wallet top-up or a seat alone leaves the sign-up a lead.
    paid = exists().where(
        Invoice.owner_id == User.id,
        Invoice.kind == str(InvoiceKind.PLAN),
        Invoice.status.in_(_PAID_BEFORE),
    )
    running = exists().where(
        Subscription.owner_id == User.id,
        Subscription.status == str(SubscriptionStatus.ACTIVE),
    )
    carded = exists().where(
        BoardCard.owner_id == User.id, BoardCard.board == str(Board.SALES)
    )
    people = list(
        db.scalars(
            select(User)
            .where(
                User.date_joined >= since,
                User.crm_owner_id.is_(None),
                User.is_staff.is_(False),
                User.is_superuser.is_(False),
                User.is_active.is_(True),
                ~paid,
                ~running,
                ~carded,
            )
            .order_by(User.date_joined, User.id)
            .limit(limit)
        )
    )
    for person in people:
        card = BoardCard(
            board=str(Board.SALES),
            owner_id=person.id,
            column_code=str(SalesColumn.UNWORKED),
            opened_at=person.date_joined,
            column_since=now,
            reasons=[],
        )
        db.add(card)
        db.flush()
        record(
            db,
            card=card,
            kind=EventKind.OPENED,
            now=now,
            to_column=card.column_code,
            ref="opened",
        )
    db.commit()
    return len(people)


def mark_sold(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """A Sales card whose client paid a full plan goes to Sotildi from any
    column, Yopildi too: the payment is what happened. Start is not a sale:
    its buyer stays a lead (``start_bought``). Once: a card the Owner moved
    out of Sotildi by hand stays where they put it, and its second ``sold``
    line would break the one-fact-once index and the batch."""
    sold_before = exists().where(
        BoardCardEvent.card_id == BoardCard.id, BoardCardEvent.ref == "sold"
    )
    first_paid = (
        select(Invoice.owner_id, func.min(Invoice.paid_at).label("paid_at"))
        .where(
            Invoice.status == str(InvoiceStatus.PAID),
            Invoice.kind == str(InvoiceKind.PLAN),
            Invoice.plan_id.in_(_full_plans()),
        )
        .group_by(Invoice.owner_id)
        .subquery()
    )
    rows = list(
        db.execute(
            select(BoardCard, first_paid.c.paid_at)
            .join(first_paid, first_paid.c.owner_id == BoardCard.owner_id)
            .where(
                BoardCard.board == str(Board.SALES),
                BoardCard.column_code != str(SalesColumn.SOLD),
                ~sold_before,
            )
            .order_by(BoardCard.opened_at)
            .limit(limit)
            .with_for_update(of=BoardCard, skip_locked=True)
            .execution_options(populate_existing=True)
        )
    )
    for card, paid_at in rows:
        card.closed_at = paid_at or now
        card.close_reason = ""
        card.due_at = None
        move(
            db,
            card=card,
            to=str(SalesColumn.SOLD),
            kind=EventKind.SOLD,
            now=now,
            ref="sold",
        )
    db.commit()
    return len(rows) + _mark_given(db, now=now, limit=limit)


def _mark_given(db: Session, *, now: datetime, limit: int) -> int:
    """A lead the office gave a plan to, with no bill paid: a client now,
    so the card leaves the managers' columns for Sotildi too, and its line
    says the plan was given. Once, like a payment."""
    sold_before = exists().where(
        BoardCardEvent.card_id == BoardCard.id, BoardCardEvent.ref == "sold"
    )
    given = (
        select(Subscription.owner_id, func.min(Subscription.started_at).label("at"))
        .where(
            Subscription.status == str(SubscriptionStatus.ACTIVE),
            Subscription.activated_by_id.is_not(None),
            Subscription.plan_id.in_(_full_plans()),
        )
        .group_by(Subscription.owner_id)
        .subquery()
    )
    rows = list(
        db.execute(
            select(BoardCard, given.c.at)
            .join(given, given.c.owner_id == BoardCard.owner_id)
            .where(
                BoardCard.board == str(Board.SALES),
                BoardCard.column_code != str(SalesColumn.SOLD),
                ~sold_before,
            )
            .order_by(BoardCard.opened_at)
            .limit(limit)
            .with_for_update(of=BoardCard, skip_locked=True)
            .execution_options(populate_existing=True)
        )
    )
    for card, at in rows:
        card.closed_at = at or now
        card.close_reason = ""
        card.due_at = None
        move(
            db,
            card=card,
            to=str(SalesColumn.SOLD),
            kind=EventKind.SOLD,
            now=now,
            body="Tarif ofisdan berildi, to'lovsiz.",
            ref="sold",
        )
    db.commit()
    return len(rows)


def start_bought(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """A client paid Start: their discount on a full plan starts at that
    payment (``offer``), but the card reaches a discount column only once a
    manager talked to them. So a client without a card gets one in
    Ishlanmagan; a closed card (or one the old rule sold on this payment)
    opens there again, with nobody on it; a card the manager talked on
    (Bog'lanildi, or a discount column on an earlier talk's clock) goes to
    the column this payment's clock stands at; any other card stays where it
    is, with a line. Once per payment, while the discount still runs."""
    paid = start_paid_at().subquery()
    start_bill = (
        select(Invoice.id)
        .join(Plan, Plan.id == Invoice.plan_id)
        .where(
            Invoice.owner_id == paid.c.owner_id,
            Invoice.paid_at == paid.c.at,
            Invoice.kind == str(InvoiceKind.PLAN),
            Invoice.status == str(InvoiceStatus.PAID),
            Plan.code == DEFAULT_PLAN_CODE,
        )
        .order_by(Invoice.id)
        .limit(1)
        .correlate(paid)
        .scalar_subquery()
    )
    seen = exists().where(
        BoardCardEvent.owner_id == paid.c.owner_id,
        BoardCardEvent.ref == func.concat("start:", start_bill),
    )
    bought = exists().where(
        Invoice.owner_id == paid.c.owner_id,
        Invoice.kind == str(InvoiceKind.PLAN),
        Invoice.status.in_(_PAID_BEFORE),
        Invoice.plan_id.in_(_full_plans()),
    )
    rows = list(
        db.execute(
            select(User.id, paid.c.at, start_bill)
            .join(paid, paid.c.owner_id == User.id)
            .where(
                paid.c.at > now - timedelta(hours=OFFER_HOURS),
                User.crm_owner_id.is_(None),
                User.is_staff.is_(False),
                User.is_superuser.is_(False),
                User.is_active.is_(True),
                ~seen,
                ~bought,
            )
            .order_by(paid.c.at)
            .limit(limit)
        )
    )
    moved = 0
    for owner_id, paid_at, bill_id in rows:
        to = column_at(paid_at, now)
        if to is None:
            continue
        card = db.scalar(
            select(BoardCard)
            .where(BoardCard.board == str(Board.SALES), BoardCard.owner_id == owner_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        ref = f"start:{bill_id}"
        if card is None:
            if _has_card(db, owner_id=owner_id):
                # Somebody holds the card this second: the next minute's.
                continue
            card = BoardCard(
                board=str(Board.SALES),
                owner_id=owner_id,
                column_code=str(SalesColumn.UNWORKED),
                opened_at=paid_at,
                column_since=now,
                reasons=[],
            )
            db.add(card)
            db.flush()
            record(
                db,
                card=card,
                kind=EventKind.START_BOUGHT,
                now=now,
                to_column=card.column_code,
                ref=ref,
            )
            moved += 1
            continue
        if card.closed_at is not None:
            # The old rule sold the card on this payment; it is a lead again,
            # and the full plan paid later writes the sale.
            for line in db.scalars(
                select(BoardCardEvent).where(
                    BoardCardEvent.card_id == card.id, BoardCardEvent.ref == _SOLD_REF
                )
            ):
                line.ref = _SOLD_BY_START_REF
            card.closed_at = None
            card.close_reason = ""
            card.close_note = ""
            card.manager_id = None
            card.due_at = None
            to = str(SalesColumn.UNWORKED)
        elif card.column_code not in START_TALKED_COLUMNS:
            # Not talked to yet: the card waits where it is for the talk.
            record(db, card=card, kind=EventKind.START_BOUGHT, now=now, ref=ref)
            moved += 1
            continue
        if to == card.column_code:
            record(db, card=card, kind=EventKind.START_BOUGHT, now=now, ref=ref)
        else:
            move(db, card=card, to=to, kind=EventKind.START_BOUGHT, now=now, ref=ref)
        moved += 1
    db.commit()
    return moved


def _has_card(db: Session, *, owner_id: uuid.UUID) -> bool:
    return bool(
        db.scalar(
            select(
                exists().where(
                    BoardCard.board == str(Board.SALES), BoardCard.owner_id == owner_id
                )
            )
        )
    )


def step_offers(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """A discount card follows its clock: 20% → 10% a day after the start;
    when the fourth day ends the discount is over and the card goes to
    Bog'lanildi, still its manager's (to Ishlanmagan if nobody has it). The
    clock is the client's Start payment, or without one the manager's talk.
    Runs after ``mark_sold``, so a client who paid is in Sotildi, not here."""
    paid = start_paid_at().subquery()
    by_start = (
        select(paid.c.at)
        .where(paid.c.owner_id == BoardCard.owner_id)
        .correlate(BoardCard)
        .scalar_subquery()
    )
    by_talk = (
        select(BoardCardEvent.created_at)
        .where(
            BoardCardEvent.card_id == BoardCard.id, BoardCardEvent.ref == OFFERED_REF
        )
        .correlate(BoardCard)
        .scalar_subquery()
    )
    started = func.coalesce(by_start, by_talk)
    # Only cards whose clock left their column: a step's column once its
    # hours are past, any once the last step is.
    due = [
        and_(
            BoardCard.column_code == str(column),
            started <= now - timedelta(hours=hours),
        )
        for _percent, hours, column in OFFER_STEPS
    ]
    rows = list(
        db.execute(
            select(BoardCard, started)
            .where(
                BoardCard.board == str(Board.SALES),
                BoardCard.closed_at.is_(None),
                BoardCard.column_code.in_(OFFER_COLUMNS),
                or_(started.is_(None), *due),
            )
            .order_by(BoardCard.column_since)
            .limit(limit)
            .with_for_update(of=BoardCard, skip_locked=True)
            .execution_options(populate_existing=True)
        )
    )
    moved = 0
    for card, at in rows:
        to = column_at(at, now) if at is not None else None
        if to == card.column_code:
            continue
        if to is not None:
            move(db, card=card, to=to, kind=EventKind.OFFER_STEP, now=now)
        else:
            to = str(SalesColumn.CONTACTED if card.manager_id else SalesColumn.UNWORKED)
            move(db, card=card, to=to, kind=EventKind.OFFER_ENDED, now=now)
        moved += 1
    db.commit()
    return moved


def bills_opened(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """A client a manager works opened a plan bill: the card goes to
    «To'lov kutilmoqda». Once per bill, so a card the manager moved on stays
    where they put it. Not from a discount column: the bill reads the
    discount from the column, and the card must stay in it."""
    from app.modules.boards.view import open_bills

    bills = open_bills(now).subquery()
    seen = exists().where(
        BoardCardEvent.card_id == BoardCard.id,
        BoardCardEvent.ref == func.concat("bill:", bills.c.id),
    )
    rows = list(
        db.execute(
            select(BoardCard, bills.c.id)
            .join(bills, bills.c.owner_id == BoardCard.owner_id)
            .where(
                BoardCard.board == str(Board.SALES),
                BoardCard.closed_at.is_(None),
                BoardCard.manager_id.is_not(None),
                BoardCard.column_code.in_(BILL_FROM_COLUMNS),
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
        # Two bills of one client in a batch: the first moved the card.
        if card.id in moved:
            continue
        moved.add(card.id)
        move(
            db,
            card=card,
            to=str(SalesColumn.AWAITING),
            kind=EventKind.BILL_OPENED,
            now=now,
            ref=f"bill:{bill_id}",
        )
    db.commit()
    return len(moved)


def bills_unpaid(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """A card its client's bill put in «To'lov kutilmoqda», and no bill of
    theirs can be paid any more: back to «Qayta aloqa», due now, so the
    manager calls. A card the manager put there with «To'laydi» is theirs to
    move. Runs after ``mark_sold``: who paid is in Sotildi, not here."""
    from app.modules.boards.view import open_bills

    bills = open_bills(now).subquery()
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
                BoardCard.board == str(Board.SALES),
                BoardCard.closed_at.is_(None),
                BoardCard.column_code == str(SalesColumn.AWAITING),
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
            to=str(SalesColumn.CALLBACK),
            kind=EventKind.BILL_UNPAID,
            now=now,
            ref=str(ref).replace("bill:", "unpaid:", 1),
        )
    db.commit()
    return len(rows)


def sweep_sales(db: Session, *, now: datetime) -> tuple[int, int]:
    ensure_board(db, board=Board.SALES, now=now)
    db.commit()
    opened, sold = open_leads(db, now=now), mark_sold(db, now=now)
    moved = start_bought(db, now=now) + step_offers(db, now=now)
    moved += bills_opened(db, now=now) + bills_unpaid(db, now=now)
    return opened, sold + moved


def _since(db: Session) -> datetime | None:
    return live_since(db, board=Board.SUPPORT)


def setup_late(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """Paid a plan an hour ago or more and still not set up. One fact per
    payment, so a renewal that finds the setup undone counts again."""
    since = _since(db)
    if since is None:
        return 0
    rows = list(
        db.execute(
            select(Invoice.id, Invoice.owner_id)
            .join(Subscription, Subscription.owner_id == Invoice.owner_id)
            .where(
                Invoice.status == str(InvoiceStatus.PAID),
                Invoice.kind == str(InvoiceKind.PLAN),
                Invoice.paid_at >= since,
                Invoice.paid_at <= now - timedelta(minutes=SETUP_GRACE_MINUTES),
                Subscription.status.in_([str(s) for s in LIVE_SUBSCRIPTION_STATUSES]),
                Subscription.setup_completed_at.is_(None),
                ~_has_ref(Invoice.owner_id, func.concat("setup:", Invoice.id)),
            )
            .order_by(Invoice.paid_at)
            .limit(limit)
        )
    )
    written = sum(
        raise_ticket(
            db,
            owner_id=owner_id,
            reason=TicketReason.SETUP,
            ref=f"setup:{invoice_id}",
            now=now,
            detail="To'lovdan 1 soat o'tdi, sozlash tugamagan.",
        )
        for invoice_id, owner_id in rows
        if owner_id is not None
    )
    db.commit()
    return written + _setup_late_given(db, since=since, now=now, limit=limit)


def _setup_late_given(
    db: Session, *, since: datetime, now: datetime, limit: int
) -> int:
    """The same hour for a plan the office gave: no bill names it, so the
    subscription itself is the fact."""
    billed = exists().where(
        Invoice.owner_id == Subscription.owner_id,
        Invoice.status == str(InvoiceStatus.PAID),
        Invoice.kind == str(InvoiceKind.PLAN),
        Invoice.paid_at >= since,
    )
    rows = list(
        db.execute(
            select(Subscription.id, Subscription.owner_id)
            .where(
                Subscription.status == str(SubscriptionStatus.ACTIVE),
                Subscription.activated_by_id.is_not(None),
                Subscription.setup_completed_at.is_(None),
                Subscription.started_at >= since,
                Subscription.started_at <= now - timedelta(minutes=SETUP_GRACE_MINUTES),
                ~billed,
                ~_has_ref(
                    Subscription.owner_id, func.concat("setup:given:", Subscription.id)
                ),
            )
            .order_by(Subscription.started_at)
            .limit(limit)
        )
    )
    written = sum(
        raise_ticket(
            db,
            owner_id=owner_id,
            reason=TicketReason.SETUP,
            ref=f"setup:given:{subscription_id}",
            now=now,
            detail="Tarif ofisdan berilganiga 1 soat o'tdi, sozlash tugamagan.",
        )
        for subscription_id, owner_id in rows
    )
    db.commit()
    return written


def from_sales(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """A client Sales marked «Support kerak» paid: the ticket opens now,
    not an hour later. Start is a payment too: its buyer is using the
    system, so the mark on their card opens the ticket at once."""
    if _since(db) is None:
        return 0
    paid = exists().where(
        Invoice.owner_id == BoardCard.owner_id,
        Invoice.kind == str(InvoiceKind.PLAN),
        Invoice.status == str(InvoiceStatus.PAID),
    )
    rows = list(
        db.execute(
            select(BoardCard.id, BoardCard.owner_id, BoardCard.manager_id)
            .where(
                BoardCard.board == str(Board.SALES),
                or_(BoardCard.column_code == str(SalesColumn.SOLD), paid),
                BoardCard.needs_support.is_(True),
                ~_has_ref(BoardCard.owner_id, func.concat("sales:", BoardCard.id)),
            )
            .limit(limit)
        )
    )
    written = sum(
        raise_ticket(
            db,
            owner_id=owner_id,
            reason=TicketReason.FROM_SALES,
            ref=f"sales:{card_id}",
            now=now,
            detail=_sales_words(db, card_id=card_id, manager_id=manager_id),
        )
        for card_id, owner_id, manager_id in rows
    )
    db.commit()
    return written


def _sales_words(
    db: Session, *, card_id: uuid.UUID, manager_id: uuid.UUID | None
) -> str:
    """What Support reads on a ticket from Sales: who sold, and what they
    wrote on the lead. Support cannot open the Sales card itself."""
    manager = db.get(User, manager_id) if manager_id else None
    who = (manager.full_name or manager.email) if manager else ""
    head = (
        f"Sotuv menejeri {who}: mijoz yordam so'radi va to'ladi."
        if who
        else "Sotuv menejeri: mijoz yordam so'radi va to'ladi."
    )
    notes = list(
        db.scalars(
            select(BoardCardEvent.body)
            .where(
                BoardCardEvent.card_id == card_id,
                BoardCardEvent.kind.in_(
                    [str(EventKind.NOTE), str(EventKind.SUPPORT_ON)]
                ),
                BoardCardEvent.body != "",
            )
            .order_by(BoardCardEvent.created_at.desc(), BoardCardEvent.id)
            .limit(SALES_NOTES_CARRIED)
        )
    )
    if not notes:
        return head
    lines = "\n".join(f"- {note}" for note in reversed(notes))
    return f"{head}\nMenejer izohlari:\n{lines}"[:NOTE_MAX]


def meta_errors(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """A launch Meta refused or that was rolled back, and a press of the
    client's own on Meta that Meta refused. Each waits half an hour first:
    a launch created on a later try, or the same press done since, is no
    ticket. Only Meta's refusals: what passes on its own and our own faults
    (those go to the Developers) are not here. The system's own presses,
    a launch's own row in the action log, Google and dry runs neither.
    The same press refused for the same reason is one fact a day."""
    since = _since(db)
    if since is None:
        return 0
    settled = now - timedelta(minutes=META_ERROR_WAIT_MINUTES)
    not_meta = sorted(PASSING_CODES | SYSTEM_CODES)
    finished = func.coalesce(CampaignLaunch.finished_at, CampaignLaunch.updated_at)
    launches = list(
        db.execute(
            select(
                CampaignLaunch.id,
                CampaignLaunch.owner_id,
                CampaignLaunch.error_message,
                CampaignLaunch.error_code,
                CampaignLaunch.campaign_name,
            )
            .where(
                CampaignLaunch.status.in_(
                    [str(LaunchStatus.FAILED), str(LaunchStatus.ROLLED_BACK)]
                ),
                CampaignLaunch.provider == META_PROVIDER,
                finished >= since,
                finished <= settled,
                func.coalesce(CampaignLaunch.error_code, "").not_in(not_meta),
                ~_has_ref(
                    CampaignLaunch.owner_id, func.concat("launch:", CampaignLaunch.id)
                ),
            )
            .order_by(finished)
            .limit(limit)
        )
    )
    code = func.coalesce(ActionLog.error_code, "")
    day_ref = func.concat(
        "press:",
        ActionLog.action,
        ":",
        code,
        ":",
        func.to_char(func.timezone("UTC", ActionLog.created_at), "YYYY-MM-DD"),
    )
    later = aliased(ActionLog)
    done_since = exists().where(
        later.owner_id == ActionLog.owner_id,
        later.action == ActionLog.action,
        later.target_external_id == ActionLog.target_external_id,
        later.status == str(ActionStatus.APPLIED),
        later.created_at > ActionLog.created_at,
    )
    presses = list(
        db.execute(
            select(
                ActionLog.owner_id,
                ActionLog.action,
                ActionLog.error_message,
                ActionLog.error_code,
                ActionLog.target_level,
                ActionLog.target_external_id,
                ActionLog.id,
                day_ref,
            )
            .where(
                ActionLog.status == str(ActionStatus.FAILED),
                ActionLog.actor_type == str(ActorType.USER),
                ActionLog.target_provider == META_PROVIDER,
                ActionLog.dry_run.is_(False),
                # A launch's own row: the launch above says it.
                ~ActionLog.idempotency_key.startswith(f"{LAUNCH_LOG_PREFIX}:"),
                ActionLog.created_at >= since,
                ActionLog.created_at <= settled,
                code.not_in(not_meta),
                ~done_since,
                ~_has_ref(ActionLog.owner_id, day_ref),
                # Written one fact a press before.
                ~_has_ref(ActionLog.owner_id, func.concat("action:", ActionLog.id)),
            )
            .order_by(ActionLog.created_at)
            .limit(limit)
        )
    )
    written = 0
    for launch_id, owner_id, message, error, name in launches:
        head = (
            f"«{name}» reklamasi ishga tushmadi" if name else "Reklama ishga tushmadi"
        )
        written += raise_ticket(
            db,
            owner_id=owner_id,
            reason=TicketReason.META_ERROR,
            ref=f"launch:{launch_id}",
            now=now,
            detail=_said(head, _plain(error)),
            extra={
                "raw": _cut(message),
                "target": {"kind": "launch", "id": str(launch_id), "name": name or ""},
            },
        )
    for owner_id, action, message, error, level, external_id, action_id, ref in presses:
        label = (
            str(ACTION_TYPE_LABELS[ActionType(action)])
            if action in ActionType.values
            else action
        )
        written += raise_ticket(
            db,
            owner_id=owner_id,
            reason=TicketReason.META_ERROR,
            ref=ref,
            now=now,
            # The client's own press: noted on a closed ticket, never
            # reopening it. A refused launch still does.
            reopen=False,
            detail=_said(f"«{label}» amali bajarilmadi", _plain(error)),
            extra={
                "raw": _cut(message),
                "target": {
                    "kind": "action",
                    "id": str(action_id),
                    "name": label,
                    "level": level or "",
                    "external_id": external_id or "",
                },
            },
        )
    db.commit()
    return written


def _cut(message: str | None) -> str:
    """The provider's own words, one line, as Support may quote them."""
    return " ".join((message or "").split())[:300]


def _plain(code: str | None) -> str:
    """Why Meta refused, in the words the client's own screen says it; a
    code nobody wrote a sentence for is left to Meta's words beside it."""
    from app.modules.ads.selectors.failures import SENTENCES

    found = SENTENCES.get(META_CODE_WORDS.get(code or "", code or ""))
    return str(found[0]) if found else "Meta rad etdi."


def _said(head: str, message: str | None) -> str:
    text = _cut(message)
    return f"{head}: {text}" if text else head


def _has_ref(owner: Any, ref: Any) -> Any:
    """The client's ticket already holds this fact."""
    return exists().where(
        BoardCardEvent.owner_id == owner,
        BoardCardEvent.ref == ref,
        BoardCardEvent.card_id.in_(
            select(BoardCard.id).where(
                BoardCard.board == str(Board.SUPPORT), BoardCard.owner_id == owner
            )
        ),
    )


def sweep_support(db: Session, *, now: datetime) -> int:
    ensure_board(db, board=Board.SUPPORT, now=now)
    db.commit()
    return (
        setup_late(db, now=now)
        + from_sales(db, now=now)
        + meta_errors(db, now=now)
        + survey_help(db, now=now)
        + client_replied(db, now=now)
        + wait_over(db, now=now)
        + confirm.close_unanswered(db, now=now)
        + confirm.ask_clients(db, now=now)
        # Last: the lines the rules above wrote are told in the same run.
        + notices.tell_ticket_people(db, now=now)
    )


def wait_over(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """«Mijoz kutilmoqda» with its time up, or «Bog'lanib bo'lmadi» with
    its time to call again come: the ticket is back in Ishlanmoqda with its
    person, whatever they hold already."""
    cards = list(
        db.scalars(
            select(BoardCard)
            .where(
                BoardCard.board == str(Board.SUPPORT),
                BoardCard.column_code.in_(
                    [str(SupportColumn.WAITING), str(SupportColumn.UNREACHABLE)]
                ),
                BoardCard.due_at <= now,
            )
            .order_by(BoardCard.due_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    )
    for card in cards:
        card.due_at = None
        kind = (
            EventKind.CALL_AGAIN
            if card.column_code == SupportColumn.UNREACHABLE
            else EventKind.WAIT_OVER
        )
        move(db, card=card, to=str(SupportColumn.IN_PROGRESS), kind=kind, now=now)
    db.commit()
    return len(cards)


def client_replied(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """A ticket waiting for its client, or one Support could not reach the
    client on, and the client wrote in the Yordam chat since: back to
    Ishlanmoqda, its wait over."""
    from app.modules.supportchat.models import SupportMessage

    wrote = exists().where(
        SupportMessage.owner_id == BoardCard.owner_id,
        SupportMessage.sender_id == BoardCard.owner_id,
        SupportMessage.deleted_at.is_(None),
        SupportMessage.created_at > BoardCard.column_since,
    )
    cards = list(
        db.scalars(
            select(BoardCard)
            .where(
                BoardCard.board == str(Board.SUPPORT),
                BoardCard.column_code.in_(
                    [str(SupportColumn.WAITING), str(SupportColumn.UNREACHABLE)]
                ),
                wrote,
            )
            .order_by(BoardCard.column_since)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    )
    for card in cards:
        card.due_at = None
        move(
            db,
            card=card,
            to=str(SupportColumn.IN_PROGRESS),
            kind=EventKind.CLIENT_REPLIED,
            now=now,
        )
    db.commit()
    return len(cards)


def survey_help(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """An answer the office marked «yordam kerak» was chosen. Read by when an
    answer was last kept, not begun: a half-finished one grows answer by answer,
    and the help may be picked in its last save. One ticket per answer still."""
    since = _since(db)
    if since is None:
        return 0
    marked: dict[str, set[int]] = {}
    for question_id, index in db.execute(
        select(SurveyHelpOption.question_id, SurveyHelpOption.option_index)
    ):
        marked.setdefault(str(question_id), set()).add(int(index))
    if not marked:
        return 0
    surveys = select(SurveyQuestion.survey_id).where(
        SurveyQuestion.id.in_([uuid.UUID(q) for q in marked])
    )
    # Read page after page to the end of the window: an answer without a
    # marked option gets no line, so a single oldest-first batch would read
    # the same plain answers every minute and never reach a newer request.
    query = (
        select(
            SurveyResponse.id,
            SurveyResponse.owner_id,
            SurveyResponse.answers,
            SurveyResponse.updated_at,
        )
        .where(
            SurveyResponse.updated_at
            >= max(since, now - timedelta(hours=SURVEY_LOOKBACK_HOURS)),
            SurveyResponse.survey_id.in_(surveys),
            ~_has_ref(
                SurveyResponse.owner_id, func.concat("survey:", SurveyResponse.id)
            ),
        )
        .order_by(SurveyResponse.updated_at, SurveyResponse.id)
        .limit(limit)
    )
    responses: list[Any] = []
    after: tuple[datetime, uuid.UUID] | None = None
    while True:
        page = list(
            db.execute(
                query
                if after is None
                else query.where(
                    tuple_(SurveyResponse.updated_at, SurveyResponse.id) > after
                )
            )
        )
        responses += page
        if len(page) < limit:
            break
        after = (page[-1].updated_at, page[-1].id)
    written = 0
    for response_id, owner_id, answers, _ in responses:
        if not any(
            isinstance(answer, dict)
            and set(answer.get("choices") or ())
            & marked.get(str(answer.get("question")), set())
            for answer in answers or []
        ):
            continue
        written += raise_ticket(
            db,
            owner_id=owner_id,
            reason=TicketReason.SURVEY,
            ref=f"survey:{response_id}",
            now=now,
            detail="So'rovnomada mutaxassis yordamini so'radi.",
        )
    db.commit()
    return written


def idle_no_launch(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """Paid three days ago or more and no ad switched on since, with the
    plan still running."""
    since = _since(db)
    if since is None:
        return 0
    meta = exists().where(
        CampaignLaunch.owner_id == Invoice.owner_id,
        CampaignLaunch.status == str(LaunchStatus.CREATED),
        CampaignLaunch.created_at >= Invoice.paid_at,
    )
    google = exists().where(
        GoogleLaunch.owner_id == Invoice.owner_id,
        GoogleLaunch.status == str(LaunchStatus.CREATED),
        GoogleLaunch.created_at >= Invoice.paid_at,
    )
    rows = list(
        db.execute(
            select(Invoice.id, Invoice.owner_id)
            .join(Subscription, Subscription.owner_id == Invoice.owner_id)
            .where(
                Invoice.status == str(InvoiceStatus.PAID),
                Invoice.kind == str(InvoiceKind.PLAN),
                Invoice.paid_at >= since,
                Invoice.paid_at <= now - timedelta(days=IDLE_NO_LAUNCH_DAYS),
                Subscription.status.in_([str(s) for s in LIVE_SUBSCRIPTION_STATUSES]),
                ~meta,
                ~google,
                ~_has_ref(Invoice.owner_id, func.concat("idle:", Invoice.id)),
            )
            .order_by(Invoice.paid_at)
            .limit(limit)
        )
    )
    written = sum(
        raise_ticket(
            db,
            owner_id=owner_id,
            reason=TicketReason.IDLE,
            ref=f"idle:{invoice_id}",
            now=now,
            detail=f"To'lovdan {IDLE_NO_LAUNCH_DAYS} kun o'tdi, birorta reklama yoqilmagan.",
        )
        for invoice_id, owner_id in rows
        if owner_id is not None
    )
    db.commit()
    return written


def idle_no_spend(db: Session, *, now: datetime, limit: int = SWEEP_BATCH) -> int:
    """A campaign of ours switched on a day ago or more, still running by a
    fresh read, and not a sum spent since. Days without delivery have no
    figures at all, so no figure is read as nothing spent.

    Every condition is in the query: a launch that is spending gets no
    ticket and no line, and read here and skipped it would come back every
    hour, oldest first, until the batch held nothing else."""
    since = _since(db)
    if since is None:
        return 0
    switched_on = CampaignLaunch.delivery_started_at
    external = CampaignLaunch.created_refs["campaign"].as_string()
    running = exists().where(
        Campaign.owner_id == CampaignLaunch.owner_id,
        Campaign.external_id == external,
        Campaign.delivery == str(Delivery.ACTIVE),
        Campaign.synced_at >= now - timedelta(hours=CAMPAIGN_FRESH_HOURS),
    )
    spent = exists().where(
        MetricsDaily.owner_id == CampaignLaunch.owner_id,
        MetricsDaily.level == str(MetricLevel.CAMPAIGN),
        MetricsDaily.external_id == external,
        MetricsDaily.date
        >= cast(func.timezone("UTC", switched_on - timedelta(days=1)), Date),
        MetricsDaily.spend_minor > 0,
    )
    launches = list(
        db.execute(
            select(CampaignLaunch.id, CampaignLaunch.owner_id)
            .where(
                CampaignLaunch.status == str(LaunchStatus.CREATED),
                switched_on.is_not(None),
                switched_on >= max(since, now - timedelta(days=NO_SPEND_LOOKBACK_DAYS)),
                switched_on <= now - timedelta(hours=NO_SPEND_HOURS),
                func.coalesce(external, "") != "",
                running,
                ~spent,
                ~_has_ref(
                    CampaignLaunch.owner_id, func.concat("nospend:", CampaignLaunch.id)
                ),
            )
            .order_by(switched_on)
            .limit(limit)
        )
    )
    written = sum(
        raise_ticket(
            db,
            owner_id=owner_id,
            reason=TicketReason.IDLE,
            ref=f"nospend:{launch_id}",
            now=now,
            detail=f"Reklama yoqilganiga {NO_SPEND_HOURS} soatdan oshdi, sarf 0.",
        )
        for launch_id, owner_id in launches
    )
    db.commit()
    return written


def sweep_idle(db: Session, *, now: datetime) -> int:
    ensure_board(db, board=Board.SUPPORT, now=now)
    db.commit()
    return idle_no_launch(db, now=now) + idle_no_spend(db, now=now)
