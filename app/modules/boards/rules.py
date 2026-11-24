"""The boards' automatic rules, kept by the superuser.

Every move the code makes on its own (a payment sells the card, a bill
opened puts it in «To'lov kutilmoqda», a waiting ticket's time brings it
back, …) is a rule here with a row of its own: what the superuser may
change of it (whether it runs, from which columns, to which column, after
how long, the reason its history keeps) is read from that row, and the rest
stays the code's. What touches money (the sale, the discount's steps) is
shown and its reason may be reworded, nothing else.

Besides those the superuser writes rules of their own, of two kinds: a card
that stood in a column long enough goes to another, and a card whose own
time passed goes to another. ``run_custom`` moves those."""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.boards.constants import (
    ATTEMPT_BOARDS,
    BILL_FROM_COLUMNS,
    BOARD_PATHS,
    CONFIRM_HOURS,
    CUSTOM_RULE_PREFIX,
    CUSTOM_RULES_MAX,
    FULL_ROLES,
    IDLE_NO_LAUNCH_DAYS,
    LEAD_ROLES,
    META_ERROR_WAIT_MINUTES,
    NO_SPEND_HOURS,
    OFFER_COLUMNS,
    OWN_RULE_KINDS,
    QUEUE_COLUMNS,
    RENEWAL_BILL_FROM,
    RENEWAL_DECLINE_DAYS,
    RENEWAL_OPEN_DAYS,
    RENEWAL_SILENT_COLUMNS,
    RULE_AMOUNT_MAX,
    RULE_ATTEMPTS_MAX,
    RULE_BILL_LABELS,
    RULE_KIND_LABELS,
    RULE_NAME_MAX,
    RULE_NO_PLAN,
    RULE_NO_PLAN_LABEL,
    RULE_REASON_MAX,
    RULE_TEXT_MAX,
    RULE_UNIT_LABELS,
    RULE_UNIT_MINUTES,
    SETUP_GRACE_MINUTES,
    STAY_RULE_MIN_MINUTES,
    SWEEP_BATCH,
    Board,
    ColumnKind,
    EventKind,
    RenewalColumn,
    RuleBill,
    RuleKind,
    RuleUnit,
    SalesColumn,
    SupportColumn,
)
from app.modules.boards.exceptions import (
    NoSuchRule,
    RuleFieldFixed,
    RuleInvalid,
    TooManyRules,
)
from app.modules.boards.models import (
    BoardCard,
    BoardCardEvent,
    BoardColumn,
    BoardRule,
)

logger = logging.getLogger(__name__)
# The cards a rule's trial names.
PREVIEW_CARDS = 10

ENABLED, FROM, TO, AMOUNT, REASON = "enabled", "from", "to", "amount", "reason"


@dataclass(frozen=True, slots=True)
class Spec:
    """A rule the code runs, as it stands until the superuser changes it."""

    code: str
    board: Board
    name: str
    # What happens to the client or the card, as a clause: «… bo'lsa».
    when: str
    # What the rule does when it is not a plain move to ``to_column``.
    then: str = ""
    from_columns: tuple[str, ...] = ()
    to_column: str = ""
    amount: int = 0
    unit: str = ""
    # What ``amount`` counts, for the settings: «to'lovdan keyin».
    amount_of: str = ""
    reason: str = ""
    editable: frozenset[str] = field(default_factory=frozenset)
    # Why the rest is not the superuser's to change.
    note: str = ""


def _s(*columns: Any) -> tuple[str, ...]:
    return tuple(sorted(str(column) for column in columns))


_MONEY = "Pulga bog'liq qoida: faqat sabab matni o'zgaradi."
_OWN_WORDS = "Sababni tizim har safar o'zi yozadi (qaysi to'lov, qaysi muddat)."

SPECS: tuple[Spec, ...] = (
    # -- Sotuv ---------------------------------------------------------------
    Spec(
        "sales.lead_opened",
        Board.SALES,
        "Yangi lid",
        "Mijoz ro'yxatdan o'tib, tarif sotib olmagan bo'lsa",
        to_column=str(SalesColumn.UNWORKED),
        note=_OWN_WORDS,
    ),
    Spec(
        "sales.start_expired",
        Board.SALES,
        "Start tarifi tugadi",
        "Start olgan mijozning tarifi tugab, to'liq tarif olmagan bo'lsa",
        to_column=str(SalesColumn.UNWORKED),
        note=_OWN_WORDS,
    ),
    Spec(
        "sales.sold",
        Board.SALES,
        "Sotildi",
        "Mijoz to'liq tarif uchun to'lasa (har qanday ustundan)",
        to_column=str(SalesColumn.SOLD),
        reason="Mijoz tarif uchun to'ladi.",
        editable=frozenset({REASON}),
        note=_MONEY,
    ),
    Spec(
        "sales.given",
        Board.SALES,
        "Tarif ofisdan berildi",
        "Mijozga tarif ofisdan to'lovsiz berilsa",
        to_column=str(SalesColumn.SOLD),
        note=_OWN_WORDS,
    ),
    Spec(
        "sales.start_bought",
        Board.SALES,
        "Start sotib olindi",
        "Menejer gaplashgan mijoz Start sotib olsa",
        then="karta chegirma ustuniga o'tadi (20%, 24 soat)",
        reason="Mijoz Start sotib oldi, chegirma soati boshlandi.",
        editable=frozenset({REASON}),
        note=_MONEY,
    ),
    Spec(
        "sales.offer_step",
        Board.SALES,
        "Chegirma 10% ga tushdi",
        "20% chegirmaning 24 soati o'tsa",
        from_columns=_s(SalesColumn.DISCOUNT_20),
        to_column=str(SalesColumn.DISCOUNT_10),
        reason="20% chegirma muddati tugadi, 10% boshlandi.",
        editable=frozenset({REASON}),
        note=_MONEY,
    ),
    Spec(
        "sales.offer_ended",
        Board.SALES,
        "Chegirma tugadi",
        "Chegirmaning 96 soati o'tsa",
        then="karta «Bog'lanildi»ga qaytadi (menejeri bo'lmasa «Ishlanmagan»ga)",
        from_columns=_s(SalesColumn.DISCOUNT_20, SalesColumn.DISCOUNT_10),
        reason="Chegirma muddati tugadi, mijoz to'lamadi.",
        editable=frozenset({REASON}),
        note=_MONEY,
    ),
    Spec(
        "sales.bill_opened",
        Board.SALES,
        "Mijoz hisob ochdi",
        "Menejeri bor mijoz tarif uchun hisob ochsa",
        from_columns=_s(*BILL_FROM_COLUMNS),
        to_column=str(SalesColumn.AWAITING),
        reason="Mijoz to'lov hisobini ochdi, to'lov kutilmoqda.",
        editable=frozenset({ENABLED, FROM, TO, REASON}),
        note="Chegirma ustunlaridan o'tmaydi: hisob narxi chegirmani ustundan o'qiydi.",
    ),
    Spec(
        "sales.bill_unpaid",
        Board.SALES,
        "Hisob to'lanmadi",
        "Mijoz ochgan hisob to'lanmay muddati o'tsa",
        then="karta ko'chadi va muddati «hozir» bo'ladi: menejer qo'ng'iroq qiladi",
        from_columns=_s(SalesColumn.AWAITING),
        to_column=str(SalesColumn.CALLBACK),
        reason="Mijoz ochgan hisobni to'lamadi, qo'ng'iroq qilish kerak.",
        editable=frozenset({ENABLED, TO, REASON}),
    ),
    # -- Support ---------------------------------------------------------------
    Spec(
        "support.setup_late",
        Board.SUPPORT,
        "Sozlash tugamadi",
        "Mijoz to'lab, sozlashni tugatmagan bo'lsa",
        to_column=str(SupportColumn.NEW),
        amount=SETUP_GRACE_MINUTES,
        unit=str(RuleUnit.MINUTES),
        amount_of="to'lovdan keyin",
        editable=frozenset({ENABLED, AMOUNT}),
        note=_OWN_WORDS,
    ),
    Spec(
        "support.from_sales",
        Board.SUPPORT,
        "Sotuvdan: yordam kerak",
        "Sotuv «Support kerak» deb belgilagan mijoz to'lasa",
        to_column=str(SupportColumn.NEW),
        editable=frozenset({ENABLED}),
        note=_OWN_WORDS,
    ),
    Spec(
        "support.meta_error",
        Board.SUPPORT,
        "Meta xatosi",
        "Meta mijozning reklamasini yoki amalini rad etsa va mijoz o'zi tuzatmasa",
        to_column=str(SupportColumn.NEW),
        amount=META_ERROR_WAIT_MINUTES,
        unit=str(RuleUnit.MINUTES),
        amount_of="rad etilgandan keyin",
        editable=frozenset({ENABLED, AMOUNT}),
        note=_OWN_WORDS,
    ),
    Spec(
        "support.survey",
        Board.SUPPORT,
        "So'rovnoma: yordam kerak",
        "Mijoz so'rovnomada «yordam kerak» deb belgilangan javobni tanlasa",
        to_column=str(SupportColumn.NEW),
        editable=frozenset({ENABLED}),
        note=_OWN_WORDS,
    ),
    Spec(
        "support.idle_no_launch",
        Board.SUPPORT,
        "Reklama yoqilmadi",
        "Mijoz to'lab, birorta reklama yoqmagan bo'lsa",
        to_column=str(SupportColumn.NEW),
        amount=IDLE_NO_LAUNCH_DAYS,
        unit=str(RuleUnit.DAYS),
        amount_of="to'lovdan keyin",
        editable=frozenset({ENABLED, AMOUNT}),
        note=_OWN_WORDS,
    ),
    Spec(
        "support.idle_no_spend",
        Board.SUPPORT,
        "Reklama sarflamayapti",
        "Yoqilgan reklama hech narsa sarflamagan bo'lsa",
        to_column=str(SupportColumn.NEW),
        amount=NO_SPEND_HOURS,
        unit=str(RuleUnit.HOURS),
        amount_of="yoqilgandan keyin",
        editable=frozenset({ENABLED, AMOUNT}),
        note=_OWN_WORDS,
    ),
    Spec(
        "support.reopened",
        Board.SUPPORT,
        "Yangi muammo",
        "Hal qilingan zayavka egasida yangi muammo chiqsa",
        to_column=str(SupportColumn.NEW),
        note=_OWN_WORDS,
    ),
    Spec(
        "support.due_back",
        Board.SUPPORT,
        "Kutish vaqti tugadi",
        "Zayavkaga qo'yilgan vaqt kelsa",
        from_columns=_s(SupportColumn.WAITING, SupportColumn.UNREACHABLE),
        to_column=str(SupportColumn.IN_PROGRESS),
        reason="Belgilangan vaqt keldi, zayavka xodimiga qaytdi.",
        editable=frozenset({ENABLED, FROM, TO, REASON}),
    ),
    Spec(
        "support.client_replied",
        Board.SUPPORT,
        "Mijoz yozdi",
        "Mijoz Yordam chatiga yozsa",
        from_columns=_s(SupportColumn.WAITING, SupportColumn.UNREACHABLE),
        to_column=str(SupportColumn.IN_PROGRESS),
        reason="Mijoz chatga yozdi, zayavka xodimiga qaytdi.",
        editable=frozenset({ENABLED, FROM, TO, REASON}),
    ),
    Spec(
        "support.confirmed",
        Board.SUPPORT,
        "Mijoz tasdiqladi yoki rad etdi",
        "Mijoz «hal bo'ldimi?» savoliga javob bersa",
        then="«Ha» — «Hal qilindi»ga, «Yo'q» — xodimiga qaytadi",
        from_columns=_s(SupportColumn.CONFIRMING),
        note=_OWN_WORDS,
    ),
    Spec(
        "support.unanswered",
        Board.SUPPORT,
        "Mijoz javob bermadi",
        "Mijoz «hal bo'ldimi?» savoliga javob bermasa",
        from_columns=_s(SupportColumn.CONFIRMING),
        to_column=str(SupportColumn.CLOSED),
        amount=CONFIRM_HOURS,
        unit=str(RuleUnit.HOURS),
        amount_of="savoldan keyin",
        reason="Mijoz tasdiq savoliga javob bermadi, zayavka yopildi.",
        editable=frozenset({REASON}),
        note="Muddat mijozga yuborilgan savol matnida ham yozilgan, shuning uchun o'zgarmaydi.",
    ),
    Spec(
        "support.dev_fixed",
        Board.SUPPORT,
        "Dasturchi tuzatdi",
        "Dasturchi zayavka bilan berilgan xatoni tuzatsa",
        from_columns=_s(SupportColumn.DEVELOPER),
        to_column=str(SupportColumn.RESOLVED),
        note=_OWN_WORDS,
    ),
    # -- Uzaytirish ------------------------------------------------------------
    Spec(
        "renewal.opened",
        Board.RENEWAL,
        "Obuna tugayapti",
        "To'lab ishlayotgan Standart yoki Pro mijozning muddati tugashiga shuncha qolsa",
        to_column=str(RenewalColumn.ENDING),
        amount=RENEWAL_OPEN_DAYS,
        unit=str(RuleUnit.DAYS),
        amount_of="muddat tugashidan oldin",
        editable=frozenset({AMOUNT}),
        note=_OWN_WORDS,
    ),
    Spec(
        "renewal.ended",
        Board.RENEWAL,
        "Obuna tugadi",
        "Karta «Tugayapti»da turganda muddat tugasa",
        from_columns=_s(RenewalColumn.ENDING),
        to_column=str(RenewalColumn.ENDED),
        reason="Obuna muddati tugadi, mijoz hali uzaytirmadi.",
        editable=frozenset({REASON}),
    ),
    Spec(
        "renewal.term_moved",
        Board.RENEWAL,
        "Muddat o'zgardi",
        "Ofis mijozga kun bersa yoki olsa",
        then="ochiq karta yangi muddatni oladi",
        note=_OWN_WORDS,
    ),
    Spec(
        "renewal.bill_opened",
        Board.RENEWAL,
        "Mijoz hisob ochdi",
        "Mijoz uzaytirish uchun hisob ochsa",
        from_columns=_s(*RENEWAL_BILL_FROM),
        to_column=str(RenewalColumn.AWAITING),
        reason="Mijoz uzaytirish hisobini ochdi, to'lov kutilmoqda.",
        editable=frozenset({ENABLED, FROM, TO, REASON}),
    ),
    Spec(
        "renewal.bill_unpaid",
        Board.RENEWAL,
        "Hisob to'lanmadi",
        "Mijoz ochgan hisob to'lanmay muddati o'tsa",
        then="karta ko'chadi va muddati «hozir» bo'ladi: menejer qo'ng'iroq qiladi",
        from_columns=_s(RenewalColumn.AWAITING),
        to_column=str(RenewalColumn.CALLBACK),
        reason="Mijoz ochgan hisobni to'lamadi, qo'ng'iroq qilish kerak.",
        editable=frozenset({ENABLED, TO, REASON}),
    ),
    Spec(
        "renewal.renewed",
        Board.RENEWAL,
        "Uzaytirdi",
        "Mijoz Standart yoki Pro uchun to'lasa (har qanday ustundan)",
        to_column=str(RenewalColumn.RENEWED),
        note=_MONEY + " " + _OWN_WORDS,
    ),
    Spec(
        "renewal.silent",
        Board.RENEWAL,
        "Javob bermadi",
        "Muddat tugab, mijoz bilan bog'lanib bo'lmagan bo'lsa",
        then="karta «Javob bermadi» sababi bilan yopiladi",
        from_columns=_s(*RENEWAL_SILENT_COLUMNS),
        to_column=str(RenewalColumn.DECLINED),
        amount=RENEWAL_DECLINE_DAYS,
        unit=str(RuleUnit.DAYS),
        amount_of="muddat tugaganidan keyin",
        reason="Muddat tugaganidan beri mijoz bilan bog'lanib bo'lmadi.",
        editable=frozenset({ENABLED, FROM, AMOUNT, REASON}),
    ),
)
SPEC_BY_CODE: dict[str, Spec] = {spec.code: spec for spec in SPECS}


@dataclass(frozen=True, slots=True)
class Rule:
    """A rule as a sweep reads it: the code's own with the superuser's
    changes on top."""

    code: str
    board: str
    kind: str
    enabled: bool
    from_columns: tuple[str, ...]
    to_column: str
    amount: int
    unit: str
    reason: str
    name: str = ""

    @property
    def delta(self) -> timedelta:
        return timedelta(minutes=self.amount * RULE_UNIT_MINUTES[RuleUnit(self.unit)])

    def said(self, detail: str = "") -> str:
        """The line a card's history keeps: why, then the particulars."""
        if not detail:
            return self.reason
        head = self.reason.rstrip(".")
        return f"{head}: {detail}" if head else detail


def _of_spec(spec: Spec, row: BoardRule | None) -> Rule:
    """The spec with what its row changes, each only where the spec lets
    the superuser change it: a stray value in the table changes nothing."""
    can = spec.editable
    return Rule(
        code=spec.code,
        board=str(spec.board),
        kind=str(RuleKind.SYSTEM),
        enabled=row.is_enabled if row is not None and ENABLED in can else True,
        from_columns=tuple(row.from_columns)
        if row is not None and FROM in can and row.from_columns
        else spec.from_columns,
        to_column=row.to_column
        if row is not None and TO in can and row.to_column
        else spec.to_column,
        amount=row.amount
        if row is not None and AMOUNT in can and row.amount > 0
        else spec.amount,
        unit=spec.unit,
        reason=(row.reason if row is not None and REASON in can and row.reason else "")
        or spec.reason,
        name=spec.name,
    )


def _seed_row(spec: Spec, position: int, now: datetime) -> dict[str, Any]:
    return {
        "id": uuid.uuid4(),
        "board": str(spec.board),
        "code": spec.code,
        "kind": str(RuleKind.SYSTEM),
        "name": "",
        "is_enabled": True,
        "from_columns": list(spec.from_columns),
        "to_column": spec.to_column,
        "amount": spec.amount,
        "unit": spec.unit,
        "reason": spec.reason,
        "position": position,
        "is_default": True,
        "created_at": now,
        "updated_at": now,
    }


def ensure(db: Session, *, now: datetime) -> None:
    """A row for every rule the code runs, written once and topped up when
    the code gains a rule. The migration writes them at deploy."""
    have = set(
        db.scalars(select(BoardRule.code).where(BoardRule.kind == str(RuleKind.SYSTEM)))
    )
    missing = [
        _seed_row(spec, index, now)
        for index, spec in enumerate(SPECS, start=1)
        if spec.code not in have
    ]
    if missing:
        db.execute(
            insert(BoardRule)
            .values(missing)
            .on_conflict_do_nothing(index_elements=["code"])
        )
        db.flush()


def get(db: Session, code: str) -> Rule:
    """One of the code's rules as it stands now."""
    spec = SPEC_BY_CODE[code]
    row = db.scalar(select(BoardRule).where(BoardRule.code == code))
    return _of_spec(spec, row)


# -- the superuser's own rules -------------------------------------------------


def _custom(db: Session, *, board: Board) -> list[BoardRule]:
    return list(
        db.scalars(
            select(BoardRule)
            .where(
                BoardRule.board == str(board),
                BoardRule.kind.in_([str(kind) for kind in OWN_RULE_KINDS]),
            )
            .order_by(BoardRule.position, BoardRule.created_at, BoardRule.code)
        )
    )


def _target_ok(db: Session, *, board: Board, code: str) -> bool:
    """A column a rule may send a card to: visible, worked by hand, and not
    one that closes a card."""
    return (
        db.scalar(
            select(BoardColumn.id).where(
                BoardColumn.board == str(board),
                BoardColumn.code == code,
                BoardColumn.is_visible.is_(True),
                BoardColumn.is_final.is_(False),
                BoardColumn.kind == str(ColumnKind.MANUAL),
            )
        )
        is not None
    )


@dataclass(frozen=True, slots=True)
class Own:
    """One of the superuser's rules as a run reads it: when it fires, what
    else must hold of the card, and what it does."""

    code: str
    kind: str
    name: str
    from_columns: tuple[str, ...]
    to_column: str
    amount: int
    unit: str
    reason: str
    attempts_min: int = 0
    plans: tuple[str, ...] = ()
    bill: str = ""
    # None: the card's time is left as it is.
    due_minutes: int | None = None
    notify_manager: bool = False
    notify_lead: bool = False
    notify_text: str = ""
    assign_to: str = ""

    @property
    def wait(self) -> timedelta:
        return timedelta(
            minutes=self.amount * RULE_UNIT_MINUTES[RuleUnit(self.unit or "hours")]
        )

    @property
    def notifies(self) -> bool:
        return self.notify_manager or self.notify_lead


def _own_of(values: dict[str, Any], *, code: str = "") -> Own:
    conditions = dict(values.get("conditions") or {})
    actions = dict(values.get("actions") or {})
    due = actions.get("due")
    notify = dict(actions.get("notify") or {})
    return Own(
        code=code,
        kind=str(values["kind"]),
        name=str(values.get("name") or ""),
        from_columns=tuple(values.get("from_columns") or ()),
        to_column=str(values.get("to_column") or ""),
        amount=int(values.get("amount") or 0),
        unit=str(values.get("unit") or ""),
        reason=str(values.get("reason") or ""),
        attempts_min=int(conditions.get("attempts_min") or 0),
        plans=tuple(conditions.get("plans") or ()),
        bill=str(conditions.get("bill") or ""),
        due_minutes=(
            int(due["amount"]) * RULE_UNIT_MINUTES[RuleUnit(due["unit"])]
            if isinstance(due, dict)
            else None
        ),
        notify_manager=bool(notify.get("manager")),
        notify_lead=bool(notify.get("lead")),
        notify_text=str(notify.get("text") or ""),
        assign_to=str(actions.get("assign") or ""),
    )


def _own_of_row(row: BoardRule) -> Own:
    return _own_of(
        {
            "kind": row.kind,
            "name": row.name,
            "from_columns": row.from_columns,
            "to_column": row.to_column,
            "amount": row.amount,
            "unit": row.unit,
            "reason": row.reason,
            "conditions": row.conditions,
            "actions": row.actions,
        },
        code=row.code,
    )


_STAMP = "YYYYMMDDHH24MISSUS"


def _fired_ref(rule: Own) -> Any:
    """What one firing of the rule on a card is named by, in SQL: the rule
    and the moment it read (the card's coming to the column, or its time).
    A rule that leaves the card where it stands fires once for that moment."""
    read = (
        BoardCard.due_at if rule.kind == str(RuleKind.DUE) else BoardCard.column_since
    )
    return func.concat(
        f"rule:{rule.code}:", func.to_char(func.timezone("UTC", read), _STAMP)
    )


def fired_ref(rule: Own, card: BoardCard) -> str:
    read = card.due_at if rule.kind == str(RuleKind.DUE) else card.column_since
    at = (read or card.column_since).astimezone(UTC)
    return f"rule:{rule.code}:{at.strftime('%Y%m%d%H%M%S%f')}"


def _matching(*, board: Board, rule: Own, now: datetime) -> list[Any]:
    """The cards the rule would act on now, as conditions on ``BoardCard``."""
    from app.modules.billing.constants import (
        LIVE_SUBSCRIPTION_STATUSES,
        InvoiceKind,
        InvoiceStatus,
    )
    from app.modules.billing.models import Invoice, Plan, Subscription
    from app.modules.boards.view import open_bills

    where: list[Any] = [
        BoardCard.board == str(board),
        BoardCard.column_code.in_(rule.from_columns),
    ]
    if rule.to_column:
        where.append(BoardCard.column_code != rule.to_column)
    if board != Board.SUPPORT:
        where.append(BoardCard.closed_at.is_(None))
    if rule.kind == str(RuleKind.STAY):
        where.append(BoardCard.column_since <= now - rule.wait)
    elif rule.kind == str(RuleKind.DUE):
        where.append(BoardCard.due_at <= now - rule.wait)
    else:
        from app.modules.supportchat.models import SupportMessage

        where.append(
            exists().where(
                SupportMessage.owner_id == BoardCard.owner_id,
                SupportMessage.sender_id == BoardCard.owner_id,
                SupportMessage.deleted_at.is_(None),
                SupportMessage.created_at > BoardCard.column_since,
            )
        )
    if rule.attempts_min:
        where.append(BoardCard.attempts >= rule.attempts_min)
    if rule.plans:
        live = (
            select(Plan.code)
            .join(Subscription, Subscription.plan_id == Plan.id)
            .where(
                Subscription.owner_id == BoardCard.owner_id,
                Subscription.status.in_([str(s) for s in LIVE_SUBSCRIPTION_STATUSES]),
                Subscription.expires_at > now,
            )
            .order_by(Subscription.started_at.desc())
            .limit(1)
            .correlate(BoardCard)
            .scalar_subquery()
        )
        where.append(func.coalesce(live, RULE_NO_PLAN).in_(rule.plans))
    if rule.bill:
        bills = open_bills(now).subquery()
        has_open = exists().where(bills.c.owner_id == BoardCard.owner_id)
        if rule.bill == str(RuleBill.OPEN):
            where.append(has_open)
        else:
            ran_out = exists().where(
                Invoice.owner_id == BoardCard.owner_id,
                Invoice.kind == str(InvoiceKind.PLAN),
                or_(
                    Invoice.status == str(InvoiceStatus.EXPIRED),
                    and_(
                        Invoice.status == str(InvoiceStatus.PENDING),
                        Invoice.expires_at <= now,
                    ),
                ),
                Invoice.created_at >= BoardCard.opened_at,
            )
            where.extend([ran_out, ~has_open])
    if rule.code:
        where.append(
            ~exists().where(
                BoardCardEvent.card_id == BoardCard.id,
                BoardCardEvent.ref == _fired_ref(rule),
            )
        )
    return where


def _leads(db: Session, *, board: Board) -> set[uuid.UUID]:
    """Who hears a rule's word «rahbarga»: the board's lead and the Owner."""
    from app.modules.accounts.models import User
    from app.modules.backoffice.permissions import roles_of

    wanted = {str(role) for role in (*LEAD_ROLES[board], *FULL_ROLES)}
    return {
        person.id
        for person in db.scalars(
            select(User).where(
                User.is_staff.is_(True),
                User.is_active.is_(True),
                User.is_superuser.is_(False),
            )
        )
        if roles_of(db, person) & wanted
    }


def _word(db: Session, *, board: Board, rule: Own, card: BoardCard) -> str:
    """What the rule tells on Telegram about one card."""
    from app.modules.notifications.services.compose import escaped

    owner = card.owner
    column = db.scalar(
        select(BoardColumn.name).where(
            BoardColumn.board == str(board), BoardColumn.code == card.column_code
        )
    )
    lines = [
        f"🤖 <b>{escaped(rule.name)}</b>",
        escaped(owner.full_name or owner.email)
        + (f" · {escaped(owner.phone)}" if owner.phone else ""),
        f"Ustun: {escaped(column or card.column_code)}",
    ]
    said = rule.notify_text or rule.reason
    if said:
        lines.append(escaped(said))
    return "\n".join(lines)


def _tell(outbox: list[tuple[str, str, str]], *, client: Any) -> int:
    """The words the run gathered, sent after its changes were kept. A
    message Telegram refuses is logged and the rest go on."""
    if not outbox:
        return 0
    from telegramkit import Button, TelegramError

    from app.modules.notifications.bot import staff_bot, staff_bot_configured

    def send(bot: Any) -> int:
        sent = 0
        for chat_id, text, url in outbox:
            try:
                bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    buttons=(Button(text="Kartani ochish", url=url),),
                )
                sent += 1
            except TelegramError:
                logger.warning("board rule notice not delivered")
        return sent

    if client is not None:
        return send(client)
    if not staff_bot_configured():
        return 0
    with staff_bot() as bot:
        return send(bot)


def run_custom(
    db: Session,
    *,
    board: Board,
    now: datetime,
    limit: int = SWEEP_BATCH,
    client: Any = None,
) -> int:
    """The superuser's own rules of the board, in their order. A card a
    rule acted on is not looked at again in the same run. A rule whose
    column was taken off the board since does nothing. What a rule tells on
    Telegram is sent after its changes are kept (``client``: the staff bot
    of a test; the configured one otherwise)."""
    from app.common.config import settings
    from app.modules.accounts.models import User
    from app.modules.boards.access import works_on
    from app.modules.boards.services import move, record

    done: set[uuid.UUID] = set()
    for row in _custom(db, board=board):
        if not row.is_enabled or not row.from_columns:
            continue
        rule = _own_of_row(row)
        if rule.to_column and not _target_ok(db, board=board, code=rule.to_column):
            continue
        query = select(BoardCard).where(*_matching(board=board, rule=rule, now=now))
        if done:
            query = query.where(BoardCard.id.not_in(done))
        cards = list(
            db.scalars(
                query.order_by(BoardCard.column_since)
                .limit(limit)
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
        )
        if not cards:
            continue
        given: User | None = None
        if rule.assign_to:
            found = db.get(User, uuid.UUID(rule.assign_to))
            # Somebody who left the board since is not given cards.
            given = found if found is not None and works_on(db, found, board) else None
        leads = _leads(db, board=board) if rule.notify_lead else set()
        outbox: list[tuple[str, str, str]] = []
        for card in cards:
            ref = fired_ref(rule, card)
            said = f"{rule.name}. {rule.reason}" if rule.reason else rule.name
            if given is not None and card.manager_id != given.id:
                card.manager_id = given.id
                said = f"{said} Xodim: {given.full_name or given.email}."
            if rule.due_minutes is not None:
                card.due_at = now + timedelta(minutes=rule.due_minutes)
            elif rule.kind == str(RuleKind.DUE) and rule.to_column:
                card.due_at = None
            if rule.notifies:
                # Read before the move: the word names the column it found.
                text = _word(db, board=board, rule=rule, card=card)
                hear = set(leads)
                if rule.notify_manager and card.manager_id:
                    hear.add(card.manager_id)
                url = f"{settings.site_url}{BOARD_PATHS[board]}?karta={card.id}"
                outbox.extend((chat, text, url) for chat in _chats(db, hear).values())
            if rule.to_column:
                move(
                    db,
                    card=card,
                    to=rule.to_column,
                    kind=EventKind.RULE,
                    now=now,
                    body=said,
                    ref=ref,
                )
            else:
                record(db, card=card, kind=EventKind.RULE, now=now, body=said, ref=ref)
            done.add(card.id)
        db.commit()
        _tell(outbox, client=client)
    return len(done)


def _chats(db: Session, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    from app.modules.notifications.models import StaffChat

    if not user_ids:
        return {}
    return {
        owner: chat
        for owner, chat in db.execute(
            select(StaffChat.owner_id, StaffChat.chat_id).where(
                StaffChat.owner_id.in_(user_ids), StaffChat.is_active.is_(True)
            )
        )
    }


def preview(
    db: Session, *, board: Board, now: datetime, code: str = "", **fields: Any
) -> dict[str, Any]:
    """Which cards a rule written so would act on this minute: how many, and
    the first few. ``code``: the rule being edited, so the cards it already
    acted on are left out as a run leaves them out."""
    from app.modules.accounts.models import User

    rule = _own_of(_custom_fields(db, board=board, **fields), code=code)
    where = _matching(board=board, rule=rule, now=now)
    total = int(
        db.scalar(select(func.count()).select_from(BoardCard).where(*where)) or 0
    )
    names = {
        column.code: column.name
        for column in db.scalars(
            select(BoardColumn).where(BoardColumn.board == str(board))
        )
    }
    rows = db.execute(
        select(BoardCard, User)
        .join(User, User.id == BoardCard.owner_id)
        .where(*where)
        .order_by(BoardCard.column_since)
        .limit(PREVIEW_CARDS)
    )
    return {
        "count": total,
        "cards": [
            {
                "id": str(card.id),
                "name": person.full_name or person.email,
                "column": card.column_code,
                "column_name": names.get(card.column_code, card.column_code),
                "column_since": card.column_since,
                "due_at": card.due_at,
            }
            for card, person in rows
        ],
    }


def pointing_at(db: Session, *, board: Board, column_code: str) -> int:
    """How many rules send cards to this column or read them from it."""
    count = 0
    for row in db.scalars(select(BoardRule).where(BoardRule.board == str(board))):
        spec = SPEC_BY_CODE.get(row.code)
        if spec is not None:
            rule = _of_spec(spec, row)
            touches = column_code == rule.to_column or column_code in (
                rule.from_columns
            )
        else:
            touches = column_code == row.to_column or column_code in (
                row.from_columns or []
            )
        count += int(touches)
    return count


# -- the superuser's changes --------------------------------------------------


def _open_columns(db: Session, *, board: Board) -> dict[str, BoardColumn]:
    return {
        column.code: column
        for column in db.scalars(
            select(BoardColumn).where(
                BoardColumn.board == str(board), BoardColumn.is_visible.is_(True)
            )
        )
    }


def _checked_from(
    columns: dict[str, BoardColumn],
    *,
    board: Board,
    codes: list[str],
    to: str,
    own: tuple[str, ...] = (),
) -> list[str]:
    """Columns a rule may take cards from: on the board, not ones that
    close a card, not a queue, not a discount column, not its own target.
    ``own``: the columns the code gave the rule, which it keeps whatever
    they are (a hidden one among them)."""
    out = sorted(set(codes))
    if not out:
        raise RuleInvalid("Qoida qaysi ustunlardan ishlashini tanlang.")
    for code in out:
        if code in own and code != to:
            continue
        column = columns.get(code)
        if (
            column is None
            or column.is_final
            or (board, code) in QUEUE_COLUMNS
            or (board == Board.SALES and code in OFFER_COLUMNS)
        ):
            raise RuleInvalid(
                "Qoida faqat ochiq ustunlardan ishlaydi: navbat, chegirma va "
                "yakuniy ustunlardan emas."
            )
        if code == to:
            raise RuleInvalid("Karta o'zi turgan ustunga ko'chirilmaydi.")
    return out


def _checked_to(db: Session, *, board: Board, code: str, default: str = "") -> str:
    if code and (code == default or _target_ok(db, board=board, code=code)):
        return code
    raise RuleInvalid(
        "Qoida kartani faqat qo'lda ishlanadigan, yakuniy bo'lmagan ustunga "
        "o'tkaza oladi."
    )


def _checked_reason(reason: str) -> str:
    return " ".join(reason.split())[:RULE_REASON_MAX]


def _checked_amount(amount: int, *, least: int = 1) -> int:
    if amount < least or amount > RULE_AMOUNT_MAX * 24 * 60:
        raise RuleInvalid("Muddat noto'g'ri.")
    return amount


def _row(db: Session, *, board: Board, rule_id: uuid.UUID) -> BoardRule:
    found = db.get(BoardRule, rule_id)
    if found is None or found.board != str(board):
        raise NoSuchRule
    return found


def edit_system(
    db: Session,
    *,
    board: Board,
    rule_id: uuid.UUID,
    changes: dict[str, Any],
    actor_id: uuid.UUID,
    now: datetime,
) -> None:
    """What the superuser changes of a rule the code runs: only the fields
    its spec opens. ``changes`` holds the fields sent."""
    row = _row(db, board=board, rule_id=rule_id)
    spec = SPEC_BY_CODE.get(row.code)
    if spec is None:
        raise NoSuchRule
    keys = {ENABLED: "is_enabled", FROM: "from_columns", TO: "to_column"}
    for name in (ENABLED, FROM, TO, AMOUNT, REASON):
        if keys.get(name, name) in changes and name not in spec.editable:
            raise RuleFieldFixed
    columns = _open_columns(db, board=board)
    to = row.to_column or spec.to_column
    if "to_column" in changes:
        to = _checked_to(
            db, board=board, code=str(changes["to_column"]), default=spec.to_column
        )
    origin = list(row.from_columns or spec.from_columns)
    if "from_columns" in changes:
        origin = _checked_from(
            columns,
            board=board,
            codes=list(changes["from_columns"]),
            to=to,
            own=spec.from_columns,
        )
    elif to in origin and "to_column" in changes:
        raise RuleInvalid("Karta o'zi turgan ustunga ko'chirilmaydi.")
    if "is_enabled" in changes:
        row.is_enabled = bool(changes["is_enabled"])
    if "amount" in changes:
        row.amount = _checked_amount(int(changes["amount"]))
    if "reason" in changes:
        row.reason = _checked_reason(str(changes["reason"])) or spec.reason
    row.to_column = to
    row.from_columns = origin
    row.updated_by_id = actor_id
    row.updated_at = now
    db.commit()


def reset_system(
    db: Session, *, board: Board, rule_id: uuid.UUID, actor_id: uuid.UUID, now: datetime
) -> None:
    """The rule as the code has it («Standartga qaytarish»)."""
    row = _row(db, board=board, rule_id=rule_id)
    spec = SPEC_BY_CODE.get(row.code)
    if spec is None:
        raise NoSuchRule
    row.is_enabled = True
    row.from_columns = list(spec.from_columns)
    row.to_column = spec.to_column
    row.amount = spec.amount
    row.reason = spec.reason
    row.updated_by_id = actor_id
    row.updated_at = now
    db.commit()


def _plan_names(db: Session) -> dict[str, str]:
    from app.modules.billing.models import Plan

    return {
        code: name or code
        for code, name in db.execute(
            select(Plan.code, Plan.name).order_by(Plan.sort_order, Plan.code)
        )
        if code
    }


def _custom_fields(
    db: Session,
    *,
    board: Board,
    kind: str,
    name: str,
    from_columns: list[str],
    to_column: str,
    amount: int,
    unit: str,
    reason: str,
    attempts_min: int = 0,
    plans: list[str] | None = None,
    bill: str = "",
    due_amount: int | None = None,
    due_unit: str = "",
    notify_manager: bool = False,
    notify_lead: bool = False,
    notify_text: str = "",
    assign_to: str = "",
) -> dict[str, Any]:
    """A rule of the superuser's own, checked: when it fires, what else
    must hold of the card, what it does. It does at least one thing."""
    from app.modules.accounts.models import User
    from app.modules.boards.access import works_on

    if kind not in [str(item) for item in OWN_RULE_KINDS]:
        raise RuleInvalid("Qoida turi noto'g'ri.")
    waits = kind != str(RuleKind.WROTE)
    if not waits:
        amount, unit = 0, str(RuleUnit.MINUTES)
    if unit not in RuleUnit.values:
        raise RuleInvalid("Muddat birligi noto'g'ri.")
    cleaned = " ".join(name.split())[:RULE_NAME_MAX]
    if not cleaned:
        raise RuleInvalid("Qoida nomini yozing.")
    to = _checked_to(db, board=board, code=to_column) if to_column else ""
    origin = _checked_from(
        _open_columns(db, board=board), board=board, codes=from_columns, to=to
    )
    minutes = amount * RULE_UNIT_MINUTES[RuleUnit(unit)]
    if kind == str(RuleKind.STAY):
        if minutes < STAY_RULE_MIN_MINUTES:
            raise RuleInvalid("Ustunda turish muddati kamida 1 soat bo'ladi.")
        _checked_amount(amount)
    elif amount < 0 or amount > RULE_AMOUNT_MAX:
        raise RuleInvalid("Muddat noto'g'ri.")

    conditions: dict[str, Any] = {}
    if attempts_min:
        if board not in ATTEMPT_BOARDS:
            raise RuleInvalid("Bu kanbanda bog'lanish urinishlari sanalmaydi.")
        if attempts_min < 1 or attempts_min > RULE_ATTEMPTS_MAX:
            raise RuleInvalid("Urinishlar soni noto'g'ri.")
        conditions["attempts_min"] = attempts_min
    picked = sorted(set(plans or []))
    if picked:
        known = {*_plan_names(db), RULE_NO_PLAN}
        if any(code not in known for code in picked):
            raise RuleInvalid("Tarif topilmadi.")
        conditions["plans"] = picked
    if bill:
        if bill not in RuleBill.values:
            raise RuleInvalid("To'lov sharti noto'g'ri.")
        conditions["bill"] = bill

    actions: dict[str, Any] = {}
    if due_amount is not None:
        if due_unit not in RuleUnit.values:
            raise RuleInvalid("Muddat birligi noto'g'ri.")
        if due_amount < 0 or due_amount > RULE_AMOUNT_MAX:
            raise RuleInvalid("Muddat noto'g'ri.")
        actions["due"] = {"amount": due_amount, "unit": due_unit}
    if notify_manager or notify_lead:
        actions["notify"] = {
            "manager": bool(notify_manager),
            "lead": bool(notify_lead),
            "text": " ".join(notify_text.split())[:RULE_TEXT_MAX],
        }
    if assign_to:
        try:
            member = db.get(User, uuid.UUID(assign_to))
        except ValueError:
            member = None
        if member is None or not works_on(db, member, board):
            raise RuleInvalid("Bu xodim shu kanbanda ishlamaydi.")
        actions["assign"] = str(member.id)
    if not to and not actions:
        raise RuleInvalid(
            "Qoida nima qilishini tanlang: ustunga o'tkazish, vaqt qo'yish, "
            "xabar yuborish yoki xodimga berish."
        )
    return {
        "kind": kind,
        "name": cleaned,
        "from_columns": origin,
        "to_column": to,
        "amount": amount,
        "unit": unit,
        "reason": _checked_reason(reason),
        "conditions": conditions,
        "actions": actions,
    }


def add_custom(
    db: Session, *, board: Board, actor_id: uuid.UUID, now: datetime, **fields: Any
) -> BoardRule:
    """A rule of the superuser's own, last in the board's order."""
    ensure(db, now=now)
    have = _custom(db, board=board)
    if len(have) >= CUSTOM_RULES_MAX:
        raise TooManyRules(CUSTOM_RULES_MAX)
    values = _custom_fields(db, board=board, **fields)
    row = BoardRule(
        board=str(board),
        code=f"{CUSTOM_RULE_PREFIX}{uuid.uuid4().hex[:10]}",
        is_enabled=True,
        position=max((item.position for item in have), default=1000) + 1,
        created_by_id=actor_id,
        updated_by_id=actor_id,
        created_at=now,
        updated_at=now,
        **values,
    )
    db.add(row)
    db.commit()
    return row


def edit_custom(
    db: Session,
    *,
    board: Board,
    rule_id: uuid.UUID,
    is_enabled: bool,
    actor_id: uuid.UUID,
    now: datetime,
    **fields: Any,
) -> None:
    row = _row(db, board=board, rule_id=rule_id)
    if row.code in SPEC_BY_CODE:
        raise NoSuchRule
    values = _custom_fields(db, board=board, **fields)
    for key, value in values.items():
        setattr(row, key, value)
    row.is_enabled = is_enabled
    row.updated_by_id = actor_id
    row.updated_at = now
    db.commit()


def is_custom(db: Session, *, board: Board, rule_id: uuid.UUID) -> bool:
    return _row(db, board=board, rule_id=rule_id).code not in SPEC_BY_CODE


def code_of(db: Session, *, board: Board, rule_id: uuid.UUID) -> str:
    return _row(db, board=board, rule_id=rule_id).code


def remove_custom(db: Session, *, board: Board, rule_id: uuid.UUID) -> None:
    """One of the superuser's own rules, gone. The code's rules are
    switched off, never removed."""
    row = _row(db, board=board, rule_id=rule_id)
    if row.code in SPEC_BY_CODE:
        raise RuleFieldFixed
    db.delete(row)
    db.commit()


# -- the settings' view --------------------------------------------------------


def _amount_words(amount: int, unit: str) -> str:
    return f"{amount} {RULE_UNIT_LABELS[RuleUnit(unit)]}" if unit and amount else ""


def _sentence(
    *,
    when: str,
    then: str,
    names: dict[str, str],
    from_columns: tuple[str, ...],
    to_column: str,
    wait: str,
    amount_of: str,
) -> str:
    """The rule in one line of plain words, as the settings read it."""

    def name(code: str) -> str:
        return f"«{names.get(code, code)}»"

    head = when
    if wait:
        head = f"{head} ({wait} {amount_of})".replace("  ", " ").replace(" )", ")")
    origin = ""
    if from_columns:
        origin = " — " + ", ".join(name(code) for code in from_columns) + " ustunidan"
    what = then or (f"karta {name(to_column)}ga o'tadi" if to_column else "")
    return f"{head}{origin} → {what}."


def _workers(db: Session, *, board: Board) -> list[dict[str, str]]:
    from app.modules.boards.view import board_staff

    return board_staff(db, board=board)


def _own_sentence(
    rule: Own, *, names: dict[str, str], plans: dict[str, str], people: dict[str, str]
) -> str:
    """One of the superuser's rules in a line of plain words."""

    def column(code: str) -> str:
        return f"«{names.get(code, code)}»"

    def span(amount: int, unit: str) -> str:
        return f"{amount} {RULE_UNIT_LABELS[RuleUnit(unit)]}"

    origin = ", ".join(column(code) for code in rule.from_columns)
    if rule.kind == str(RuleKind.STAY):
        head = f"Karta {origin} ustunida {span(rule.amount, rule.unit)} tursa"
    elif rule.kind == str(RuleKind.DUE):
        late = f" va {span(rule.amount, rule.unit)} o'tsa" if rule.amount else ""
        head = f"{origin} ustunidagi kartaga qo'yilgan vaqt kelsa{late}"
    else:
        head = f"{origin} ustunidagi kartaning mijozi Yordam chatiga yozsa"
    also: list[str] = []
    if rule.attempts_min:
        also.append(f"{rule.attempts_min} marta bog'lanib bo'lmagan")
    if rule.plans:
        also.append("tarifi " + ", ".join(plans.get(code, code) for code in rule.plans))
    if rule.bill:
        also.append(str(RULE_BILL_LABELS[RuleBill(rule.bill)]))
    if also:
        head = f"{head} (sharti: {'; '.join(also)})"
    does: list[str] = []
    if rule.to_column:
        does.append(f"{column(rule.to_column)}ga o'tadi")
    if rule.assign_to:
        does.append(f"{people.get(rule.assign_to, 'xodim')}ga beriladi")
    if rule.due_minutes is not None:
        does.append(
            "muddati «hozir» bo'ladi"
            if rule.due_minutes == 0
            else f"muddati {_minutes_words(rule.due_minutes)}dan keyinga qo'yiladi"
        )
    if rule.notifies:
        who = " va ".join(
            word
            for word, on in (
                ("xodimiga", rule.notify_manager),
                ("rahbarga", rule.notify_lead),
            )
            if on
        )
        does.append(f"{who} Telegram xabar boradi")
    return f"{head} → karta {', '.join(does)}."


def _minutes_words(minutes: int) -> str:
    for unit in (RuleUnit.DAYS, RuleUnit.HOURS):
        size = RULE_UNIT_MINUTES[unit]
        if minutes % size == 0:
            return f"{minutes // size} {RULE_UNIT_LABELS[unit]}"
    return f"{minutes} {RULE_UNIT_LABELS[RuleUnit.MINUTES]}"


def settings_view(db: Session, *, board: Board, may_edit: bool) -> dict[str, Any]:
    """Every rule of the board in plain words: the code's with what may be
    changed of each, then the superuser's own; and the columns to pick."""
    ensure(db, now=utcnow())
    columns = list(
        db.scalars(
            select(BoardColumn)
            .where(BoardColumn.board == str(board))
            .order_by(BoardColumn.position, BoardColumn.code)
        )
    )
    names = {column.code: column.name for column in columns}
    shown = [column for column in columns if column.is_visible]
    rows = {
        row.code: row
        for row in db.scalars(select(BoardRule).where(BoardRule.board == str(board)))
    }
    system: list[dict[str, Any]] = []
    for spec in SPECS:
        if spec.board != board:
            continue
        row = rows.get(spec.code)
        rule = _of_spec(spec, row)
        changed = (
            not rule.enabled
            or rule.from_columns != spec.from_columns
            or rule.to_column != spec.to_column
            or rule.amount != spec.amount
            or rule.reason != spec.reason
        )
        system.append(
            {
                "id": str(row.id) if row is not None else "",
                "code": spec.code,
                "kind": str(RuleKind.SYSTEM),
                "name": spec.name,
                "sentence": _sentence(
                    when=spec.when,
                    then=spec.then,
                    names=names,
                    from_columns=rule.from_columns,
                    to_column=rule.to_column,
                    wait=_amount_words(rule.amount, rule.unit),
                    amount_of=spec.amount_of,
                ),
                "is_enabled": rule.enabled,
                "from_columns": list(rule.from_columns),
                "to_column": rule.to_column,
                "default_to": spec.to_column,
                "amount": rule.amount,
                "unit": rule.unit,
                "amount_of": spec.amount_of,
                "reason": rule.reason,
                "editable": sorted(spec.editable),
                "note": spec.note,
                "is_changed": changed,
                "is_custom": False,
            }
        )
    plan_names = {**_plan_names(db), RULE_NO_PLAN: RULE_NO_PLAN_LABEL}
    people = {item["id"]: item["name"] for item in _workers(db, board=board)}
    shown_codes = {column.code for column in shown}
    custom = []
    for row in _custom(db, board=board):
        own = _own_of_row(row)
        due = dict((row.actions or {}).get("due") or {})
        note = ""
        if own.to_column and own.to_column not in shown_codes:
            note = "Ustuni doskadan olib tashlangan: qoida ishlamaydi."
        elif own.assign_to and own.assign_to not in people:
            note = "Xodim endi bu kanbanda ishlamaydi: karta hech kimga berilmaydi."
        custom.append(
            {
                "id": str(row.id),
                "code": row.code,
                "kind": row.kind,
                "name": row.name,
                "sentence": _own_sentence(
                    own, names=names, plans=plan_names, people=people
                ),
                "is_enabled": row.is_enabled,
                "from_columns": list(own.from_columns),
                "to_column": own.to_column,
                "default_to": "",
                "amount": row.amount,
                "unit": row.unit,
                "amount_of": "",
                "reason": row.reason,
                "editable": [ENABLED, FROM, TO, AMOUNT, REASON],
                "note": note,
                "is_changed": False,
                "is_custom": True,
                "attempts_min": own.attempts_min,
                "plans": list(own.plans),
                "bill": own.bill,
                "due_amount": due.get("amount") if due else None,
                "due_unit": str(due.get("unit") or "") if due else "",
                "notify_manager": own.notify_manager,
                "notify_lead": own.notify_lead,
                "notify_text": own.notify_text,
                "assign_to": own.assign_to,
            }
        )
    return {
        "board": str(board),
        "may_edit": may_edit,
        "max_custom": CUSTOM_RULES_MAX,
        "rules": system + custom,
        "kinds": [
            {"value": str(kind), "label": str(RULE_KIND_LABELS[kind])}
            for kind in OWN_RULE_KINDS
        ],
        "plans": [
            {"value": code, "label": label} for code, label in plan_names.items()
        ],
        "bills": [
            {"value": str(item), "label": str(RULE_BILL_LABELS[item])}
            for item in RuleBill
        ],
        "staff": [
            {"value": item["id"], "label": item["name"]}
            for item in _workers(db, board=board)
        ],
        "counts_attempts": board in ATTEMPT_BOARDS,
        "units": [
            {"value": str(unit), "label": str(RULE_UNIT_LABELS[unit])}
            for unit in RuleUnit
        ],
        "from_choices": [
            {"code": column.code, "name": column.name}
            for column in shown
            if not column.is_final
            and (board, column.code) not in QUEUE_COLUMNS
            and not (board == Board.SALES and column.code in OFFER_COLUMNS)
        ],
        "to_choices": [
            {"code": column.code, "name": column.name}
            for column in shown
            if not column.is_final and column.kind == str(ColumnKind.MANUAL)
        ],
    }


def count_custom(db: Session, *, board: Board) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(BoardRule)
            .where(
                BoardRule.board == str(board),
                BoardRule.kind != str(RuleKind.SYSTEM),
            )
        )
        or 0
    )
