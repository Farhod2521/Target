from typing import Final

from app.common.choices import Choices

REFERRAL_PERCENT: Final = 20
BONUS_FRIENDS_MAX: Final = 20
CODE_ALPHABET: Final = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH: Final = 8
CODE_ATTEMPTS: Final = 8
REFERRAL_SESSION_KEY: Final = "referrals:code"
INVITE_DISMISSED_SESSION_KEY: Final = "referrals:invite_dismissed"


class ReferralMode(Choices):
    AUTO = "auto"
    OPEN = "open"
    CLOSED = "closed"


REFERRAL_MODE_LABELS = {
    ReferralMode.AUTO: "Avtomatik",
    ReferralMode.OPEN: "Ochiq",
    ReferralMode.CLOSED: "Yopiq",
}


class RewardStatus(Choices):
    EARNED = "earned"


REWARD_STATUS_LABELS = {RewardStatus.EARNED: "Hisoblandi"}


class PayoutMethod(Choices):
    CARD = "card"
    BANK = "bank"
    CASH = "cash"


PAYOUT_METHOD_LABELS = {
    PayoutMethod.CARD: "Karta",
    PayoutMethod.BANK: "Bank",
    PayoutMethod.CASH: "Naqd",
}


class PayoutStatus(Choices):
    REQUESTED = "requested"
    PAID = "paid"
    REJECTED = "rejected"
    VOIDED = "voided"


PAYOUT_STATUS_LABELS = {
    PayoutStatus.REQUESTED: "Ko'rib chiqilmoqda",
    PayoutStatus.PAID: "To'langan",
    PayoutStatus.REJECTED: "Rad etildi",
    PayoutStatus.VOIDED: "Bekor qilingan",
}
CARD_DIGITS: Final = 16
CARD_HOLDER_MAX: Final = 64


class FeedbackKind(Choices):
    TEXT = "text"
    AUDIO = "audio"
    VIDEO = "video"


FEEDBACK_KIND_LABELS = {
    FeedbackKind.TEXT: "Matn",
    FeedbackKind.AUDIO: "Audio",
    FeedbackKind.VIDEO: "Video",
}
FEEDBACK_PERCENT: Final = {
    FeedbackKind.TEXT: 5,
    FeedbackKind.AUDIO: 10,
    FeedbackKind.VIDEO: 20,
}


class FeedbackStatus(Choices):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


FEEDBACK_STATUS_LABELS = {
    FeedbackStatus.PENDING: "Ko'rib chiqilmoqda",
    FeedbackStatus.APPROVED: "Tasdiqlandi",
    FeedbackStatus.REJECTED: "Rad etildi",
}
FEEDBACK_TEXT_MIN: Final = 100
FEEDBACK_TEXT_MAX: Final = 3000
FEEDBACK_UPLOAD_DIR: Final = "feedback"
FEEDBACK_EXTENSIONS: Final = {
    FeedbackKind.AUDIO: ("mp3", "m4a", "aac", "ogg", "oga", "opus", "wav", "webm"),
    FeedbackKind.VIDEO: ("mp4", "mov", "m4v", "webm"),
}
FEEDBACK_MAX_BYTES: Final = {
    FeedbackKind.AUDIO: 50 * 1024 * 1024,
    FeedbackKind.VIDEO: 200 * 1024 * 1024,
}
FEEDBACK_PROMPT_AFTER_DAYS: Final = 10
FEEDBACK_PROMPT_SESSION_KEY: Final = "feedback_prompt_answered"


class FeedbackPromptAnswer(Choices):
    OPEN = "open"
    LATER = "later"


FEEDBACK_PROMPT_ANSWER_LABELS = {
    FeedbackPromptAnswer.OPEN: "Fikr qoldirish",
    FeedbackPromptAnswer.LATER: "Keyinroq",
}
