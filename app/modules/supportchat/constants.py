from datetime import timedelta
from pathlib import PurePosixPath
from typing import Final, Literal

from app.common.choices import Choices


class RelayBot(Choices):
    CUSTOMER = "customer"
    STAFF = "staff"


RELAY_BOT_LABELS = {RelayBot.CUSTOMER: "Asosiy bot", RelayBot.STAFF: "Xodimlar boti"}


class MessageKind(Choices):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    FILE = "file"
    VOICE = "voice"
    STICKER = "sticker"


MESSAGE_KIND_LABELS = {
    MessageKind.TEXT: "Matn",
    MessageKind.IMAGE: "Rasm",
    MessageKind.VIDEO: "Video",
    MessageKind.FILE: "Fayl",
    MessageKind.VOICE: "Ovozli xabar",
    MessageKind.STICKER: "Stiker",
}
MAX_UPLOAD_MB: Final = 100
MAX_UPLOAD_BYTES: Final = 100 * 1024 * 1024
MAX_BODY_CHARS: Final = 2000
ALLOWED_IMAGE_SUFFIXES: Final = frozenset({"jpg", "jpeg", "png", "webp", "gif"})
ALLOWED_VIDEO_SUFFIXES: Final = frozenset({"mp4", "mov"})
ALLOWED_DOC_SUFFIXES: Final = frozenset(
    {"pdf", "doc", "docx", "xls", "xlsx", "zip", "txt"}
)
ALLOWED_UPLOAD_SUFFIXES: Final = (
    ALLOWED_IMAGE_SUFFIXES | ALLOWED_VIDEO_SUFFIXES | ALLOWED_DOC_SUFFIXES
)
MAX_FILES_PER_MESSAGE: Final = 10
MAX_SEND_MB: Final = 200
MAX_SEND_BYTES: Final = MAX_SEND_MB * 1024 * 1024
ALLOWED_VOICE_SUFFIXES: Final = frozenset({"webm", "ogg", "m4a", "mp3"})
MAX_VOICE_SECONDS: Final = 300
EDIT_WINDOW: Final = timedelta(hours=24)
STICKERS: Final = (
    ("thumbs-up", "👍", "Zo'r"),
    ("heart", "❤️", "Yurak"),
    ("smile", "😊", "Tabassum"),
    ("laugh", "😂", "Kulgi"),
    ("thanks", "🙏", "Rahmat"),
    ("ok", "👌", "Yaxshi"),
    ("fire", "🔥", "Olov"),
    ("party", "🎉", "Bayram"),
    ("think", "🤔", "O'ylayapman"),
    ("sad", "😔", "Afsus"),
    ("wow", "😮", "Voy"),
    ("clap", "👏", "Qarsak"),
)
STICKER_CODES: Final = frozenset((code for code, _emoji, _name in STICKERS))


def sticker_emoji(code: str) -> str:
    for known, emoji, _name in STICKERS:
        if known == code:
            return emoji
    return ""


def kind_for_filename(filename: str) -> MessageKind | None:
    suffix = PurePosixPath(filename).suffix.lstrip(".").lower()
    if suffix in ALLOWED_IMAGE_SUFFIXES:
        return MessageKind.IMAGE
    if suffix in ALLOWED_VIDEO_SUFFIXES:
        return MessageKind.VIDEO
    if suffix in ALLOWED_DOC_SUFFIXES:
        return MessageKind.FILE
    return None


ACTION_TARGET_PROVIDER: Final = "supportchat"
ACTION_TARGET_LEVEL: Final = "conversation"
CONVERSATION_PAGE_SIZE: Final = 20
MESSAGE_PAGE_SIZE: Final = 50
MESSAGES_PER_MINUTE: Final = 20
MESSAGE_BUCKET: Final = "supportchat:message"
QueueState = Literal["waiting", "all"]
WAITING: Final[QueueState] = "waiting"
EVERYONE: Final[QueueState] = "all"
Viewer = Literal["client", "office"]
CLIENT: Final[Viewer] = "client"
OFFICE: Final[Viewer] = "office"
WIDGET_SURFACE: Final = "widget"
TYPING_BEAT_MS: Final = 2500
TYPING_SHOWN_MS: Final = 5000
WATCH_PARAM: Final = "watch"
WS_GROUP_PREFIX: Final = "supportchat"
