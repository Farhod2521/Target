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
    TELEGRAM = "telegram"


CHANNEL_LABELS = {Channel.SHEETS: "Google jadval", Channel.TELEGRAM: "Telegram"}


class DeliveryStatus(Choices):
    SENDING = "sending"
    DELIVERED = "delivered"
    # Telegram refused this one message (too long, bad markup), not the chat.
    FAILED = "failed"


DELIVERY_STATUS_LABELS = {
    DeliveryStatus.SENDING: "Yuborilmoqda",
    DeliveryStatus.DELIVERED: "Yetkazildi",
    DeliveryStatus.FAILED: "Yuborilmadi",
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


class LeadChatKind(Choices):
    GROUP = "group"
    CHANNEL = "channel"


LEAD_CHAT_KIND_LABELS = {LeadChatKind.GROUP: "Guruh", LeadChatKind.CHANNEL: "Kanal"}


class LeadChatStatus(Choices):
    ACTIVE = "active"
    BROKEN = "broken"


LEAD_CHAT_STATUS_LABELS = {
    LeadChatStatus.ACTIVE: "Ishlayapti",
    LeadChatStatus.BROKEN: "To'xtagan",
}


class LeadChatBroken(Choices):
    REMOVED = "removed"
    RIGHTS = "rights"
    PUBLIC = "public"
    GONE = "gone"
    REFUSED = "refused"


LEAD_CHAT_BROKEN_LABELS = {
    LeadChatBroken.REMOVED: "Bot guruh yoki kanaldan chiqarilgan",
    LeadChatBroken.RIGHTS: "Botda xabar yozish huquqi yo'q",
    LeadChatBroken.PUBLIC: "Guruh yoki kanal ochiq bo'lib qolgan",
    LeadChatBroken.GONE: "Guruh yoki kanal o'chirilgan",
    LeadChatBroken.REFUSED: "Telegram xabarni qabul qilmadi",
}
# Telegram's words for where the bot was added.
GROUP_CHAT_TYPES: Final = frozenset({"group", "supergroup"})
CHANNEL_CHAT_TYPE: Final = "channel"
# The site's button -> /start lc_<token> in the bot -> a group or a channel.
LEAD_CHAT_PAYLOAD: Final = "lc_"
LEAD_CHAT_PRESS: Final = "lc:"
LEAD_CHAT_TOKEN_BYTES: Final = 16
LEAD_CHAT_TOKEN_TTL_SECONDS: Final = 30 * 60
LEAD_CHAT_TOKEN_KEY: Final = "destinations:leadchat:token:{token}"
# The token the person last opened, by their Telegram id: adding the bot to
# a channel carries no payload, only who did it.
LEAD_CHAT_WAITING_KEY: Final = "destinations:leadchat:waiting:{user}"
# What a send that Telegram put off waits before trying again.
LEAD_POST_RETRIES: Final = 6
LEAD_POST_BACKOFF_SECONDS: Final = 30
# The sweep posts what a lost task left behind, never older than this.
LEAD_POST_SWEEP_HOURS: Final = 24
LEAD_POST_SWEEP_LIMIT: Final = 200
LEAD_POST_ANSWER_CHARS: Final = 300
LEAD_POST_QUESTION_CHARS: Final = 100
# Telegram takes 4096 characters; the answers that do not fit are left out.
LEAD_POST_TEXT_CHARS: Final = 4000
# A claim this old was never finished (the worker died mid-send): it is taken again.
LEAD_POST_STALE_SECONDS: Final = 10 * 60
# Telegram's words for a refusal of the message itself, not of the chat.
LEAD_POST_MESSAGE_REFUSALS: Final = (
    "message is too long",
    "can't parse entities",
    "text must be non-empty",
    "button_url_invalid",
    "wrong http url",
)
# Every linked chat is looked at hourly (public now? bot still there?),
# a few per sweep so the sweep never holds a worker for long.
LEAD_CHAT_CHECK_SECONDS: Final = 60 * 60
LEAD_CHAT_CHECKS_PER_RUN: Final = 20
