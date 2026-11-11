"""The one chat's own words and limits. Nothing here is shared with the old
chat (``app/modules/chat``) except what is imported from it by name."""

from datetime import timedelta
from typing import Final

from app.common.choices import Choices


class Author(Choices):
    """Who wrote a row of a thread."""

    USER = "user"
    AI = "ai"
    # A person in Support, answering in the same thread.
    STAFF = "staff"


AUTHOR_LABELS = {Author.USER: "Mijoz", Author.AI: "AI", Author.STAFF: "Support"}


class MessageStatus(Choices):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


MESSAGE_STATUS_LABELS = {
    MessageStatus.PENDING: "Kutilmoqda",
    MessageStatus.DONE: "Tayyor",
    MessageStatus.FAILED: "Xato",
}


class ButtonKind:
    """What a button under an answer does when pressed."""

    # A request to Support the assistant prepared (``create_ticket``).
    TICKET = "ticket"
    # A change to a running advert the owner asked for (``propose_change``).
    CHANGE = "change"
    # A proposal the agent had already made (``Actions you may offer``).
    OFFER = "offer"
    # A visitor: leave a name and a phone for Support.
    GUEST_TICKET = "guest_ticket"


class ButtonState:
    OPEN = "open"
    # Pressed and on its way: a change being carried out, a ticket not
    # picked up yet.
    SENT = "sent"
    WORKING = "working"
    DONE = "done"
    REFUSED = "refused"
    DISMISSED = "dismissed"
    GONE = "gone"


class Mode:
    """Who the composer talks to by default in a thread."""

    AI = "ai"
    SUPPORT = "support"


PROMPT_NAME: Final = "assistant"
RELATED_TYPE: Final = "assistant_message"
TITLE_CHARS: Final = 60
SUPPORT_TITLE: Final = "Yordam"
TEAM: Final = "Yordam xizmati"

MAX_QUESTION_CHARS: Final = 1000
ANSWER_MAX_TOKENS: Final = 1600
HISTORY_TURNS: Final = 10
HISTORY_CHARS: Final = 4000
SIDEBAR_SESSIONS: Final = 20
SESSION_TTL_DAYS: Final = 30
ANSWER_STUCK_AFTER_MINUTES: Final = 20

TURN_KEY: Final = "assistant:turn:{turn_id}"
OUT_KEY: Final = "assistant:out:{turn_id}"
GUEST_TICKET_KEY: Final = "assistant:guest-ticket:{turn_id}"
TURN_TTL_SECONDS: Final = 600
GUEST_TICKET_TTL_SECONDS: Final = 24 * 3600
STREAM_CHUNK_CHARS: Final = 40
STREAM_TIMEOUT_SECONDS: Final = 90
POLL_SECONDS: Final = 0.12

# Tickets are a person's time: fewer than questions, counted on their own.
TICKET_BUCKET: Final = "assistant-ticket"
TICKETS_PER_DAY: Final = 5
TICKET_SUMMARY_CHARS: Final = 600
TICKET_CHECKED_ITEMS: Final = 8
TICKET_ANSWER_CHARS: Final = 600

# How much of an earlier support chat is brought into a new thread.
IMPORT_ROWS: Final = 100
# After a person's reply the thread stays with them this long.
REPLY_WINDOW: Final = timedelta(hours=24)

HELP_RESULTS: Final = 4
HELP_STEPS_CHARS: Final = 1200
HELP_LANGUAGES: Final = ("uz", "ru", "en")

LOOKING: Final[dict[str, str]] = {
    "account_health": "Hisobingiz holatini tekshiryapman…",
    "help_search": "Yechimlar bazasidan qidiryapman…",
    "create_ticket": "Mutaxassis uchun zayavka tayyorlayapman…",
}
