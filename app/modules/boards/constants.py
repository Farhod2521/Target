from typing import Final, NamedTuple

from app.common.choices import Choices
from app.modules.backoffice.constants import Role


class Board(Choices):
    SALES = "sales"
    SUPPORT = "support"
    # Paying clients whose term is running out: the renewal manager calls.
    RENEWAL = "renewal"


BOARD_LABELS = {
    Board.SALES: "Sotuv",
    Board.SUPPORT: "Support",
    Board.RENEWAL: "Uzaytirish",
}


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
    # The client asked to be called later, or is thinking: a time is set.
    CALLBACK = "callback"
    # Kept hidden until the free trial is built.
    TRIAL = "trial"
    # The discount's own clock: 20% for a day, then 10% for three more.
    DISCOUNT_20 = "discount_20"
    DISCOUNT_10 = "discount_10"
    NO_DISCOUNT = "no_discount"
    # The client opened a bill, or told the manager they will pay.
    AWAITING = "awaiting"
    SOLD = "sold"
    CLOSED = "closed"


SALES_COLUMN_LABELS = {
    SalesColumn.UNWORKED: "Ishlanmagan",
    SalesColumn.NEW_LEAD: "Yangi lead",
    SalesColumn.NO_CONTACT: "Bog'lanilmadi",
    SalesColumn.CONTACTED: "Bog'lanildi",
    SalesColumn.CALLBACK: "Qayta aloqa",
    SalesColumn.TRIAL: "Sinovda",
    SalesColumn.DISCOUNT_20: "20% chegirma",
    SalesColumn.DISCOUNT_10: "10% chegirma",
    SalesColumn.NO_DISCOUNT: "Chegirmasiz",
    SalesColumn.AWAITING: "To'lov kutilmoqda",
    SalesColumn.SOLD: "Sotildi",
    SalesColumn.CLOSED: "Yopildi",
}


class SupportColumn(Choices):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    # Support did its part; the client's answer or action is waited for.
    WAITING = "waiting"
    # A fault only a developer can mend; the ticket stays its person's.
    DEVELOPER = "developer"
    # Support says it is solved; the client is asked whether it is.
    CONFIRMING = "confirming"
    # The client said yes.
    RESOLVED = "resolved"
    # The client did not answer the question in time.
    CLOSED = "closed"


SUPPORT_COLUMN_LABELS = {
    SupportColumn.NEW: "Yangi",
    SupportColumn.IN_PROGRESS: "Ishlanmoqda",
    SupportColumn.WAITING: "Mijoz kutilmoqda",
    SupportColumn.DEVELOPER: "Dasturchiga berildi",
    SupportColumn.CONFIRMING: "Tasdiq kutilmoqda",
    SupportColumn.RESOLVED: "Hal qilindi",
    SupportColumn.CLOSED: "Yopildi",
}


class RenewalColumn(Choices):
    # The term ends within the window; nobody has called yet.
    ENDING = "ending"
    # The term ended while the card still stood in Tugayapti.
    ENDED = "ended"
    NO_CONTACT = "no_contact"
    CONTACTED = "contacted"
    CALLBACK = "callback"
    AWAITING = "awaiting"
    # The client paid Standart or Pro.
    RENEWED = "renewed"
    DECLINED = "declined"


RENEWAL_COLUMN_LABELS = {
    RenewalColumn.ENDING: "Tugayapti",
    RenewalColumn.ENDED: "Tugagan",
    RenewalColumn.NO_CONTACT: "Bog'lanilmadi",
    RenewalColumn.CONTACTED: "Bog'lanildi",
    RenewalColumn.CALLBACK: "Qayta aloqa",
    RenewalColumn.AWAITING: "To'lov kutilmoqda",
    RenewalColumn.RENEWED: "Uzaytirdi",
    RenewalColumn.DECLINED: "Rad etdi",
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


def _renewal(
    code: RenewalColumn, kind: ColumnKind, *, final: bool = False
) -> SeedColumn:
    return SeedColumn(
        Board.RENEWAL, str(code), RENEWAL_COLUMN_LABELS[code], kind, final, True
    )


# The columns each board starts with, in their first order. The code never
# changes; the office may rename and reorder them.
SEED_COLUMNS: Final[tuple[SeedColumn, ...]] = (
    _sales(SalesColumn.UNWORKED, ColumnKind.AUTO),
    _sales(SalesColumn.NEW_LEAD, ColumnKind.MANUAL),
    _sales(SalesColumn.NO_CONTACT, ColumnKind.MANUAL),
    _sales(SalesColumn.CONTACTED, ColumnKind.MANUAL),
    _sales(SalesColumn.CALLBACK, ColumnKind.MANUAL),
    _sales(SalesColumn.TRIAL, ColumnKind.AUTO, shown=False),
    _sales(SalesColumn.DISCOUNT_20, ColumnKind.AUTO),
    _sales(SalesColumn.DISCOUNT_10, ColumnKind.AUTO),
    # Not reached any more: a card whose discount ran out closes.
    _sales(SalesColumn.NO_DISCOUNT, ColumnKind.AUTO, shown=False),
    _sales(SalesColumn.AWAITING, ColumnKind.AUTO),
    _sales(SalesColumn.SOLD, ColumnKind.AUTO, final=True),
    _sales(SalesColumn.CLOSED, ColumnKind.MANUAL, final=True),
    _support(SupportColumn.NEW, ColumnKind.AUTO),
    _support(SupportColumn.IN_PROGRESS, ColumnKind.MANUAL),
    _support(SupportColumn.WAITING, ColumnKind.MANUAL),
    _support(SupportColumn.DEVELOPER, ColumnKind.MANUAL),
    _support(SupportColumn.CONFIRMING, ColumnKind.MANUAL),
    _support(SupportColumn.RESOLVED, ColumnKind.AUTO, final=True),
    _support(SupportColumn.CLOSED, ColumnKind.AUTO, final=True),
    _renewal(RenewalColumn.ENDING, ColumnKind.AUTO),
    _renewal(RenewalColumn.ENDED, ColumnKind.AUTO),
    _renewal(RenewalColumn.NO_CONTACT, ColumnKind.MANUAL),
    _renewal(RenewalColumn.CONTACTED, ColumnKind.MANUAL),
    _renewal(RenewalColumn.CALLBACK, ColumnKind.MANUAL),
    _renewal(RenewalColumn.AWAITING, ColumnKind.MANUAL),
    _renewal(RenewalColumn.RENEWED, ColumnKind.AUTO, final=True),
    _renewal(RenewalColumn.DECLINED, ColumnKind.MANUAL, final=True),
)

# Columns only a board's lead (and the superuser or Owner) sees. Support's
# own Yopildi is its person's to read.
LEAD_ONLY_COLUMNS: Final = frozenset(
    {
        (Board.SALES, str(SalesColumn.UNWORKED)),
        (Board.SALES, str(SalesColumn.CLOSED)),
    }
)

# Who works each board. The superuser and the Owner role see both.
BOARD_ROLES: Final = {
    Board.SALES: (Role.SALES, Role.SALES_LEAD),
    Board.SUPPORT: (Role.SUPPORT,),
    Board.RENEWAL: (Role.RENEWAL, Role.SALES_LEAD),
}
LEAD_ROLES: Final = {
    Board.SALES: (Role.SALES_LEAD,),
    Board.SUPPORT: (),
    Board.RENEWAL: (Role.SALES_LEAD,),
}
# Whom a board's cards are given to. The Sales lead reads the renewal board
# whole but is not its manager.
WORKER_ROLES: Final = {
    Board.SALES: (Role.SALES, Role.SALES_LEAD),
    Board.SUPPORT: (Role.SUPPORT,),
    Board.RENEWAL: (Role.RENEWAL,),
}
FULL_ROLES: Final = (Role.OWNER,)

COLUMN_NAME_MAX: Final = 40
CODE_MAX: Final = 24


class CardAction(Choices):
    CONTACTED = "contacted"
    NO_CONTACT = "no_contact"
    CALLBACK = "callback"
    WILL_PAY = "will_pay"
    NEEDS_SUPPORT = "needs_support"
    OFFER = "offer"
    CLOSE = "close"
    RELEASE = "release"
    START = "start"
    WAIT = "wait"
    RESOLVE = "resolve"
    REOPEN = "reopen"
    TO_DEVELOPER = "to_developer"
    # Renewal: the client will not renew; the reason is picked.
    DECLINE = "decline"


CARD_ACTION_LABELS = {
    CardAction.CONTACTED: "Gaplashildi",
    CardAction.NO_CONTACT: "Bog'lanib bo'lmadi",
    CardAction.CALLBACK: "Vaqt qo'yish",
    CardAction.WILL_PAY: "To'laydi",
    CardAction.NEEDS_SUPPORT: "Support kerak",
    CardAction.OFFER: "Chegirma berish",
    CardAction.CLOSE: "Yopish",
    CardAction.RELEASE: "Navbatga qaytarish",
    CardAction.START: "Ishlayapman",
    CardAction.WAIT: "Mijoz kutilmoqda",
    CardAction.RESOLVE: "Hal qilindi",
    CardAction.REOPEN: "Qayta ochish",
    CardAction.TO_DEVELOPER: "Dasturchiga berish",
    CardAction.DECLINE: "Rad etdi",
}
# On Support the same button gives the ticket up, not a lead back.
SUPPORT_ACTION_LABELS: Final = {CardAction.RELEASE: "Voz kechish"}

# What a button asks for besides the press: `due` is a time, `note` a line,
# `reason` a close reason. `required` ones are refused when empty.
ACTION_DUE_REQUIRED: Final = frozenset({CardAction.CALLBACK, CardAction.WAIT})
ACTION_DUE_OPTIONAL: Final = frozenset({CardAction.NO_CONTACT, CardAction.WILL_PAY})
ACTION_NOTE_REQUIRED: Final = frozenset(
    {
        CardAction.RELEASE,
        CardAction.RESOLVE,
        CardAction.TO_DEVELOPER,
        # Sales: Support reads why the client needs it.
        CardAction.NEEDS_SUPPORT,
    }
)

# The buttons each Sales column shows. The manager says what the call came
# to and sets a time to call again; the system moves the card. «Support
# kerak» is pressed with its reason written. Giving a lead back is the
# lead's (the Owner's, the superuser's): `POST /cards/{id}/assign`.
_CALL: Final = (CardAction.CONTACTED, CardAction.NO_CONTACT, CardAction.CALLBACK)
SALES_ACTIONS: Final[dict[str, tuple[CardAction, ...]]] = {
    str(SalesColumn.NEW_LEAD): (*_CALL, CardAction.CLOSE),
    str(SalesColumn.NO_CONTACT): (*_CALL, CardAction.CLOSE),
    str(SalesColumn.CONTACTED): (
        CardAction.CALLBACK,
        CardAction.NEEDS_SUPPORT,
        CardAction.CLOSE,
    ),
    str(SalesColumn.CALLBACK): (*_CALL, CardAction.NEEDS_SUPPORT, CardAction.CLOSE),
    # The discount's clock owns the column: here the same buttons leave
    # their mark on the card and do not move it.
    str(SalesColumn.DISCOUNT_20): (
        *_CALL,
        CardAction.NEEDS_SUPPORT,
        CardAction.CLOSE,
    ),
    str(SalesColumn.DISCOUNT_10): (
        *_CALL,
        CardAction.NEEDS_SUPPORT,
        CardAction.CLOSE,
    ),
    str(SalesColumn.NO_DISCOUNT): (
        CardAction.CALLBACK,
        CardAction.NEEDS_SUPPORT,
        CardAction.CLOSE,
    ),
    str(SalesColumn.AWAITING): (
        CardAction.CALLBACK,
        CardAction.NEEDS_SUPPORT,
        CardAction.CLOSE,
    ),
}
# A client's own bill moves the card to «To'lov kutilmoqda» from these.
BILL_FROM_COLUMNS: Final = frozenset(
    {
        str(SalesColumn.NEW_LEAD),
        str(SalesColumn.NO_CONTACT),
        str(SalesColumn.CONTACTED),
        str(SalesColumn.CALLBACK),
        str(SalesColumn.NO_DISCOUNT),
    }
)

# The discount starts on its own: when the client pays Start, or when the
# manager presses «Gaplashildi» on a lead who has not. Each step: the
# percent, the hour after the start it lasts until, and its column: 20% for
# a day, then 10% for three more days. When the last ends the card closes.
OFFER_STEPS: Final[tuple[tuple[int, int, SalesColumn], ...]] = (
    (20, 24, SalesColumn.DISCOUNT_20),
    (10, 96, SalesColumn.DISCOUNT_10),
)
OFFER_COLUMNS: Final = frozenset(str(step[2]) for step in OFFER_STEPS)
OFFER_HOURS: Final = OFFER_STEPS[-1][1]
# A bill priced with the offer stays payable this long after its step ends.
OFFER_INVOICE_GRACE_MINUTES: Final = 15
# Why a card closed when its discount ran out; not a reason a person picks.
OFFER_ENDED_REASON: Final = "offer_ended"
OFFER_ENDED_LABEL: Final = "Chegirma tugadi"


# The buttons each Support column shows. «Hal qilindi» does not close the
# ticket: the client is asked, and their yes does. A closed ticket is
# reopened by a new reason on its own, or by «Qayta ochish».
SUPPORT_ACTIONS: Final[dict[str, tuple[CardAction, ...]]] = {
    str(SupportColumn.NEW): (CardAction.START,),
    str(SupportColumn.IN_PROGRESS): (
        CardAction.WAIT,
        CardAction.TO_DEVELOPER,
        CardAction.RESOLVE,
        CardAction.RELEASE,
    ),
    str(SupportColumn.WAITING): (
        CardAction.START,
        CardAction.RESOLVE,
        CardAction.RELEASE,
    ),
    str(SupportColumn.DEVELOPER): (CardAction.START, CardAction.RESOLVE),
    str(SupportColumn.CONFIRMING): (CardAction.REOPEN,),
    str(SupportColumn.RESOLVED): (CardAction.REOPEN,),
    str(SupportColumn.CLOSED): (CardAction.REOPEN,),
}
# A new reason reopens a ticket standing in these.
SUPPORT_DONE_COLUMNS: Final = frozenset(
    {
        str(SupportColumn.CONFIRMING),
        str(SupportColumn.RESOLVED),
        str(SupportColumn.CLOSED),
    }
)
# «Zayavka olish» gives one ticket a press, while this person has fewer
# than this many in Ishlanmoqda. What comes back on its own (a timer, the
# client's "no", the Owner's hand) is not held by it.
TICKET_TAKE_LIMIT: Final = 5
# The client has this long to say whether the problem is solved.
CONFIRM_HOURS: Final = 24
# How many of the sales manager's notes go with a ticket from Sales.
SALES_NOTES_CARRIED: Final = 5


# -- Uzaytirish ------------------------------------------------------------

# The plans whose paying clients are called before the term ends. Start,
# Enterprise, a trial and a plan the office gave without a payment are not.
RENEWAL_PLAN_CODES: Final = ("standart", "pro")
# A card opens this many days before the term ends.
RENEWAL_OPEN_DAYS: Final = 3
# Ended this long ago and nobody reached: the card is declined on its own.
# The first run also opens cards for terms that ended inside this window.
RENEWAL_DECLINE_DAYS: Final = 30

_RENEWAL_CALL: Final = (
    CardAction.CONTACTED,
    CardAction.NO_CONTACT,
    CardAction.CALLBACK,
)
RENEWAL_ACTIONS: Final[dict[str, tuple[CardAction, ...]]] = {
    str(RenewalColumn.ENDING): (*_RENEWAL_CALL, CardAction.DECLINE),
    str(RenewalColumn.ENDED): (*_RENEWAL_CALL, CardAction.DECLINE),
    str(RenewalColumn.NO_CONTACT): (*_RENEWAL_CALL, CardAction.DECLINE),
    str(RenewalColumn.CONTACTED): (
        CardAction.CALLBACK,
        CardAction.WILL_PAY,
        CardAction.DECLINE,
    ),
    str(RenewalColumn.CALLBACK): (
        *_RENEWAL_CALL,
        CardAction.WILL_PAY,
        CardAction.DECLINE,
    ),
    str(RenewalColumn.AWAITING): (CardAction.CALLBACK, CardAction.DECLINE),
}
# A client's own bill moves the card to «To'lov kutilmoqda» from these.
RENEWAL_BILL_FROM: Final = frozenset(
    {
        str(RenewalColumn.ENDING),
        str(RenewalColumn.ENDED),
        str(RenewalColumn.NO_CONTACT),
        str(RenewalColumn.CONTACTED),
        str(RenewalColumn.CALLBACK),
    }
)
# Nobody reached the client in these: thirty days after the end they close.
RENEWAL_SILENT_COLUMNS: Final = frozenset(
    {str(RenewalColumn.ENDED), str(RenewalColumn.NO_CONTACT)}
)


class DeclineReason(Choices):
    EXPENSIVE = "expensive"
    NO_RESULT = "no_result"
    META_PROBLEM = "meta_problem"
    BUSINESS_STOPPED = "business_stopped"
    SWITCHED = "switched"
    NO_ANSWER = "no_answer"
    OTHER = "other"


DECLINE_REASON_LABELS = {
    DeclineReason.EXPENSIVE: "Qimmat",
    DeclineReason.NO_RESULT: "Natija bo'lmadi",
    DeclineReason.META_PROBLEM: "Meta muammosi",
    DeclineReason.BUSINESS_STOPPED: "Biznes to'xtadi",
    DeclineReason.SWITCHED: "Boshqa tizimga o'tdi",
    DeclineReason.NO_ANSWER: "Javob bermadi",
    DeclineReason.OTHER: "Boshqa",
}


class AttemptsFilter(Choices):
    NONE = "0"
    FEW = "1-2"
    MANY = "3+"


# The report reads at most this long a period.
REPORT_MAX_DAYS: Final = 366
REPORT_DEFAULT_DAYS: Final = 30


class TicketReason(Choices):
    SETUP = "setup"
    FROM_SALES = "from_sales"
    META_ERROR = "meta_error"
    SURVEY = "survey"
    IDLE = "idle"
    # The client pressed «Mutaxassisga yuborish» in the assistant's chat.
    AI = "ai"
    # Opened by hand in the office.
    MANUAL = "manual"


TICKET_REASON_LABELS = {
    TicketReason.SETUP: "Sozlash tugamadi",
    TicketReason.FROM_SALES: "Sotuvdan: yordam kerak",
    TicketReason.META_ERROR: "Meta xatosi",
    TicketReason.SURVEY: "So'rovnoma: yordam kerak",
    TicketReason.IDLE: "Ishlamayapti",
    TicketReason.AI: "AI chatdan",
    TicketReason.MANUAL: "Qo'lda ochilgan",
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
    OFFERED = "offered"
    START_BOUGHT = "start_bought"
    OFFER_STEP = "offer_step"
    OFFER_ENDED = "offer_ended"
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
    ADDED = "added"
    CALLBACK = "callback"
    WILL_PAY = "will_pay"
    BILL_OPENED = "bill_opened"
    BILL_UNPAID = "bill_unpaid"
    RELEASED = "released"
    WAITING = "waiting"
    CLIENT_REPLIED = "client_replied"
    DUE_SET = "due_set"
    DUE_CLEARED = "due_cleared"
    MISSED_CALL = "missed_call"
    TICKET_TAKEN = "ticket_taken"
    DEVELOPER = "developer"
    WAIT_OVER = "wait_over"
    ASKED = "asked"
    CONFIRMED = "confirmed"
    DENIED = "denied"
    UNANSWERED = "unanswered"
    TERM_ENDING = "term_ending"
    TERM_ENDED = "term_ended"
    TERM_MOVED = "term_moved"
    RENEWED = "renewed"
    DECLINED = "declined"
    SILENT = "silent"


EVENT_KIND_LABELS = {
    EventKind.OPENED: "Lid ochildi",
    EventKind.TAKEN: "Lid olindi",
    EventKind.ASSIGNED: "Menejerga berildi",
    EventKind.RETURNED: "Qaytarib olindi",
    EventKind.CONTACTED: "Bog'lanildi",
    EventKind.NO_CONTACT: "Bog'lanilmadi",
    EventKind.OFFERED: "20% chegirma boshlandi",
    EventKind.START_BOUGHT: "Start sotib oldi, chegirma boshlandi",
    EventKind.OFFER_STEP: "Chegirma 10% ga tushdi",
    EventKind.OFFER_ENDED: "Chegirma tugadi",
    EventKind.SUPPORT_ON: "Support kerak deb belgilandi",
    EventKind.SUPPORT_OFF: "Support kerak belgisi olib tashlandi",
    EventKind.NOTE: "Izoh",
    EventKind.CLOSED: "Yopildi",
    EventKind.SOLD: "Sotildi",
    EventKind.TICKET: "Zayavka ochildi",
    EventKind.REASON: "Yangi sabab",
    EventKind.REOPENED: "Zayavka qayta ochildi",
    EventKind.STARTED: "Ishga olindi",
    EventKind.RESOLVED: "Xodim: hal qilindi",
    EventKind.MOVED: "Qo'lda ko'chirildi",
    EventKind.ADDED: "Qo'lda qo'shildi",
    EventKind.CALLBACK: "Qayta aloqa belgilandi",
    EventKind.WILL_PAY: "To'laydi",
    EventKind.BILL_OPENED: "Mijoz hisob ochdi",
    EventKind.BILL_UNPAID: "Hisob to'lanmadi",
    EventKind.RELEASED: "Xodim kartani qaytardi",
    EventKind.WAITING: "Mijoz javobi kutilmoqda",
    EventKind.CLIENT_REPLIED: "Mijoz javob yozdi",
    EventKind.DUE_SET: "Muddat qo'yildi",
    EventKind.DUE_CLEARED: "Muddat olib tashlandi",
    EventKind.MISSED_CALL: "Javobsiz qo'ng'iroq",
    EventKind.TICKET_TAKEN: "Zayavka olindi",
    EventKind.DEVELOPER: "Dasturchiga berildi",
    EventKind.WAIT_OVER: "Kutish vaqti tugadi",
    EventKind.ASKED: "Mijozdan so'raldi: hal bo'ldimi?",
    EventKind.CONFIRMED: "Mijoz tasdiqladi: hal bo'ldi",
    EventKind.DENIED: "Mijoz: hal bo'lmadi",
    EventKind.UNANSWERED: "Mijoz javob bermadi, yopildi",
    EventKind.TERM_ENDING: "Obuna tugayapti",
    EventKind.TERM_ENDED: "Obuna tugadi",
    EventKind.TERM_MOVED: "Obuna muddati o'zgardi",
    EventKind.RENEWED: "Uzaytirdi",
    EventKind.DECLINED: "Rad etdi",
    EventKind.SILENT: "30 kun javob bermadi, yopildi",
}

NOTE_MAX: Final = 2000
COLUMN_CARDS: Final = 50
COLUMN_CARDS_MAX: Final = 200
SWEEP_BATCH: Final = 500
SEARCH_MAX: Final = 100
# A deadline is set this far ahead at most.
DUE_MAX_DAYS: Final = 365
# A minute of slack for a time picked "now" and sent a moment later.
DUE_PAST_SLACK_SECONDS: Final = 60


class DueFilter(Choices):
    OVERDUE = "overdue"
    TODAY = "today"
    SET = "set"


# «Bog'lanilmadi» is counted up to this; the column is a small integer.
ATTEMPTS_MAX: Final = 999
CLIENT_SEARCH_ROWS: Final = 20
