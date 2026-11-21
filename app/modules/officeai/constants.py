from typing import Final


class Author:
    """Who wrote a row: the admin, or the assistant."""

    USER = "user"
    AI = "ai"


class MessageStatus:
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


PROMPT_NAME: Final = "office_ai"
RELATED_TYPE: Final = "office_ai_message"
TITLE_CHARS: Final = 60

MAX_QUESTION_CHARS: Final = 2000
ANSWER_MAX_TOKENS: Final = 2500
# What the model is shown of the thread before the question.
HISTORY_TURNS: Final = 8
HISTORY_CHARS: Final = 8000
SIDEBAR_THREADS: Final = 30
PAGE_MESSAGES: Final = 50

# Each look-up is a database read; an answer needs a handful at most.
MAX_LOOKUPS: Final = 10
MAX_ROUNDS: Final = 6
# Rows a customer list shows the model; the total is always given.
LIST_ROWS: Final = 15
PROBLEM_ROWS: Final = 10
# A numbered list's row numbers pass the figure gate below this.
ORDINALS_BELOW: Final = 100

# A person's questions a day: a guard on the bill, not a rationing.
QUESTIONS_PER_DAY: Final = 100

TURN_KEY: Final = "officeai:turn:{turn_id}"
OUT_KEY: Final = "officeai:out:{turn_id}"
STOP_KEY: Final = "officeai:stop:{turn_id}"
TURN_TTL_SECONDS: Final = 600
STREAM_CHUNK_CHARS: Final = 40
STREAM_TIMEOUT_SECONDS: Final = 120
POLL_SECONDS: Final = 0.15
ANSWER_STUCK_AFTER_MINUTES: Final = 20

LOOKING_DEFAULT: Final = "Ma'lumotlarni o'qiyapman…"

# The same assistant in @owners_tai_bot. A chat keeps answering in one
# thread until it has been quiet this long, or /yangi starts another.
TELEGRAM_THREAD_KEY: Final = "officeai:telegram:thread:{chat_id}"
TELEGRAM_THREAD_TTL_SECONDS: Final = 6 * 60 * 60
# Telegram takes 4096 characters a message; room is left for the tags.
TELEGRAM_CHUNK_CHARS: Final = 3800
TELEGRAM_THINKING: Final = "⏳ Ma'lumotlarni o'qiyapman…"
TELEGRAM_CHANNEL: Final = (
    "- Channel: Telegram. No tables: short lines and lists, **bold** for "
    "the key figure."
)

# What the empty screen offers to ask, for a first question.
SUGGESTIONS: Final[tuple[str, ...]] = (
    "Bugun nechta odam ro'yxatdan o'tdi?",
    "Shu oy qancha to'lov tushdi, qaysi tarif ko'p sotildi?",
    "O'tgan 7 kunda ro'yxatdan o'tganlarning nechtasi to'lov qildi?",
    "Kimlarning obunasi yaqin kunlarda tugayapti?",
    "Hozir nimalar odamni kutib turibdi?",
    "Qaysi menejer shu oy ko'proq sotdi?",
)
