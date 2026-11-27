"""The one chat's own words and limits. Nothing here is shared with the old
chat (``app/modules/chat``) except what is imported from it by name."""

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
    # What the person said about their business, to be kept (``note_business``).
    KNOWLEDGE = "knowledge"
    # The business's kind and name, to be confirmed (``set_business_kind``).
    BUSINESS_KIND = "business_kind"
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


class GapStatus:
    """Where a question the assistant could not answer has got to."""

    OPEN = "open"
    # A ready answer was written for it (``AssistantGap.article_id``).
    ANSWERED = "answered"
    # The office decided it needs nothing.
    DISMISSED = "dismissed"


GAP_KIND_LABELS: Final[dict[str, str]] = {
    "answer": "Tayyor javob yo'q",
    "tool": "Imkoniyat qo'shish kerak",
}
# The same question asked again is found among this many of the newest.
GAP_COMPARE_ROWS: Final = 300
# Share of a title's words two questions must have in common to be one.
GAP_SAME_SHARE: Final = 0.6
GAP_SAMPLES: Final = 5
GAP_QUERIES: Final = 8
GAP_QUESTION_CHARS: Final = 1000


class Translation:
    """The office's text on its way into the other languages."""

    NONE = ""
    TRANSLATING = "translating"
    FAILED = "failed"


TRANSLATION_PROMPT: Final = "office_translation"
# A translation nobody finished is shown as failed after this long.
TRANSLATION_STUCK_MINUTES: Final = 10


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
# A thread is drawn newest first, this many rows at a time.
PAGE_MESSAGES: Final = 50
SESSION_TTL_DAYS: Final = 30
ANSWER_STUCK_AFTER_MINUTES: Final = 20

TURN_KEY: Final = "assistant:turn:{turn_id}"
OUT_KEY: Final = "assistant:out:{turn_id}"
GUEST_TICKET_KEY: Final = "assistant:guest-ticket:{turn_id}"
# The client pressed stop: the answer ends where it is.
STOP_KEY: Final = "assistant:stop:{turn_id}"
TURN_TTL_SECONDS: Final = 600
GUEST_TICKET_TTL_SECONDS: Final = 24 * 3600
STREAM_CHUNK_CHARS: Final = 40
STREAM_TIMEOUT_SECONDS: Final = 90
POLL_SECONDS: Final = 0.12

# Tickets are a person's time: fewer than questions, counted on their own.
TICKET_BUCKET: Final = "assistant-ticket"
TICKETS_PER_DAY: Final = 5
TICKET_SUMMARY_CHARS: Final = 600
# Only the facts that bear on the request, not every check that was made.
TICKET_CHECKED_ITEMS: Final = 5

# How much of an earlier support chat is brought into a new thread.
IMPORT_ROWS: Final = 100

HELP_RESULTS: Final = 4
HELP_STEPS_CHARS: Final = 1200
HELP_LANGUAGES: Final = ("uz", "ru", "en")

LOOKING: Final[dict[str, str]] = {
    "account_health": "Hisobingiz holatini tekshiryapman…",
    "help_search": "Yechimlar bazasidan qidiryapman…",
    "create_ticket": "Mutaxassis uchun zayavka tayyorlayapman…",
    "note_business": "Biznesingiz haqida eslab qolyapman…",
    "set_business_kind": "Biznes turini tayyorlayapman…",
    "plans_and_prices": "Tariflarni ko'ryapman…",
    "crm_outcomes": "CRM natijalarini ko'ryapman…",
    "guard_alerts": "Qo'riqchi ogohlantirishlarini ko'ryapman…",
    "referrals_and_wallet": "Referal va hamyonni ko'ryapman…",
}
RELATED_REFUSAL: Final = "refusal_answer"
RELATED_ARTICLE: Final = "help_article"


class FeedbackStatus:
    """Where a client's word on the assistant's answers has got to."""

    OPEN = "open"
    # The office has read it.
    DONE = "done"


class FeedbackKind:
    """What brought a client's word on the answers."""

    # Asked before a request to Support was shown.
    TICKET = "ticket"
    # 👍 or 👎 under an answer.
    RATING = "rating"


RATING_UP: Final = "up"
RATING_DOWN: Final = "down"
# Why a 👎, as the client picks it under the answer.
RATING_REASONS: Final[dict[str, str]] = {
    "wrong": "Noto'g'ri",
    "unclear": "Tushunarsiz",
    "incomplete": "To'liq emas",
    "other": "Boshqa",
}
FEEDBACK_CHARS: Final = 2000
FEEDBACK_ANSWER_CHARS: Final = 4000
# Before a prepared request is shown, the client is asked what was wrong
# with the answers (owner's decision, 2026-11-19); their reply goes to the
# office and the send button follows it. Keyed by the person's language.
FEEDBACK_ASK: Final[dict[str, str]] = {
    "uz": (
        "Zayavkani yuborishdan oldin bitta savol: **mening javoblarimda "
        "qanday kamchilik bor?** Fikringizni yozing — bu tizimni yangilash "
        "uchun muhim."
    ),
    "ru": (
        "Перед отправкой заявки один вопрос: **что было не так в моих "
        "ответах?** Напишите своё мнение — это важно для обновления системы."
    ),
    "en": (
        "One question before the request is sent: **what was wrong with my "
        "answers?** Please tell us what you think — it matters for improving "
        "the system."
    ),
}
FEEDBACK_SKIP: Final[dict[str, str]] = {
    "uz": "Fikrim yo'q",
    "ru": "Нет замечаний",
    "en": "Nothing to add",
}
FEEDBACK_THANKS: Final[dict[str, str]] = {
    "uz": (
        "Rahmat, fikringiz jamoaga yetkazildi. Endi zayavkani yuborishni "
        "tasdiqlang — mutaxassis shu masala bo'yicha siz bilan bog'lanadi."
    ),
    "ru": (
        "Спасибо, ваш отзыв передан команде. Теперь подтвердите отправку "
        "заявки — специалист свяжется с вами по этому вопросу."
    ),
    "en": (
        "Thank you, your feedback has reached the team. Now confirm sending "
        "the request — a specialist will contact you about it."
    ),
}
FEEDBACK_SKIPPED: Final[dict[str, str]] = {
    "uz": (
        "Tushunarli. Zayavkani yuborishni tasdiqlang — mutaxassis shu masala "
        "bo'yicha siz bilan bog'lanadi."
    ),
    "ru": (
        "Понятно. Подтвердите отправку заявки — специалист свяжется с вами "
        "по этому вопросу."
    ),
    "en": (
        "Understood. Confirm sending the request — a specialist will contact "
        "you about it."
    ),
}
FEEDBACK_LANGUAGE: Final = "uz"


def in_language(words: dict[str, str], language: str) -> str:
    """The person's language (a ``Written.key``), Uzbek when there is none
    for it; Uzbek in Cyrillic is the Uzbek transliterated."""
    if language == "uz-cyrl":
        from core.written import to_cyrillic

        return to_cyrillic(words[FEEDBACK_LANGUAGE])
    return words.get(language) or words[FEEDBACK_LANGUAGE]
