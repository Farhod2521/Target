from app.common.choices import Choices


class Role(Choices):
    SUPPORT = "Support"
    FINANCE = "Finance"
    ENGINEER = "Engineer"
    OWNER = "Owner"
    SALES = "Sales"
    SALES_LEAD = "SalesLead"


ROLE_LABELS = {
    Role.SUPPORT: "Qo'llab-quvvatlash",
    Role.FINANCE: "Moliya",
    Role.ENGINEER: "Developer",
    Role.OWNER: "Egasi",
    Role.SALES: "Sotuv menejeri",
    Role.SALES_LEAD: "Sotuv boshlig'i",
}
ADMIN_ROLES = (Role.SUPPORT, Role.FINANCE, Role.OWNER)
MONEY_ROLES = (Role.FINANCE, Role.OWNER)
FEEDBACK_ROLES = (Role.OWNER,)
ANSWER_ROLES = (Role.SUPPORT, Role.OWNER)
SALES_ROLES = (Role.SALES, Role.SALES_LEAD, Role.OWNER)
SALES_LEAD_ROLES = (Role.SALES_LEAD, Role.OWNER)


class Severity(Choices):
    URGENT = "urgent"
    WAITING = "waiting"


SEVERITY_LABELS = {Severity.URGENT: "Shoshilinch", Severity.WAITING: "Kutilmoqda"}
PAGE_SIZE = 50


class TakingsPeriod(Choices):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"
    RANGE = "range"


TAKINGS_PERIOD_LABELS = {
    TakingsPeriod.DAY: "Kunlik",
    TakingsPeriod.WEEK: "Haftalik",
    TakingsPeriod.MONTH: "Oylik",
    TakingsPeriod.YEAR: "Yillik",
    TakingsPeriod.RANGE: "Oraliq",
}
TAKINGS_CACHE_SECONDS = 10 * 60
PAYMENT_FEED_ROWS = 15
STUCK_HOLD_HOURS = 12
EXPIRING_DAYS = 7


class ActionKind(Choices):
    VIEW = "view"
    PROMO_APPROVED = "promo_approved"
    PROMO_REJECTED = "promo_rejected"
    PLAN_GIVEN = "plan_given"
    DAYS_GRANTED = "days_granted"
    PAGES_GRANTED = "pages_granted"
    PAGES_REVOKED = "pages_revoked"
    PAGE_ADDED = "page_added"
    PAGE_MOVED = "page_moved"
    PAGE_ACCOUNT_CHANGED = "page_account_changed"
    PAGE_PAIR_REMOVED = "page_pair_removed"
    RECEIPTS_ATTACHED = "receipts_attached"
    ACCOUNT_PURGED = "account_purged"
    PASSWORD_SET = "password_set"
    PAYMENT_RECORDED = "payment_recorded"
    REFERRAL_CHANGED = "referral_changed"
    HOLD_RELEASED = "hold_released"
    ROLES_CHANGED = "roles_changed"
    WITHDRAWAL_PAID = "withdrawal_paid"
    WITHDRAWAL_REJECTED = "withdrawal_rejected"
    WITHDRAWAL_VOIDED = "withdrawal_voided"
    FEEDBACK_APPROVED = "feedback_approved"
    FEEDBACK_REJECTED = "feedback_rejected"
    FEEDBACK_FILE = "feedback_file"
    FEEDBACK_PUBLISHED = "feedback_published"
    SUPPORT_VIEW = "support_view"
    SUPPORT_FILE = "support_file"
    PROMO_CODE_CREATED = "promo_code_created"
    PROMO_CODE_UPDATED = "promo_code_updated"
    PROMO_CODE_DELETED = "promo_code_deleted"
    SALES_VIEW = "sales_view"
    SALES_CLAIMED = "sales_claimed"
    SALES_RETURNED = "sales_returned"
    SALES_LOST = "sales_lost"
    SALES_HOLD_LIFTED = "sales_hold_lifted"
    SALES_SETTINGS_CHANGED = "sales_settings"


ACTION_KIND_LABELS = {
    ActionKind.VIEW: "Karta ochildi",
    ActionKind.PROMO_APPROVED: "Promo tasdiqlandi",
    ActionKind.PROMO_REJECTED: "Promo rad etildi",
    ActionKind.PLAN_GIVEN: "Tarif berildi",
    ActionKind.DAYS_GRANTED: "Kun berildi",
    ActionKind.PAGES_GRANTED: "O'rin berildi",
    ActionKind.PAGES_REVOKED: "O'rin olindi",
    ActionKind.PAGE_ADDED: "Qo'shimcha sahifa yoqildi",
    ActionKind.PAGE_MOVED: "Sahifa o'tkazildi",
    ActionKind.PAGE_ACCOUNT_CHANGED: "Sahifaning reklama akkaunti almashtirildi",
    ActionKind.PAGE_PAIR_REMOVED: "Sahifa juftligi o'chirildi",
    ActionKind.RECEIPTS_ATTACHED: "Eski cheklar ulandi",
    ActionKind.ACCOUNT_PURGED: "Akkaunt o'chirildi",
    ActionKind.PASSWORD_SET: "Parol o'rnatildi",
    ActionKind.PAYMENT_RECORDED: "To'lov qayd etildi",
    ActionKind.REFERRAL_CHANGED: "Referal o'zgardi",
    ActionKind.HOLD_RELEASED: "Hisob bo'shatildi",
    ActionKind.ROLES_CHANGED: "Rollar o'zgardi",
    ActionKind.WITHDRAWAL_PAID: "Daromad to'lovi qayd etildi",
    ActionKind.WITHDRAWAL_REJECTED: "Pul yechish so'rovi rad etildi",
    ActionKind.WITHDRAWAL_VOIDED: "Daromad to'lovi bekor qilindi",
    ActionKind.FEEDBACK_APPROVED: "Fikr tasdiqlandi",
    ActionKind.FEEDBACK_REJECTED: "Fikr rad etildi",
    ActionKind.FEEDBACK_FILE: "Fikr fayli ochildi",
    ActionKind.FEEDBACK_PUBLISHED: "Fikr saytga chiqarildi",
    ActionKind.SUPPORT_VIEW: "Yordam suhbati o'qildi",
    ActionKind.SUPPORT_FILE: "Yordam fayli yuklab olindi",
    ActionKind.PROMO_CODE_CREATED: "Promo kod yaratildi",
    ActionKind.PROMO_CODE_UPDATED: "Promo kod o'zgartirildi",
    ActionKind.PROMO_CODE_DELETED: "Promo kod o'chirildi",
    ActionKind.SALES_VIEW: "Sotuv kartasi ochildi",
    ActionKind.SALES_CLAIMED: "Sotuvga olindi",
    ActionKind.SALES_RETURNED: "Sotuvdan qaytarildi",
    ActionKind.SALES_LOST: "Sotuvda rad etdi",
    ActionKind.SALES_HOLD_LIFTED: "Qo'ng'iroq taqiqi olindi",
    ActionKind.SALES_SETTINGS_CHANGED: "Sotuv sozlamalari o'zgardi",
}
READ_KINDS = (
    ActionKind.VIEW,
    ActionKind.SUPPORT_VIEW,
    ActionKind.SUPPORT_FILE,
    ActionKind.SALES_VIEW,
)
WRITE_KINDS = tuple(kind for kind in ActionKind if kind not in READ_KINDS)
GRANT_KINDS = (
    ActionKind.PLAN_GIVEN,
    ActionKind.DAYS_GRANTED,
    ActionKind.PAGES_GRANTED,
    ActionKind.PAGE_ADDED,
)
VIEW_QUIET_MINUTES = 30
JOURNAL_PAGE = 50
CARD_TRACES = 6
