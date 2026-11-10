from typing import Final, NamedTuple

from app.common.choices import Choices
from app.modules.backoffice.constants import Role


class Board(Choices):
    SALES = "sales"
    SUPPORT = "support"


BOARD_LABELS = {Board.SALES: "Sotuv", Board.SUPPORT: "Support"}


class ColumnKind(Choices):
    # Moved by a button.
    MANUAL = "manual"
    # Moved by what happened to the client; wins over a manual column.
    AUTO = "auto"


COLUMN_KIND_LABELS = {ColumnKind.MANUAL: "Tugma bilan", ColumnKind.AUTO: "Avtomatik"}


class SalesColumn(Choices):
    UNWORKED = "unworked"
    NEW_LEAD = "new_lead"
    NO_CONTACT = "no_contact"
    CONTACTED = "contacted"
    # Kept hidden until the free trial and the discount are built.
    TRIAL = "trial"
    DISCOUNT_20 = "discount_20"
    DISCOUNT_10 = "discount_10"
    NO_DISCOUNT = "no_discount"
    SOLD = "sold"
    CLOSED = "closed"


SALES_COLUMN_LABELS = {
    SalesColumn.UNWORKED: "Ishlanmagan",
    SalesColumn.NEW_LEAD: "Yangi lead",
    SalesColumn.NO_CONTACT: "Bog'lanilmadi",
    SalesColumn.CONTACTED: "Bog'lanildi",
    SalesColumn.TRIAL: "Sinovda",
    SalesColumn.DISCOUNT_20: "20% chegirma",
    SalesColumn.DISCOUNT_10: "10% chegirma",
    SalesColumn.NO_DISCOUNT: "Chegirmasiz",
    SalesColumn.SOLD: "Sotildi",
    SalesColumn.CLOSED: "Yopildi",
}


class SupportColumn(Choices):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"


SUPPORT_COLUMN_LABELS = {
    SupportColumn.NEW: "Yangi",
    SupportColumn.IN_PROGRESS: "Ishlanmoqda",
    SupportColumn.RESOLVED: "Hal qilindi",
}


class SeedColumn(NamedTuple):
    board: Board
    code: str
    name: str
    kind: ColumnKind
    is_final: bool
    is_visible: bool


def _sales(
    code: SalesColumn, kind: ColumnKind, *, final: bool = False, shown: bool = True
) -> SeedColumn:
    return SeedColumn(
        Board.SALES, str(code), SALES_COLUMN_LABELS[code], kind, final, shown
    )


def _support(
    code: SupportColumn, kind: ColumnKind, *, final: bool = False
) -> SeedColumn:
    return SeedColumn(
        Board.SUPPORT, str(code), SUPPORT_COLUMN_LABELS[code], kind, final, True
    )


# The columns each board starts with, in their first order. The code never
# changes; the office may rename and reorder them.
SEED_COLUMNS: Final[tuple[SeedColumn, ...]] = (
    _sales(SalesColumn.UNWORKED, ColumnKind.AUTO),
    _sales(SalesColumn.NEW_LEAD, ColumnKind.MANUAL),
    _sales(SalesColumn.NO_CONTACT, ColumnKind.MANUAL),
    _sales(SalesColumn.CONTACTED, ColumnKind.MANUAL),
    _sales(SalesColumn.TRIAL, ColumnKind.AUTO, shown=False),
    _sales(SalesColumn.DISCOUNT_20, ColumnKind.AUTO, shown=False),
    _sales(SalesColumn.DISCOUNT_10, ColumnKind.AUTO, shown=False),
    _sales(SalesColumn.NO_DISCOUNT, ColumnKind.AUTO, shown=False),
    _sales(SalesColumn.SOLD, ColumnKind.AUTO, final=True),
    _sales(SalesColumn.CLOSED, ColumnKind.MANUAL, final=True),
    _support(SupportColumn.NEW, ColumnKind.AUTO),
    _support(SupportColumn.IN_PROGRESS, ColumnKind.MANUAL),
    _support(SupportColumn.RESOLVED, ColumnKind.MANUAL, final=True),
)

# Columns only a board's lead (and the superuser or Owner) sees.
LEAD_ONLY_COLUMNS: Final = frozenset(
    {str(SalesColumn.UNWORKED), str(SalesColumn.CLOSED)}
)

# Who works each board. The superuser and the Owner role see both.
BOARD_ROLES: Final = {
    Board.SALES: (Role.SALES, Role.SALES_LEAD),
    Board.SUPPORT: (Role.SUPPORT,),
}
LEAD_ROLES: Final = {Board.SALES: (Role.SALES_LEAD,), Board.SUPPORT: ()}
FULL_ROLES: Final = (Role.OWNER,)

COLUMN_NAME_MAX: Final = 40
CODE_MAX: Final = 24


class CardAction(Choices):
    CONTACTED = "contacted"
    NO_CONTACT = "no_contact"
    NEEDS_SUPPORT = "needs_support"
    CLOSE = "close"
    START = "start"
    RESOLVE = "resolve"


CARD_ACTION_LABELS = {
    CardAction.CONTACTED: "Bog'lanildi",
    CardAction.NO_CONTACT: "Bog'lanilmadi",
    CardAction.NEEDS_SUPPORT: "Support kerak",
    CardAction.CLOSE: "Yopildi",
    CardAction.START: "Ishlayapman",
    CardAction.RESOLVE: "Hal qilindi",
}

# The buttons each Sales column shows. "Support kerak" comes after a talk:
# the client asked for help while the manager was on the phone with them.
SALES_ACTIONS: Final[dict[str, tuple[CardAction, ...]]] = {
    str(SalesColumn.NEW_LEAD): (
        CardAction.CONTACTED,
        CardAction.NO_CONTACT,
        CardAction.CLOSE,
    ),
    str(SalesColumn.NO_CONTACT): (CardAction.CONTACTED, CardAction.CLOSE),
    str(SalesColumn.CONTACTED): (CardAction.NEEDS_SUPPORT, CardAction.CLOSE),
}


# The buttons each Support column shows. A solved ticket has none: a new
# reason reopens it on its own.
SUPPORT_ACTIONS: Final[dict[str, tuple[CardAction, ...]]] = {
    str(SupportColumn.NEW): (CardAction.START,),
    str(SupportColumn.IN_PROGRESS): (CardAction.RESOLVE,),
}


class TicketReason(Choices):
    SETUP = "setup"
    FROM_SALES = "from_sales"
    META_ERROR = "meta_error"
    SURVEY = "survey"
    IDLE = "idle"


TICKET_REASON_LABELS = {
    TicketReason.SETUP: "Sozlash tugamadi",
    TicketReason.FROM_SALES: "Sotuvdan: yordam kerak",
    TicketReason.META_ERROR: "Meta xatosi",
    TicketReason.SURVEY: "So'rovnoma: yordam kerak",
    TicketReason.IDLE: "Ishlamayapti",
}

# Paid this long ago and still not set up: Support calls.
SETUP_GRACE_MINUTES: Final = 60
# Paid this many days ago and no ad switched on since: Support calls.
IDLE_NO_LAUNCH_DAYS: Final = 3
# Switched on this long ago, running, and not a sum spent: Support calls.
NO_SPEND_HOURS: Final = 24
# Only campaigns switched on this recently are looked at for spend.
NO_SPEND_LOOKBACK_DAYS: Final = 30
# A campaign's state older than this is not trusted to say it is running.
CAMPAIGN_FRESH_HOURS: Final = 6
# Survey answers are read this far back each run.
SURVEY_LOOKBACK_HOURS: Final = 24
# A failed press that is not Meta's refusal: nothing for Support to fix.
NOT_META_ERRORS: Final = frozenset({"already", "finished", "temporary", "in_use"})


class CloseReason(Choices):
    EXPENSIVE = "expensive"
    NOT_NEEDED = "not_needed"
    NO_ANSWER = "no_answer"
    WRONG_NUMBER = "wrong_number"
    OTHER = "other"


CLOSE_REASON_LABELS = {
    CloseReason.EXPENSIVE: "Qimmat",
    CloseReason.NOT_NEEDED: "Kerak emas",
    CloseReason.NO_ANSWER: "Javob bermaydi",
    CloseReason.WRONG_NUMBER: "Raqam noto'g'ri",
    CloseReason.OTHER: "Boshqa",
}


class EventKind(Choices):
    OPENED = "opened"
    TAKEN = "taken"
    ASSIGNED = "assigned"
    RETURNED = "returned"
    CONTACTED = "contacted"
    NO_CONTACT = "no_contact"
    SUPPORT_ON = "support_on"
    SUPPORT_OFF = "support_off"
    NOTE = "note"
    CLOSED = "closed"
    SOLD = "sold"
    TICKET = "ticket"
    REASON = "reason"
    REOPENED = "reopened"
    STARTED = "started"
    RESOLVED = "resolved"
    MOVED = "moved"


EVENT_KIND_LABELS = {
    EventKind.OPENED: "Lid ochildi",
    EventKind.TAKEN: "Lid olindi",
    EventKind.ASSIGNED: "Menejerga berildi",
    EventKind.RETURNED: "Qaytarib olindi",
    EventKind.CONTACTED: "Bog'lanildi",
    EventKind.NO_CONTACT: "Bog'lanilmadi",
    EventKind.SUPPORT_ON: "Support kerak deb belgilandi",
    EventKind.SUPPORT_OFF: "Support kerak belgisi olib tashlandi",
    EventKind.NOTE: "Izoh",
    EventKind.CLOSED: "Yopildi",
    EventKind.SOLD: "Sotildi",
    EventKind.TICKET: "Zayavka ochildi",
    EventKind.REASON: "Yangi sabab",
    EventKind.REOPENED: "Zayavka qayta ochildi",
    EventKind.STARTED: "Ishga olindi",
    EventKind.RESOLVED: "Hal qilindi",
    EventKind.MOVED: "Qo'lda ko'chirildi",
}

NOTE_MAX: Final = 2000
COLUMN_CARDS: Final = 50
COLUMN_CARDS_MAX: Final = 200
SWEEP_BATCH: Final = 500
SEARCH_MAX: Final = 100
