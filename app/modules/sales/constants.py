from typing import Final

from app.common.choices import Choices


class Group(Choices):
    ARIZA = "ariza"
    PROBLEM = "problem"
    NEW = "new"
    BACK = "back"
    ENDING = "ending"


GROUP_LABELS = {
    Group.ARIZA: "Ariza",
    Group.PROBLEM: "Muammoli",
    Group.NEW: "Yangi",
    Group.BACK: "Qaytgan",
    Group.ENDING: "Tugayapti",
}
GROUP_ORDER: Final = (Group.ENDING, Group.PROBLEM, Group.ARIZA, Group.BACK, Group.NEW)


class Stage(Choices):
    TAKEN = "taken"
    NO_ANSWER = "no_answer"
    CALLBACK = "callback"
    THINKING = "thinking"
    USING = "using"
    AWAITING = "awaiting"


STAGE_LABELS = {
    Stage.TAKEN: "Olindi",
    Stage.NO_ANSWER: "Javob bermadi",
    Stage.CALLBACK: "Qayta aloqa",
    Stage.THINKING: "O'ylab ko'radi",
    Stage.USING: "Foydalanmoqda",
    Stage.AWAITING: "To'lov kutilmoqda",
}


class Outcome(Choices):
    SOLD = "sold"
    SELF_PAID = "self_paid"
    LOST = "lost"
    UNREACHABLE = "unreachable"
    EXPIRED = "expired"
    RETURNED = "returned"


OUTCOME_LABELS = {
    Outcome.SOLD: "Sotildi",
    Outcome.SELF_PAID: "O'zi to'ladi",
    Outcome.LOST: "Rad etdi",
    Outcome.UNREACHABLE: "Aloqaga chiqmadi",
    Outcome.EXPIRED: "Muddati o'tdi",
    Outcome.RETURNED: "Qaytarildi",
}


class Source(Choices):
    MANAGER = "manager"
    SELF = "self"
    REFERRAL = "referral"


SOURCE_LABELS = {
    Source.MANAGER: "Menejer",
    Source.SELF: "O'zi",
    Source.REFERRAL: "Referal",
}


class HoldTerm(Choices):
    DAYS_30 = "30"
    DAYS_90 = "90"
    NEVER = "never"


HOLD_TERM_LABELS = {
    HoldTerm.DAYS_30: "30 kundan keyin",
    HoldTerm.DAYS_90: "90 kundan keyin",
    HoldTerm.NEVER: "Umuman xohlamaydi",
}


class ActivityKind(Choices):
    CLAIMED = "claimed"
    TAKEN_BACK = "taken_back"
    NO_ANSWER = "no_answer"
    CALLBACK = "callback"
    THINKING = "thinking"
    USING = "using"
    AWAITING = "awaiting"
    NOTE = "note"
    LOST = "lost"
    UNREACHABLE = "unreachable"
    RETURNED = "returned"
    REOPENED = "reopened"
    EXPIRED = "expired"
    SOLD = "sold"
    SELF_PAID = "self_paid"


ACTIVITY_KIND_LABELS = {
    ActivityKind.CLAIMED: "Olindi",
    ActivityKind.TAKEN_BACK: "«Olindi»ga qaytarildi",
    ActivityKind.NO_ANSWER: "Javob bermadi",
    ActivityKind.CALLBACK: "Qayta aloqa",
    ActivityKind.THINKING: "O'ylab ko'radi",
    ActivityKind.USING: "Foydalanmoqda",
    ActivityKind.AWAITING: "To'lov kutilmoqda",
    ActivityKind.NOTE: "Izoh",
    ActivityKind.LOST: "Rad etdi",
    ActivityKind.UNREACHABLE: "Aloqaga chiqmadi",
    ActivityKind.RETURNED: "Qaytarildi",
    ActivityKind.REOPENED: "Qayta ochildi",
    ActivityKind.EXPIRED: "Muddati o'tdi",
    ActivityKind.SOLD: "Sotildi",
    ActivityKind.SELF_PAID: "O'zi to'ladi",
}


class LiftKind(Choices):
    STAFF = "staff"
    PAID = "paid"


LIFT_KIND_LABELS = {
    LiftKind.STAFF: "Xodim qaytardi",
    LiftKind.PAID: "Mijoz o'zi to'ladi",
}
HOLD_DAYS = {HoldTerm.DAYS_30: 30, HoldTerm.DAYS_90: 90}
SELLING_STAGES = (Stage.CALLBACK, Stage.THINKING, Stage.USING, Stage.AWAITING)
CLAIM_DAYS = 7
AWAITING_EXTRA_DAYS = 3
NO_ANSWER_LIMIT = 3
NO_ANSWER_HOLD_DAYS = 30
NEW_WINDOW_DAYS = 30
BACK_WINDOW_DAYS = 90
PROBLEM_AFTER_HOURS = 24
DEFAULT_ENDING_DAYS = 3
COLUMN_CARDS = 40
SEARCH_DIGITS = 4
SEARCH_LENGTH = 100
WS_GROUP = "sales.board"
ACTION_TARGET_PROVIDER: Final = "sales"
