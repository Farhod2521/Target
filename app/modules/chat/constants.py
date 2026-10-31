from typing import Any, Final

from app.common.choices import Choices


class ChatRole(Choices):
    USER = "user"
    ASSISTANT = "assistant"


CHAT_ROLE_LABELS = {ChatRole.USER: "Savol", ChatRole.ASSISTANT: "Javob"}


class ChatMessageStatus(Choices):
    PENDING = "pending"
    DONE = "done"
    REFUSED = "refused"
    FAILED = "failed"


CHAT_MESSAGE_STATUS_LABELS = {
    ChatMessageStatus.PENDING: "Kutilmoqda",
    ChatMessageStatus.DONE: "Tayyor",
    ChatMessageStatus.REFUSED: "Rad etildi",
    ChatMessageStatus.FAILED: "Xato",
}
SCRIPT_ASK: Final = "script"
HISTORY_TURNS: Final = 10
HISTORY_CHARS: Final = 4000
SESSION_TTL_DAYS: Final = 30
SIDEBAR_SESSIONS: Final = 20
FREE_QUESTIONS: Final = 10
FREE_WINDOW_HOURS: Final = 24
VISITOR_HEADCOUNT_BELOW: Final = 10**12
MAX_QUESTION_CHARS: Final = 1000
ANSWER_MAX_TOKENS: Final = 1600
STREAM_CHUNK_CHARS: Final = 120
TURN_TTL_SECONDS: Final = 600
ANSWER_STUCK_AFTER_MINUTES: Final = 20
POLL_SECONDS: Final = 0.15
STREAM_TIMEOUT_SECONDS: Final = 90
CAMPAIGNS_IN_CONTEXT: Final = 10
ADSETS_IN_CONTEXT: Final = 6
ADS_IN_CONTEXT: Final = 5
AD_WORDS_CHARS: Final = 280
FORMS_IN_CONTEXT: Final = 3
PAGES_IN_CONTEXT: Final = 3
AUDIENCES_IN_CONTEXT: Final = 10
SUGGESTIONS_IN_CONTEXT: Final = 5
OFFERS_IN_CONTEXT: Final = 3
CHOICE_POLL_SECONDS: Final = 3
CONTEXT_WINDOW_DAYS: Final = 30
PROMPT_NAME: Final = "chat_answer"
REPORT_PROMPT_NAME: Final = "weekly_report"
REPORT_TTL_SECONDS: Final = 7 * 24 * 3600
CHANGES_IN_REPORT: Final = 4
BARREN_MIN_SPEND_PCT: Final = 15
REPORT_POLL_TRIES: Final = 6
DAILY_PROMPT_NAME: Final = "daily_report"
DAILY_RELATED_TYPE: Final = "daily_report"
DAILY_USUAL_DAYS: Final = 7
DAILY_REREAD_AFTER_HOURS: Final = 1
REPORT_RELATED_TYPE: Final = "weekly_report"
RELATED_TYPE: Final = "chat_message"
LOOKING: Final[dict[str, Any]] = {
    "account_overview": "Hisobingizni ko'ryapman…",
    "find": "Qidiryapman…",
    "list_campaigns": "Kampaniyalarni ko'ryapman…",
    "campaign_details": "Kampaniyalarni ko'ryapman…",
    "ad_details": "Reklamalarni ko'ryapman…",
    "audience_details": "Auditoriyani ko'ryapman…",
    "audiences": "Auditoriyani ko'ryapman…",
    "daily_figures": "Raqamlarni ko'ryapman…",
    "lead_counts": "Raqamlarni ko'ryapman…",
    "lead_forms": "Formalarni ko'ryapman…",
    "recent_changes": "O'zgarishlarni ko'ryapman…",
    "agent_proposals": "Takliflarni ko'ryapman…",
    "open_problems": "Takliflarni ko'ryapman…",
    "preparations": "Tayyorlangan kampaniyalarni ko'ryapman…",
}
LOOKING_DEFAULT: Final = "Ma'lumotlarni ko'ryapman…"
REFUSAL_PROMPT_NAME: Final = "refusal_answer"
REFUSAL_MAX_TOKENS: Final = 900
REFUSAL_ANSWER_FIELDS: Final = {"uz": "answer_uz", "ru": "answer_ru", "en": "answer_en"}
# The prompts' ``{{ language }}`` when one question writes all three.
REFUSAL_EVERY_LANGUAGE: Final = (
    "each of Uzbek (Latin script), Russian and English, one whole answer to each field"
)
REFUSAL_STALE_VERSIONS: Final = frozenset({"v1"})
OUR_FAULT_KEYS: Final = frozenset({"meta:100/1885624", "meta:100/1815614"})
CHANGE_REFUSAL_PROMPT_NAME: Final = "change_refusal"
# Kept apart from the launch prompt's versions, which REFUSAL_STALE_VERSIONS retires.
CHANGE_REFUSAL_VERSION_PREFIX: Final = "change-"
# One question to Claude per refusal, however many screens ask; it answers every language.
REFUSAL_LOCK: Final = "refusal-answer:{key}"
REFUSAL_LOCK_SECONDS: Final = 10 * 60
# An answer that could not be kept (it named this owner's figures, or Claude
# failed): the screen stops waiting, and nobody asks again for a day.
REFUSAL_GAVE_UP: Final = "none"
REFUSAL_GAVE_UP_SECONDS: Final = 24 * 60 * 60
