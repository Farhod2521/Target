from typing import Final

from app.common.choices import Choices
from app.modules.audit.constants import ActionType


class SheetStatus(Choices):
    CHOOSING = "choosing"
    PREPARING = "preparing"
    ACTIVE = "active"
    BROKEN = "broken"
    DISCONNECTED = "disconnected"


SHEET_STATUS_LABELS = {
    SheetStatus.CHOOSING: "Fayl tanlanmoqda",
    SheetStatus.PREPARING: "Tayyorlanmoqda",
    SheetStatus.ACTIVE: "Ishlayapti",
    SheetStatus.BROKEN: "To'xtagan",
    SheetStatus.DISCONNECTED: "Uzilgan",
}


class BrokenReason(Choices):
    REVOKED = "revoked"
    PERMISSION = "permission"
    SHEET_GONE = "sheet_gone"
    TRASHED = "trashed"
    TAB_GONE = "tab_gone"
    NOT_A_SHEET = "not_a_sheet"
    READ_ONLY = "read_only"


BROKEN_REASON_LABELS = {
    BrokenReason.REVOKED: "Google ruxsati olib tashlangan",
    BrokenReason.PERMISSION: "Jadvalga yozish ruxsati berilmagan",
    BrokenReason.SHEET_GONE: "Jadval o'chirilgan",
    BrokenReason.TRASHED: "Jadval savatchada",
    BrokenReason.TAB_GONE: "Jadvaldagi varaq o'chirilgan",
    BrokenReason.NOT_A_SHEET: "Tanlangan fayl jadval emas",
    BrokenReason.READ_ONLY: "Faylni faqat ko'rish mumkin",
}
NEEDS_NEW_SHEET: Final = frozenset(
    {BrokenReason.SHEET_GONE, BrokenReason.TRASHED, BrokenReason.TAB_GONE}
)
NEEDS_OTHER_FILE: Final = frozenset(
    {
        BrokenReason.PERMISSION,
        BrokenReason.SHEET_GONE,
        BrokenReason.TRASHED,
        BrokenReason.NOT_A_SHEET,
        BrokenReason.READ_ONLY,
    }
)


class SheetMode(Choices):
    SINGLE = "single"
    PER_FORM = "per_form"
    OWN_FILE = "own_file"


SHEET_MODE_LABELS = {
    SheetMode.SINGLE: "Hammasi bitta jadvalga",
    SheetMode.PER_FORM: "Har forma alohida faylga",
    SheetMode.OWN_FILE: "O'z faylimga",
}
SPREADSHEET_MIME: Final = "application/vnd.google-apps.spreadsheet"
FILE_ID_PATTERN: Final = "^[A-Za-z0-9_-]{10,200}$"
PICKER_TOKEN_MARGIN_SECONDS: Final = 600


class Channel(Choices):
    SHEETS = "sheets"


CHANNEL_LABELS = {Channel.SHEETS: "Google jadval"}


class DeliveryStatus(Choices):
    SENDING = "sending"
    DELIVERED = "delivered"


DELIVERY_STATUS_LABELS = {
    DeliveryStatus.SENDING: "Yuborilmoqda",
    DeliveryStatus.DELIVERED: "Yetkazildi",
}
FIRST_TAB: Final = "0"
DELIVERY_BATCH: Final = 200
DELIVERY_BATCHES_PER_RUN: Final = 10
RECENT_WINDOW_HOURS: Final = 24
DELIVERY_LOCK_SECONDS: Final = 600
RATE_LIMIT_BACKOFF_SECONDS: Final = 60
OUTAGE_BACKOFF_SECONDS: Final = 120
REFUSAL_BACKOFF_SECONDS: Final = 3600
MAX_QUESTION_COLUMNS: Final = 200
STATE_SESSION_KEY: Final = "google_oauth_state"
CHOICE_SESSION_KEY: Final = "google_sheet_choice"
PREPARE_GRACE_SECONDS: Final = 120
PREPARE_LOCK_SECONDS: Final = 300
AUDIT_PROVIDER: Final = "google"
AUDIT_LEVEL: Final = "spreadsheet"
AUDIT_AGGREGATE: Final = "sheet_link"
FILE_ACTIONS: Final = (
    ActionType.SHEET_CONNECT,
    ActionType.SHEET_PICK,
    ActionType.SHEET_RECREATE,
)
REVOKE_ACTIONS: Final = (ActionType.SHEET_DISCONNECT,)
SUPERSEDED: Final = "superseded"
