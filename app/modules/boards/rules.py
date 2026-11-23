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

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.boards.constants import (
    BILL_FROM_COLUMNS,
    CONFIRM_HOURS,
    CUSTOM_RULE_PREFIX,
    CUSTOM_RULES_MAX,
    IDLE_NO_LAUNCH_DAYS,
    META_ERROR_WAIT_MINUTES,
    NO_SPEND_HOURS,
    OFFER_COLUMNS,
    QUEUE_COLUMNS,
    RENEWAL_BILL_FROM,
    RENEWAL_DECLINE_DAYS,
    RENEWAL_OPEN_DAYS,
    RENEWAL_SILENT_COLUMNS,
    RULE_AMOUNT_MAX,
    RULE_KIND_LABELS,
    RULE_NAME_MAX,
    RULE_REASON_MAX,
    RULE_UNIT_LABELS,
    RULE_UNIT_MINUTES,
    SETUP_GRACE_MINUTES,
    STAY_RULE_MIN_MINUTES,
    SWEEP_BATCH,
    Board,
    ColumnKind,
    EventKind,
    RenewalColumn,
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
from app.modules.boards.models import BoardCard, BoardColumn, BoardRule

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
                BoardRule.kind.in_([str(RuleKind.STAY), str(RuleKind.DUE)]),
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


def run_custom(
    db: Session, *, board: Board, now: datetime, limit: int = SWEEP_BATCH
) -> int:
    """The superuser's own rules of the board, in their order. A card a
    rule moved is not looked at again in the same run. A rule whose column
    was taken off the board since does nothing."""
    from app.modules.boards.services import move

    moved: set[uuid.UUID] = set()
    for row in _custom(db, board=board):
        if not row.is_enabled or not row.from_columns:
            continue
        if not _target_ok(db, board=board, code=row.to_column):
            continue
        wait = timedelta(
            minutes=row.amount * RULE_UNIT_MINUTES[RuleUnit(row.unit or "hours")]
        )
        query = select(BoardCard).where(
            BoardCard.board == str(board),
            BoardCard.column_code.in_(row.from_columns),
            BoardCard.column_code != row.to_column,
        )
        if board != Board.SUPPORT:
            query = query.where(BoardCard.closed_at.is_(None))
        if row.kind == str(RuleKind.STAY):
            query = query.where(BoardCard.column_since <= now - wait)
        else:
            query = query.where(BoardCard.due_at <= now - wait)
        if moved:
            query = query.where(BoardCard.id.not_in(moved))
        cards = list(
            db.scalars(
                query.order_by(BoardCard.column_since)
                .limit(limit)
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
        )
        for card in cards:
            if row.kind == str(RuleKind.DUE):
                card.due_at = None
            move(
                db,
                card=card,
                to=row.to_column,
                kind=EventKind.RULE,
                now=now,
                body=f"{row.name}. {row.reason}" if row.reason else row.name,
            )
            moved.add(card.id)
        db.commit()
    return len(moved)


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
) -> dict[str, Any]:
    if kind not in (str(RuleKind.STAY), str(RuleKind.DUE)):
        raise RuleInvalid("Qoida turi noto'g'ri.")
    if unit not in RuleUnit.values:
        raise RuleInvalid("Muddat birligi noto'g'ri.")
    cleaned = " ".join(name.split())[:RULE_NAME_MAX]
    if not cleaned:
        raise RuleInvalid("Qoida nomini yozing.")
    to = _checked_to(db, board=board, code=to_column)
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
    return {
        "kind": kind,
        "name": cleaned,
        "from_columns": origin,
        "to_column": to,
        "amount": amount,
        "unit": unit,
        "reason": _checked_reason(reason),
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
    custom = [
        {
            "id": str(row.id),
            "code": row.code,
            "kind": row.kind,
            "name": row.name,
            "sentence": _sentence(
                when="Karta ustunda turgan bo'lsa"
                if row.kind == str(RuleKind.STAY)
                else "Kartaga qo'yilgan vaqt o'tgan bo'lsa",
                then="",
                names=names,
                from_columns=tuple(row.from_columns or ()),
                to_column=row.to_column,
                wait=_amount_words(row.amount, row.unit),
                amount_of="" if row.kind == str(RuleKind.STAY) else "o'tgach",
            ),
            "is_enabled": row.is_enabled,
            "from_columns": list(row.from_columns or []),
            "to_column": row.to_column,
            "default_to": "",
            "amount": row.amount,
            "unit": row.unit,
            "amount_of": "",
            "reason": row.reason,
            "editable": [ENABLED, FROM, TO, AMOUNT, REASON],
            "note": ""
            if row.to_column in {c.code for c in shown}
            else "Ustuni doskadan olib tashlangan: qoida ishlamaydi.",
            "is_changed": False,
            "is_custom": True,
        }
        for row in _custom(db, board=board)
    ]
    return {
        "board": str(board),
        "may_edit": may_edit,
        "max_custom": CUSTOM_RULES_MAX,
        "rules": system + custom,
        "kinds": [
            {"value": str(kind), "label": str(RULE_KIND_LABELS[kind])}
            for kind in (RuleKind.STAY, RuleKind.DUE)
        ],
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
