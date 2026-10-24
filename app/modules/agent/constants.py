from typing import Any, Final

from app.common.choices import Choices
from app.modules.audit.constants import ActionType

SUGGESTION_TTL_HOURS: Final = 48
UNANSWERED_KEEP_DAYS: Final = 30
RUN_RELATED_TYPE: Final = "agent_run"
CHECK_STALE_HOURS: Final = 30
AGENT_LOCK_SECONDS: Final = 15 * 60
RUN_STALLED_AFTER_MINUTES: Final = 30
CRASHED_CODE: Final = "crashed"
STALLED_CODE: Final = "stalled"
ASSESS_GIVE_UP_DAYS: Final = 14
ASSESS_MIN_DAYS: Final = 5
RECENT_RUNS: Final = 10
RECENT_DECIDED: Final = 12
IN_FLIGHT_MINUTES: Final = 10
IN_FLIGHT_POLL_SECONDS: Final = 3
HISTORY_PAGE: Final = 10
RECENT_OUTCOMES: Final = 3
OUTCOME_FRESH_DAYS: Final = 14
PAST_PROPOSAL_DAYS: Final = 90
PAST_PROPOSALS_PER_TARGET: Final = 3


class SuggestionStatus(Choices):
    PENDING = "pending"
    UNANSWERED = "unanswered"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"
    STALE = "stale"


SUGGESTION_STATUS_LABELS = {
    SuggestionStatus.PENDING: "Javob kutmoqda",
    SuggestionStatus.UNANSWERED: "Javobsiz",
    SuggestionStatus.APPROVED: "Tasdiqlandi",
    SuggestionStatus.REJECTED: "Rad etildi",
    SuggestionStatus.EXPIRED: "Javobsiz qoldi",
    SuggestionStatus.SUPERSEDED: "Eskirdi",
    SuggestionStatus.STALE: "Raqamlar o'zgardi",
}
OPEN_STATUSES: Final = frozenset(
    {SuggestionStatus.PENDING, SuggestionStatus.UNANSWERED}
)


class RunStatus(Choices):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


RUN_STATUS_LABELS = {
    RunStatus.RUNNING: "Ishlamoqda",
    RunStatus.DONE: "Tugadi",
    RunStatus.FAILED: "Xato",
}


class RunSource(Choices):
    NIGHT = "night"
    FAULT = "fault"


RUN_SOURCE_LABELS = {
    RunSource.NIGHT: "Kechki ko'rib chiqish",
    RunSource.FAULT: "Muammo topilganda",
}


class SkipReason(Choices):
    DISABLED = "disabled"
    EXPIRED = "expired"
    NO_ACCOUNT = "no_account"
    NO_DATA = "no_data"
    LIMIT = "limit"
    NOTHING = "nothing"
    AI_UNAVAILABLE = "ai_unavailable"
    STALE = "stale"


SKIP_REASON_LABELS = {
    SkipReason.DISABLED: "Agent o'chirilgan",
    SkipReason.EXPIRED: "Obuna muddati tugagan",
    SkipReason.NO_ACCOUNT: "Reklama akkaunti ulanmagan",
    SkipReason.NO_DATA: "Ma'lumot yetarli emas",
    SkipReason.LIMIT: "Oylik AI chegarasi tugadi",
    SkipReason.NOTHING: "O'zgartirish kerak emas",
    SkipReason.AI_UNAVAILABLE: "AI javob bermadi",
    SkipReason.STALE: "Kechagi raqamlar yangilanmagan",
}


class SuggestionOutcome(Choices):
    WORKED = "worked"
    NOT_WORKED = "not_worked"
    UNCLEAR = "unclear"
    GONE = "gone"


SUGGESTION_OUTCOME_LABELS = {
    SuggestionOutcome.WORKED: "Kutilganday bo'ldi",
    SuggestionOutcome.NOT_WORKED: "Kutilganday bo'lmadi",
    SuggestionOutcome.UNCLEAR: "Aniq bo'lmadi",
    SuggestionOutcome.GONE: "Obyekt endi yo'q",
}


class SuggestionKind(Choices):
    PAUSE = "pause"
    RESUME = "resume"
    INCREASE_BUDGET = "increase_budget"
    DECREASE_BUDGET = "decrease_budget"
    SWAP_TARGETING = "swap_targeting"
    NARROW_TARGETING = "narrow_targeting"
    DROP_AUDIENCE = "drop_audience"
    NEW_AD = "new_ad"
    NEW_PICTURE = "new_picture"


SUGGESTION_KIND_LABELS = {
    SuggestionKind.PAUSE: "To'xtatish",
    SuggestionKind.RESUME: "Davom ettirish",
    SuggestionKind.INCREASE_BUDGET: "Byudjetni oshirish",
    SuggestionKind.DECREASE_BUDGET: "Byudjetni kamaytirish",
    SuggestionKind.SWAP_TARGETING: "Auditoriyani kengaytirish",
    SuggestionKind.NARROW_TARGETING: "Auditoriyani toraytirish",
    SuggestionKind.DROP_AUDIENCE: "Buzilgan auditoriyani olib tashlash",
    SuggestionKind.NEW_AD: "Yangi matnli reklama",
    SuggestionKind.NEW_PICTURE: "Rasmni almashtirish",
}


class DiagnosisCause(Choices):
    PROVIDER_STOPPED = "provider_stopped"
    LANDING_BLOCKS = "landing_blocks"
    TOO_EARLY = "too_early"
    WORN_OUT = "worn_out"
    WEAK_CREATIVE = "weak_creative"
    COSTLY_AUDIENCE = "costly_audience"
    NOT_DELIVERING = "not_delivering"
    PROMISE_MISMATCH = "promise_mismatch"
    LEARNING_LIMITED = "learning_limited"
    NO_PROBLEM = "no_problem"
    UNCLEAR = "unclear"


DIAGNOSIS_CAUSE_LABELS = {
    DiagnosisCause.PROVIDER_STOPPED: "Reklama ko'rsatilmayapti",
    DiagnosisCause.LANDING_BLOCKS: "Forma yoki sayt to'sadi",
    DiagnosisCause.TOO_EARLY: "Hali erta",
    DiagnosisCause.WORN_OUT: "Odamlar charchagan",
    DiagnosisCause.WEAK_CREATIVE: "Reklama e'tibor tortmaydi",
    DiagnosisCause.COSTLY_AUDIENCE: "Auditoriya qimmat",
    DiagnosisCause.NOT_DELIVERING: "Reklama kam ko'rsatilyapti",
    DiagnosisCause.PROMISE_MISMATCH: "Va'da mos emas",
    DiagnosisCause.LEARNING_LIMITED: "O'rganish cheklangan",
    DiagnosisCause.NO_PROBLEM: "Muammo yo'q",
    DiagnosisCause.UNCLEAR: "Sababi aniq emas",
}


class FrequencyLevel(Choices):
    ADVICE = "advice"
    WARNING = "warning"
    REQUIRED = "required"


FREQUENCY_LEVEL_LABELS = {
    FrequencyLevel.ADVICE: "Tavsiya",
    FrequencyLevel.WARNING: "Qattiq ogohlantirish",
    FrequencyLevel.REQUIRED: "Majburiy",
}


class FrequencyAnswer(Choices):
    CREATIVE_ADDED = "creative_added"
    WORKING_WELL = "working_well"


FREQUENCY_ANSWER_LABELS = {
    FrequencyAnswer.CREATIVE_ADDED: "Kreativ qo'shildi",
    FrequencyAnswer.WORKING_WELL: "Reklama yaxshi ishlayapti",
}
APPROVE_WORD: Final = "O'zgartirish"
REJECT_WORD: Final = "Rad etish"
ACTION_LABELS: Final[dict[str, str]] = {
    "pause": "To'xtatish",
    "resume": "Davom ettirish",
    "increase_budget": "Byudjetni oshirish",
    "decrease_budget": "Byudjetni kamaytirish",
    "swap_targeting": "Kengaytirish",
    "narrow_targeting": "Toraytirish",
    "drop_audience": "Olib tashlash",
    "new_ad": "Matnni ko'rish",
    "new_picture": "Rasmni almashtirish",
}
RULE_LABELS: Final[dict[str, str]] = {
    "wasting": "Sarf bor, natija yo'q",
    "junk": "Murojaat bor, sifatlisi yo'q",
    "expensive": "Odatdagidan qimmat",
    "winning": "Arzon va byudjetga tiqilgan",
    "starved": "Auditoriya juda tor",
    "saturated": "Bir xil odamlar charchagan",
    "narrow_audience": "Auditoriyaning bir qismi behuda",
    "weak_ad": "Bitta reklama pulni behuda yeyapti",
    "idle": "Hech narsa ishlamayapti",
    "provider_stopped": "Auditoriya buzilgan, reklama to'xtagan",
    "provider_advice": "Meta ko'proq odamga yetkazishni taklif qilyapti",
    "refresh_ad": "Reklamaga yangi rasm kerak",
    "broken_picture": "Rasm ko'rinmayapti, reklama to'xtagan",
    "refused_ad": "Meta reklamani rad etdi",
    "site_down": "Sayt ochilmayapti, pul behuda ketyapti",
}
RULE_TONES: Final[dict[str, str]] = {
    "winning": "good",
    "wasting": "bad",
    "idle": "bad",
    "junk": "warn",
    "expensive": "warn",
    "starved": "warn",
    "saturated": "warn",
    "narrow_audience": "warn",
    "weak_ad": "warn",
    "provider_stopped": "bad",
    "provider_advice": "good",
    "refresh_ad": "warn",
    "broken_picture": "bad",
    "refused_ad": "bad",
    "site_down": "bad",
}
EXPECTATION_LABELS: Final[dict[str, str]] = {
    "spend_stops": "Bu guruhga pul sarflanishi to'xtaydi.",
    "more_leads": "Murojaat ko'payishi kerak - bittasining narxi oshmagan holda.",
    "cheaper_leads": "Bitta murojaat narxi tushishi kerak.",
    "more_delivery": "Reklama ko'proq odamga yetib borishi kerak.",
    "delivery_resumes": "Reklama yana ko'rsatila boshlashi kerak.",
    "group_delivery_resumes": "Reklama yana ko'rsatila boshlashi kerak.",
    "attention_recovers": "Reklamani bosish darajasi tiklanishi kerak.",
    "cheaper_reported_leads": "Bitta murojaat narxi tushishi kerak.",
    "cheaper_group_leads": "Guruh o'sha byudjet bilan murojaatni arzonroqqa olishi kerak.",
    "group_attention_recovers": "Guruhda reklamani bosish ulushi oshishi kerak.",
    "cheaper_results": "Bitta natija narxi tushishi kerak.",
    "group_cheaper_results": "Bitta natija narxi tushishi kerak.",
}
RESULT_WORDS: Final[dict[str, tuple[Any, Any]]] = {
    "lead": ("Murojaat", "Bitta murojaat narxi"),
    "chat": ("Suhbatlar", "Suhbat narxi"),
    "call": ("Qo'ng'iroqlar", "Qo'ng'iroq narxi"),
    "click": ("Saytga o'tishlar", "Bitta o'tish narxi"),
    "view": ("Ko'rishlar", "Ming ko'rish narxi"),
    "recall": ("Eslab qolganlar", "Bitta eslab qolgan narxi"),
    "profile": ("Profilga o'tishlar", "Profilga o'tish narxi"),
}
USUAL_COST_LABEL: Final = "Hisobingizda odatda"
NARROWING_LABELS: Final[dict[str, str]] = {
    "age": "Natija bermagan yosh oralig'i olib tashlanadi",
    "gender": "Natija bermagan jins olib tashlanadi",
}
WIDENING_LABELS: Final[dict[str, str]] = {
    "radius": "Qamrov masofasi kengaytiriladi",
    "age": "Yosh oralig'i kengaytiriladi",
    "interests": "Qiziqishlar bo'yicha cheklov olib tashlanadi",
}
AUTOMATION_NOTES: Final[dict[str, str]] = {
    "age_max": "Yosh yuqori chegarasi olib tashlanadi",
    "age_min": "Eng kichik yosh 25 ga tushiriladi",
}
NO_AUDIENCE_LEFT: Final = "Sizning ro'yxatlaringizdan biri ham qolmaydi - reklama qolgan sozlamalarga mos hammaga ko'rsatiladi."
NEW_PICTURE_NAMED: Final = "Kutubxonadagi «%(name)s» qo'yiladi."
STALE_GONE: Final = "gone"
STALE_CHANGED: Final = "changed"
STALE_OUTSIDE: Final = "outside"
REASON_ON_EARLIER_FIGURES: Final = "reason_on_earlier_figures"
STALE_LABELS: Final[dict[str, str]] = {
    STALE_GONE: "Bu reklama guruhi endi mavjud emas",
    STALE_CHANGED: "Raqamlar o'zgardi - bu o'zgarish endi kerak emas",
    STALE_OUTSIDE: "Bu reklama endi obunangizga kirmaydi",
}
WORDS_NOT_SHOWN: Final = "Yangi reklama matnini avval ko'rib chiqing - «Amallar» bo'limida «Matnni ko'rish» tugmasi bor."
AGENT_SPREAD_SECONDS: Final = 3600
FIX_ACTIONS: Final[dict[str, str]] = {
    "relink_page": ActionType.RELINK_PAGE,
    "recover_leads": ActionType.RECOVER_LEADS,
}
FIX_LABELS: Final[dict[str, Any]] = {
    "relink_page": "Sahifa qayta ulandi",
    "recover_leads": "Yig'ilmagan mijozlar tiklandi",
}
FIX_REASONS: Final[dict[str, Any]] = {
    "relink_page": "Sahifa mijoz arizalarini yuborishni to'xtatgan edi.",
    "recover_leads": "To'langan arizalarning bir qismi saqlanmay qolgan edi.",
}
FIX_NEWS_DAYS: Final = 7
FIXES_IN_LIST: Final = 10
AUTO_STOP_MARK: Final = "auto_stop"
AUTO_STOP_FRESH_MINUTES: Final = 60
STOPPED_SHOWN_DAYS: Final = 7
