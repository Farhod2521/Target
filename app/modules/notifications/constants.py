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
# The daily report's buttons: a pair's day, and back to the list.
CALLBACK_DAILY_PAIR: Final = "dd"
CALLBACK_DAILY_LIST: Final = "dl"
CALLBACK_WEEKLY_PAIR: Final = "wd"
CALLBACK_WEEKLY_LIST: Final = "wl"
# Five pairs a message; a pair key on a button is cut to a digest this long.
DAILY_PAIR_DIGEST_CHARS: Final = 10
# A final day's reports, kept for the buttons under its message.
DAILY_REPORTS_KEY: Final = "notifications:day-book:{owner}:{day}:{language}"
DAILY_REPORTS_TTL_SECONDS: Final = 3 * 24 * 60 * 60
CALLBACK_WATCH_UP: Final = "wu"
CALLBACK_WATCH_DOWN: Final = "wd"
CALLBACK_WATCH_PAUSE: Final = "wp"
CALLBACK_WATCH_DELETE: Final = "wx"
CALLBACK_WATCH_DELETE_SURE: Final = "wy"
CALLBACK_WATCH_WAIT: Final = "ww"
CALLBACK_WATCH_RESUME: Final = "wr"
CALLBACK_FREQUENCY_FINE: Final = "fw"
# TZ 1.5: «Reklamani to'xtatish» and «Kuzataman» under a price rise.
CALLBACK_PRICE_PAUSE: Final = "np"
CALLBACK_PRICE_WATCH: Final = "nw"
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
# The cabinet's troubles are said once a day, at this hour on the owner's
# clock: after the daily report and the frequency message, never at night.
TROUBLE_HOUR: Final = 10
DAILY_REPORT_LATEST_HOUR: Final = 9
WEEKLY_REPORT_HOUR: Final = 8
WEEKLY_REPORT_LATEST_HOUR: Final = 10
FREQUENCY_HOUR: Final = 9
# One message holds the day's levels while it stays under Telegram's 4096.
FREQUENCY_MAX_CHARS: Final = 3800
NOTICE_TRIES: Final = 3
UNDELIVERED_DAYS: Final = 7
OUTCOME_NOTICE_HOURS: Final = 24
__all__ = [
    "ASKED_KEY",
    "ASKED_TTL_SECONDS",
    "CALLBACK_ANSWER",
    "CALLBACK_APPROVE",
    "CALLBACK_DAILY_LIST",
    "CALLBACK_DAILY_PAIR",
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
    "CALLBACK_WEEKLY_LIST",
    "CALLBACK_WEEKLY_PAIR",
    "COMMAND_START",
    "COMMAND_STOP",
    "DAILY_PAIR_DIGEST_CHARS",
    "DAILY_REPORTS_KEY",
    "DAILY_REPORTS_TTL_SECONDS",
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
    "TROUBLE_HOUR",
    "UNDELIVERED_DAYS",
    "WEEKLY_REPORT_HOUR",
    "WEEKLY_REPORT_LATEST_HOUR",
    "NoticeKind",
]
STAFF_LINK_TOKEN_KEY: Final = "notifications:staff-link:{token}"
DEV_ALERT_KEY: Final = "notifications:devalert:{owner}:{code}:{digest}"
DEV_ALERT_REPEAT_SECONDS: Final = 60 * 60
DEV_ALERT_MESSAGE_CHARS: Final = 1500
# The customer bot's "/" menu, and the wait after /yordam for words to Support.
COMMAND_REPORT: Final = "hisobot"
COMMAND_TODAY: Final = "bugun"
COMMAND_WEEK: Final = "hafta"
COMMAND_HELP: Final = "yordam"
SUPPORT_WAIT_KEY: Final = "notifications:support-wait:{chat_id}"
SUPPORT_WAIT_TTL_SECONDS: Final = 15 * 60
# The support bot: a cabinet's «Telegramda yozish» link, a Telegram message
# already stored (a delivery seen twice), an office answer to a guest
# already sent.
SUPPORT_BOT_LINK_KEY: Final = "notifications:support-bot-link:{token}"
SUPPORT_BOT_SEEN_KEY: Final = "notifications:support-bot-seen:{chat_id}:{message_id}"
SUPPORT_BOT_SEEN_TTL_SECONDS: Final = 24 * 60 * 60
SUPPORT_BOT_GUEST_SENT_KEY: Final = "notifications:support-bot-guest-sent:{message_id}"
# A client's first words after a quiet stretch are answered «qabul qilindi».
SUPPORT_BOT_ACK_AFTER_SECONDS: Final = 30 * 60
SUPPORT_BOT_COMMANDS: Final = (
    ("start", "Boshlash"),
    ("yordam", "Bot qanday ishlaydi"),
    ("stop", "Javoblarni botga yubormaslik"),
)
# "Parolni unutdingizmi?" opens the bot with this instead of a link code.
RESET_PAYLOAD: Final = "parol"
