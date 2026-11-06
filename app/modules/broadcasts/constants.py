from app.common.choices import Choices


class BroadcastStatus(Choices):
    DRAFT = "draft"
    SENDING = "sending"
    SENT = "sent"
    STOPPED = "stopped"


BROADCAST_STATUS_LABELS = {
    BroadcastStatus.DRAFT: "Qoralama",
    BroadcastStatus.SENDING: "Yuborilmoqda",
    BroadcastStatus.SENT: "Yuborildi",
    BroadcastStatus.STOPPED: "To'xtatildi",
}


class Audience(Choices):
    ALL = "all"
    SELECTED = "selected"


AUDIENCE_LABELS = {
    Audience.ALL: "Hammaga",
    Audience.SELECTED: "Tanlanganlarga",
}


class DeliveryStatus(Choices):
    PENDING = "pending"
    # Taken by a worker and not yet answered. One left here after a crash is
    # never sent again: a missed message is better than a doubled one.
    CLAIMED = "claimed"
    SENT = "sent"
    BLOCKED = "blocked"
    FAILED = "failed"


DELIVERY_STATUS_LABELS = {
    DeliveryStatus.PENDING: "Navbatda",
    DeliveryStatus.CLAIMED: "Noma'lum",
    DeliveryStatus.SENT: "Yetdi",
    DeliveryStatus.BLOCKED: "Botni bloklagan",
    DeliveryStatus.FAILED: "Xato",
}

TITLE_MAX = 120
BODY_MAX = 3800
PAGE_SIZE = 50
MAX_TARGETS = 1000

IMAGE_TYPES = ("jpg", "jpeg", "png", "webp")
MAX_IMAGE_MB = 5
IMAGE_DIR = "broadcasts/%Y/%m/"
IMAGE_TOKEN_HOURS = 6

# Telegram lets a bot post about 30 messages a second to different chats;
# 25 leaves room for the bot's own notices going out at the same time.
SENDS_PER_SECOND = 25
# One task sends this many and queues the next, so a stop is heard within
# seconds and a restarted worker picks up where the last one left off.
BATCH_SIZE = 200
# A 429 asking for longer than this ends the batch; the next one waits.
MAX_INLINE_WAIT_SECONDS = 30
