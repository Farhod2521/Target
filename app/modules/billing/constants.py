from typing import Final

from app.common.choices import Choices


class SubscriptionStatus(Choices):
    TRIAL = "trial"
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELED = "canceled"


SUBSCRIPTION_STATUS_LABELS = {
    SubscriptionStatus.TRIAL: "Sinov",
    SubscriptionStatus.ACTIVE: "Faol",
    SubscriptionStatus.EXPIRED: "Muddati tugagan",
    SubscriptionStatus.CANCELED: "Bekor qilingan",
}


class PlanMove(Choices):
    STACK = "stack"
    RESTART = "restart"
    WAIT = "wait"


PLAN_MOVE_LABELS = {
    PlanMove.STACK: "Ustiga qo'shiladi",
    PlanMove.RESTART: "Bugundan boshlanadi",
    PlanMove.WAIT: "Muddat tugashini kutadi",
}


class HistoryKind(Choices):
    TRIAL = "trial"
    PAID = "paid"
    GIVEN = "given"
    PROMO = "promo"
    REFUNDED = "refunded"
    PAGES = "pages"
    SEATS = "seats"


HISTORY_KIND_LABELS = {
    HistoryKind.TRIAL: "Sinov boshlandi",
    HistoryKind.PAID: "To'lov",
    HistoryKind.GIVEN: "Ofis berdi",
    HistoryKind.PROMO: "Promo kod",
    HistoryKind.REFUNDED: "Pul qaytarildi",
    HistoryKind.PAGES: "Qo'shimcha sahifa",
    HistoryKind.SEATS: "CRM menejeri",
}


class WalletChoice(Choices):
    USE = "use"
    KEEP = "keep"


WALLET_CHOICE_LABELS = {
    WalletChoice.USE: "Balansdan ishlatish",
    WalletChoice.KEEP: "Balansga tegmaslik",
}


class InvoiceKind(Choices):
    PLAN = "plan"
    PAGES = "pages"
    SEATS = "seats"


INVOICE_KIND_LABELS = {
    InvoiceKind.PLAN: "Tarif",
    InvoiceKind.PAGES: "Qo'shimcha sahifa",
    InvoiceKind.SEATS: "CRM menejeri",
}


class PagesChoice(Choices):
    KEEP = "keep"
    DROP = "drop"


PAGES_CHOICE_LABELS = {
    PagesChoice.KEEP: "Sahifalarni qoldirish",
    PagesChoice.DROP: "Sahifalarsiz",
}


class PlanFeatureKind(Choices):
    INCLUDED = "included"
    UNLIMITED = "unlimited"
    LIMITED = "limited"
    HEADING = "heading"


PLAN_FEATURE_KIND_LABELS = {
    PlanFeatureKind.INCLUDED: "Bor",
    PlanFeatureKind.UNLIMITED: "Cheksiz",
    PlanFeatureKind.LIMITED: "Limitli",
    PlanFeatureKind.HEADING: "Sarlavha",
}
PAGE_PRICE_DAYS: Final = 30
MAX_PAGES_PER_PURCHASE: Final = 10
LIVE_SUBSCRIPTION_STATUSES = (SubscriptionStatus.TRIAL, SubscriptionStatus.ACTIVE)
TRIAL_DAYS = 3
TRIAL_MAX_CAMPAIGNS: Final = 3
MAX_GRANT_DAYS = 120
MAX_SLOT_CHANGE = 20
DEFAULT_PLAN_CODE = "start"
CHAT_SHARE_PCT: Final = 80


class InvoiceStatus(Choices):
    PENDING = "pending"
    HELD = "held"
    PAID = "paid"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REFUNDED = "refunded"


INVOICE_STATUS_LABELS = {
    InvoiceStatus.PENDING: "To'lanmagan",
    InvoiceStatus.HELD: "To'lov kutilmoqda",
    InvoiceStatus.PAID: "To'langan",
    InvoiceStatus.CANCELED: "Bekor qilingan",
    InvoiceStatus.EXPIRED: "Muddati o'tgan",
    InvoiceStatus.REFUNDED: "Qaytarilgan",
}


class ManualMethod(Choices):
    CASH = "cash"
    TRANSFER = "transfer"
    CARD = "card"


MANUAL_METHOD_LABELS = {
    ManualMethod.CASH: "Naqd",
    ManualMethod.TRANSFER: "O'tkazma",
    ManualMethod.CARD: "Karta",
}


class PromoKind(Choices):
    PLAN = "plan"
    SLOTS = "slots"
    DISCOUNT = "discount"


PROMO_KIND_LABELS = {
    PromoKind.PLAN: "Tarif",
    PromoKind.SLOTS: "Qo'shimcha o'rin",
    PromoKind.DISCOUNT: "Chegirma",
}


class RedemptionStatus(Choices):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


REDEMPTION_STATUS_LABELS = {
    RedemptionStatus.PENDING: "Ko'rib chiqilmoqda",
    RedemptionStatus.APPROVED: "Tasdiqlangan",
    RedemptionStatus.REJECTED: "Rad etilgan",
}
HELD_REDEMPTION_STATUSES = (RedemptionStatus.PENDING, RedemptionStatus.APPROVED)


class PromoDiscountKind(Choices):
    NONE = "none"
    PERCENT = "percent"
    AMOUNT = "amount"


PROMO_DISCOUNT_KIND_LABELS = {
    PromoDiscountKind.NONE: "Chegirmasiz",
    PromoDiscountKind.PERCENT: "Foiz",
    PromoDiscountKind.AMOUNT: "Summa",
}


class PromoScope(Choices):
    SUBSCRIPTION = "subscription"
    ADDON = "addon"
    BOTH = "both"


PROMO_SCOPE_LABELS = {
    PromoScope.SUBSCRIPTION: "Obuna",
    PromoScope.ADDON: "Qo'shimcha",
    PromoScope.BOTH: "Ikkalasi",
}


class TransactionState(Choices):
    CREATED = "created"
    PERFORMED = "performed"
    CANCELED = "canceled"
    REFUNDED = "refunded"


TRANSACTION_STATE_LABELS = {
    TransactionState.CREATED: "Boshlangan",
    TransactionState.PERFORMED: "To'langan",
    TransactionState.CANCELED: "Bekor qilingan",
    TransactionState.REFUNDED: "Qaytarilgan",
}
PAYABLE_INVOICE_STATUSES = (InvoiceStatus.PENDING,)
UNPAID_END_STATUSES = (InvoiceStatus.EXPIRED, InvoiceStatus.CANCELED)
INVOICE_TTL_HOURS: Final = 24
TRANSACTION_TTL_HOURS: Final = 12
INVOICE_NUMBER_DIGITS: Final = 10
TRANSACTION_REFERENCE_DIGITS: Final = 12
NUMBER_ATTEMPTS: Final = 8
EXPIRY_REMINDER_DAYS: Final = (3, 1)
EXPIRY_NOTICE_SEEN: Final = "billing:expiry_notice_seen"
PROMO_GAINS: Final = "billing:promo_gains"
POLL_SECONDS: Final = 3
MAX_POLL_TRIES: Final = 60
SETTLED_INVOICE_STATUSES = (
    InvoiceStatus.PAID,
    InvoiceStatus.CANCELED,
    InvoiceStatus.EXPIRED,
    InvoiceStatus.REFUNDED,
)
LAPSED_SWEEP_DAYS: Final = 30
