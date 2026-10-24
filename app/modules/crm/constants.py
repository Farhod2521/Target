from typing import Final

from app.common.choices import Choices

ACTION_TARGET_PROVIDER: Final = "crm"
MAX_MEMBERS: Final = 10
CARDS_PER_COLUMN: Final = 40
CLOSED_DAYS_ON_BOARD: Final = 30
BACKFILL_LIMIT: Final = 2000
SWEEP_WINDOW_HOURS: Final = 6
SWEEP_LIMIT: Final = 200
LOST_REASONS_SHOWN: Final = 5
MIN_PASSWORD_LENGTH: Final = 8


class SetupState(Choices):
    DRAFT = "draft"
    ON = "on"
    OFF = "off"


SETUP_STATE_LABELS = {
    SetupState.DRAFT: "Sozlanmagan",
    SetupState.ON: "Yoqiq",
    SetupState.OFF: "O'chiq",
}


class StageKind(Choices):
    NEW = "new"
    OPEN = "open"
    WON = "won"
    LOST = "lost"


STAGE_KIND_LABELS = {
    StageKind.NEW: "Yangi lid",
    StageKind.OPEN: "Jarayonda",
    StageKind.WON: "Sotildi",
    StageKind.LOST: "Rad etildi",
}
CLOSING_KINDS: Final = (StageKind.WON, StageKind.LOST)


class Distribution(Choices):
    ROUND_ROBIN = "round_robin"
    CLAIM = "claim"
    MANUAL = "manual"


DISTRIBUTION_LABELS = {
    Distribution.ROUND_ROBIN: "Navbat bilan, teng",
    Distribution.CLAIM: "Kim birinchi «Olish» bossa",
    Distribution.MANUAL: "Men o'zim beraman",
}


class Since(Choices):
    ONLY_NEW = "new"
    YESTERDAY = "yesterday"
    WEEK = "week"
    MONTH = "month"
    DATE = "date"


SINCE_LABELS = {
    Since.ONLY_NEW: "Faqat yangilar",
    Since.YESTERDAY: "Kechadan",
    Since.WEEK: "Hafta boshidan",
    Since.MONTH: "Oy boshidan",
    Since.DATE: "Aniq sana",
}


class ActivityKind(Choices):
    ARRIVED = "arrived"
    RETURNED = "returned"
    ASSIGNED = "assigned"
    TAKEN = "taken"
    MOVED = "moved"
    NOTE = "note"
    NO_ANSWER = "no_answer"
    DUE_SET = "due_set"
    DUE_DONE = "due_done"
    QUALIFIED = "qualified"
    WON = "won"
    LOST = "lost"
    REOPENED = "reopened"


ACTIVITY_KIND_LABELS = {
    ActivityKind.ARRIVED: "Reklamadan keldi",
    ActivityKind.RETURNED: "Qayta murojaat qildi",
    ActivityKind.ASSIGNED: "Menejerga berildi",
    ActivityKind.TAKEN: "Oldi",
    ActivityKind.MOVED: "Ustun almashdi",
    ActivityKind.NOTE: "Izoh",
    ActivityKind.NO_ANSWER: "Javob bermadi",
    ActivityKind.DUE_SET: "Muddat qo'yildi",
    ActivityKind.DUE_DONE: "Muddat bajarildi",
    ActivityKind.QUALIFIED: "Sifatli bo'ldi",
    ActivityKind.WON: "Sotildi",
    ActivityKind.LOST: "Rad etildi",
    ActivityKind.REOPENED: "Qayta ochildi",
}


class Flag(Choices):
    LATE = "late"
    TODAY = "today"


FLAG_LABELS = {Flag.LATE: "Muddat o'tgan", Flag.TODAY: "Bugun"}
COLORS: Final = (
    "#0A64E0",
    "#7C6CFF",
    "#0891B2",
    "#B7791F",
    "#D9480F",
    "#C2255C",
    "#4A5878",
    "#0E7F5C",
    "#C2262E",
)


class Preset(Choices):
    NEW = "new"
    WORKING = "working"
    INFORMED = "informed"
    CALLBACK = "callback"
    MEETING = "meeting"
    PAYMENT = "payment"
    WON = "won"
    LOST = "lost"


PRESET_LABELS = {
    Preset.NEW: "Yangi lid",
    Preset.WORKING: "Jarayonda",
    Preset.INFORMED: "Ma'lumot berildi",
    Preset.CALLBACK: "Qayta aloqa",
    Preset.MEETING: "Uchrashuv belgilandi",
    Preset.PAYMENT: "To'lov kutilmoqda",
    Preset.WON: "Sotildi",
    Preset.LOST: "Rad etildi",
}
PRESETS: Final = (
    (Preset.NEW, StageKind.NEW, "#0A64E0", True, True),
    (Preset.WORKING, StageKind.OPEN, "#7C6CFF", True, False),
    (Preset.INFORMED, StageKind.OPEN, "#0891B2", True, False),
    (Preset.CALLBACK, StageKind.OPEN, "#B7791F", False, False),
    (Preset.MEETING, StageKind.OPEN, "#4A5878", False, False),
    (Preset.PAYMENT, StageKind.OPEN, "#C2255C", False, False),
    (Preset.WON, StageKind.WON, "#0E7F5C", True, True),
    (Preset.LOST, StageKind.LOST, "#C2262E", True, True),
)
MAX_CUSTOM_STAGES: Final = 6
MAX_STAGES: Final = 12
DEFAULT_LOST_REASONS: Final = (
    "Qimmat",
    "Aloqaga chiqmadi",
    "Boshqasini tanladi",
    "Hozir kerak emas",
    "Noto'g'ri raqam",
    "Boshqa sabab",
)
