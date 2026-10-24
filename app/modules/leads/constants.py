from typing import Any

from app.common.choices import Choices

FORMER_SITE_URLS: tuple[str, ...] = ("https://targetolog-ai.uz",)


class LeadFormStatus(Choices):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


LEAD_FORM_STATUS_LABELS = {
    LeadFormStatus.ACTIVE: "Faol",
    LeadFormStatus.ARCHIVED: "Arxivlangan",
}


class RawEventStatus(Choices):
    RECEIVED = "received"
    PROCESSED = "processed"
    FAILED = "failed"
    ORPHAN = "orphan"
    UNTRACKED = "untracked"


RAW_EVENT_STATUS_LABELS = {
    RawEventStatus.RECEIVED: "Qabul qilindi",
    RawEventStatus.PROCESSED: "Qayta ishlandi",
    RawEventStatus.FAILED: "Xato",
    RawEventStatus.ORPHAN: "Egasi topilmadi",
    RawEventStatus.UNTRACKED: "Kuzatilmaydigan akkaunt",
}


class OutcomeStatus(Choices):
    QUALIFIED = "qualified"
    UNQUALIFIED = "unqualified"


OUTCOME_STATUS_LABELS = {
    OutcomeStatus.QUALIFIED: "Sifatli",
    OutcomeStatus.UNQUALIFIED: "Sifatsiz",
}


class OutcomeSource(Choices):
    USER = "user"
    CRM = "crm"
    AGENT = "agent"


OUTCOME_SOURCE_LABELS = {
    OutcomeSource.USER: "Foydalanuvchi",
    OutcomeSource.CRM: "CRM",
    OutcomeSource.AGENT: "Agent",
}
RECONCILE_LOOKBACK_DAYS = 90
SWEEP_STUCK_DAYS = 3
FINAL_SWEEP_KEY = "leads:final-sweep:{form}"
FINAL_SWEEP_TTL_SECONDS = RECONCILE_LOOKBACK_DAYS * 24 * 60 * 60
RECONCILE_OVERLAP_HOURS = 24
ORPHAN_REPORT_HOURS = 24
ORPHAN_REPORT_PAGES = 10
FAILED_RETRY_ATTEMPTS = 5
FAILED_RETRY_COOLDOWN_MINUTES = 15
FAILED_RETRY_BATCH = 200
FAILED_RETRY_WINDOW_HOURS = 48
UNIMPORTED_GRACE_MINUTES = 20
UNIMPORTED_WINDOW_HOURS = 6
UNIMPORTED_BATCH = 200
UNIMPORTED_REPORT_HOURS = 24
UNIMPORTED_REPORT_SAMPLE = 10
LEADS_PER_PAGE = 50
UNMARKED = "unmarked"
SEARCH_DIGITS = 4
EXPORT_LIMIT = 10000
EXPORT_ANSWER_COLUMNS = 20
POLL_SECONDS = 10
LEAD_RETENTION_DAYS = 90
RECOVERY_BATCH = 200
RECOVERY_COOLDOWN_SECONDS = 300
UNSIGNED_DELIVERIES_PER_ADDRESS = 60
UNSIGNED_WINDOW_SECONDS = 60 * 60
UNSIGNED_EVENT_RETENTION_DAYS = 30
PURGE_BATCH = 5000
ANONYMIZE_LIMIT = 5000
FORMS_REFRESH_SECONDS = 60
PICKER_FORMS = 12
QUESTION_LABELS: dict[str, Any] = {
    "FULL_NAME": "Ism va familiya",
    "FIRST_NAME": "Faqat ism",
    "LAST_NAME": "Familiya",
    "PHONE": "Telefon",
    "EMAIL": "Email",
    "CITY": "Shahar",
    "STATE": "Viloyat",
    "COUNTRY": "Davlat",
    "ZIP": "Pochta indeksi",
    "STREET_ADDRESS": "Manzil",
}
VERDICTS_PER_RUN = 500
