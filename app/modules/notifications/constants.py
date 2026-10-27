from typing import Final

from app.common.choices import Choices


class NoticeKind(Choices):
    SUGGESTION = "suggestion"
    REPORT = "report"
    REJECTION = "rejection"
    SUBSCRIPTION = "subscription"
    CONNECTION = "connection"
    TROUBLE = "trouble"
    ACTION_REQUIRED = "action_required"
    SPEND_GUARD = "spend_guard"
    DAILY_REPORT = "daily_report"
    LAUNCH_WATCH = "launch_watch"
    SUPPORT_REPLY = "support_reply"
    WITHDRAWAL = "withdrawal"
    REFERRAL = "referral"
    FEEDBACK = "feedback"
    SURVEY = "survey"
    FREQUENCY = "frequency"
    STOP = "stop"


NOTICE_KIND_LABELS = {
    NoticeKind.SUGGESTION: "Agent taklifi",
    NoticeKind.REPORT: "Haftalik hisobot",
    NoticeKind.REJECTION: "Rad etilgan reklama",
    NoticeKind.SUBSCRIPTION: "Obuna muddati",
    NoticeKind.CONNECTION: "Uzilgan ulanish",
    NoticeKind.TROUBLE: "Kabinetdagi muammo",
    NoticeKind.ACTION_REQUIRED: "Meta profil tasdig'i",
    NoticeKind.SPEND_GUARD: "Bugungi natijasiz sarf",
    NoticeKind.DAILY_REPORT: "Kunlik hisobot",
    NoticeKind.LAUNCH_WATCH: "Yangi reklama kuzatuvi",
    NoticeKind.SUPPORT_REPLY: "Yordam javobi",
    NoticeKind.WITHDRAWAL: "Daromad to'lovi",
    NoticeKind.REFERRAL: "Yangi do'st",
    NoticeKind.FEEDBACK: "Fikrga javob",
    NoticeKind.SURVEY: "So'rovnoma",
    NoticeKind.FREQUENCY: "Chastota ogohlantirishi",
    NoticeKind.STOP: "Reklama to'xtadi",
}
NOTICES_WITHOUT_SUBSCRIPTION: Final = frozenset(
    {
        NoticeKind.SUBSCRIPTION,
        NoticeKind.SUPPORT_REPLY,
        NoticeKind.WITHDRAWAL,
        NoticeKind.REFERRAL,
        NoticeKind.FEEDBACK,
        NoticeKind.SURVEY,
    }
)
ERROR_BLOCKED: Final = "blocked"
ERROR_UNREACHABLE: Final = "unreachable"
ERROR_LABELS: Final[dict[str, object]] = {
    ERROR_BLOCKED: "Siz botni bloklagansiz",
    ERROR_UNREACHABLE: "Telegram bu suhbatni topmadi",
}
PRIVATE_CHAT: Final = "private"
ASKED_KEY: Final = "telegram:asked:{chat_id}:{message_id}"
ASKED_TTL_SECONDS: Final = 15 * 60
REPLIED_KEY: Final = "telegram:replied:{message_id}"
COMMAND_START: Final = "start"
COMMAND_STOP: Final = "stop"
LINK_TOKEN_TTL_SECONDS: Final = 15 * 60
LINK_TOKEN_BYTES: Final = 12
LINK_TOKEN_KEY: Final = "notifications:link:{token}"
CALLBACK_APPROVE: Final = "a"
CALLBACK_REJECT: Final = "r"
CALLBACK_PAUSE: Final = "p"
CALLBACK_PAUSE_ANYWAY: Final = "pf"
CALLBACK_WAIT: Final = "pw"
CALLBACK_ANSWER: Final = "c"
CALLBACK_REPLY: Final = "q"
CALLBACK_SEPARATOR: Final = ":"
CALLBACK_WATCH_UP: Final = "wu"
CALLBACK_WATCH_DOWN: Final = "wd"
CALLBACK_WATCH_PAUSE: Final = "wp"
CALLBACK_WATCH_DELETE: Final = "wx"
CALLBACK_WATCH_DELETE_SURE: Final = "wy"
CALLBACK_WATCH_WAIT: Final = "ww"
CALLBACK_WATCH_RESUME: Final = "wr"
CALLBACK_FREQUENCY_FINE: Final = "fw"
CALLBACK_SUPPORT_SEND: Final = "sy"
CALLBACK_SUPPORT_DROP: Final = "sn"
SUPPORT_CONFIRM_KEY: Final = "notifications:support-confirm:{token}"
SUPPORT_CONFIRM_TTL_SECONDS: Final = 30 * 60
CALLBACK_SURVEY: Final = "sv"
SURVEY_STATE_KEY: Final = "notifications:survey:{chat_id}"
SURVEY_STATE_TTL_SECONDS: Final = 3 * 24 * 60 * 60
SURVEY_FIRST_HOUR: Final = 10
SURVEY_LAST_HOUR: Final = 21
SUPPORT_CONFIRM_TOKEN_BYTES: Final = 9
REJECTION_DIGEST_CHARS: Final = 8
MAX_REJECTIONS_PER_SWEEP: Final = 3
MAX_TROUBLES_PER_SWEEP: Final = 3
DAILY_REPORT_HOUR: Final = 7
DAILY_REPORT_LATEST_HOUR: Final = 9
WEEKLY_REPORT_HOUR: Final = 8
WEEKLY_REPORT_LATEST_HOUR: Final = 10
FREQUENCY_HOUR: Final = 9
FREQUENCY_MAX_ITEMS: Final = 5
NOTICE_TRIES: Final = 3
UNDELIVERED_DAYS: Final = 7
OUTCOME_NOTICE_HOURS: Final = 24
__all__ = [
    "ASKED_KEY",
    "ASKED_TTL_SECONDS",
    "CALLBACK_ANSWER",
    "CALLBACK_APPROVE",
    "CALLBACK_PAUSE",
    "CALLBACK_PAUSE_ANYWAY",
    "CALLBACK_REJECT",
    "CALLBACK_REPLY",
    "CALLBACK_SEPARATOR",
    "CALLBACK_SUPPORT_DROP",
    "CALLBACK_SUPPORT_SEND",
    "CALLBACK_SURVEY",
    "CALLBACK_WAIT",
    "CALLBACK_WATCH_DELETE",
    "CALLBACK_WATCH_DELETE_SURE",
    "CALLBACK_WATCH_DOWN",
    "CALLBACK_WATCH_PAUSE",
    "CALLBACK_WATCH_RESUME",
    "CALLBACK_WATCH_UP",
    "CALLBACK_WATCH_WAIT",
    "COMMAND_START",
    "COMMAND_STOP",
    "DAILY_REPORT_HOUR",
    "DAILY_REPORT_LATEST_HOUR",
    "ERROR_BLOCKED",
    "ERROR_LABELS",
    "ERROR_UNREACHABLE",
    "LINK_TOKEN_BYTES",
    "LINK_TOKEN_KEY",
    "LINK_TOKEN_TTL_SECONDS",
    "MAX_REJECTIONS_PER_SWEEP",
    "MAX_TROUBLES_PER_SWEEP",
    "NOTICE_TRIES",
    "OUTCOME_NOTICE_HOURS",
    "PRIVATE_CHAT",
    "REJECTION_DIGEST_CHARS",
    "REPLIED_KEY",
    "SUPPORT_CONFIRM_KEY",
    "SUPPORT_CONFIRM_TOKEN_BYTES",
    "SUPPORT_CONFIRM_TTL_SECONDS",
    "SURVEY_FIRST_HOUR",
    "SURVEY_LAST_HOUR",
    "SURVEY_STATE_KEY",
    "SURVEY_STATE_TTL_SECONDS",
    "UNDELIVERED_DAYS",
    "WEEKLY_REPORT_HOUR",
    "WEEKLY_REPORT_LATEST_HOUR",
    "NoticeKind",
]
STAFF_LINK_TOKEN_KEY: Final = "notifications:staff-link:{token}"
DEV_ALERT_KEY: Final = "notifications:devalert:{owner}:{code}:{digest}"
DEV_ALERT_REPEAT_SECONDS: Final = 60 * 60
DEV_ALERT_MESSAGE_CHARS: Final = 1500
