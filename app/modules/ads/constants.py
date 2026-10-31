from datetime import timedelta
from typing import Any, Final

from app.common.choices import Choices


class Delivery(Choices):
    ACTIVE = "active"
    PAUSED = "paused"
    PAUSED_ABOVE = "paused_above"
    PENDING = "pending"
    BILLING = "billing"
    REJECTED = "rejected"
    FINISHED = "finished"
    UNKNOWN = "unknown"


DELIVERY_LABELS = {
    Delivery.ACTIVE: "Ishlayapti",
    Delivery.PAUSED: "To'xtatilgan",
    Delivery.PAUSED_ABOVE: "Kampaniya to'xtatilgan",
    Delivery.PENDING: "Tekshiruvda",
    Delivery.BILLING: "To'lov kutilmoqda",
    Delivery.REJECTED: "Muammo bor",
    Delivery.FINISHED: "Tugagan",
    Delivery.UNKNOWN: "Noma'lum",
}
LEARNING_LIMITED: frozenset[str] = frozenset({"LEARNING_LIMITED", "FAIL"})
SWITCHED_OFF: frozenset[str] = frozenset({Delivery.PAUSED})
NOT_RUNNING: frozenset[str] = SWITCHED_OFF | frozenset({Delivery.FINISHED})
NOT_LIVE: frozenset[str] = NOT_RUNNING | frozenset({Delivery.PAUSED_ABOVE})
PROMPT_LANGUAGE: dict[str, str] = {
    "uz": "Uzbek (latin script)",
    "ru": "Russian",
    "en": "English",
}
SYNC_LOCK_SECONDS = 660
REFUSED_SAMPLE = 10
SYNC_OUTCOME_KEY = "ads:sync-outcome:{sweep}:{account_id}"
SYNC_OUTCOME_SECONDS = 26 * 60 * 60
MIRROR_SWEEP: Final = "mirror"
FIGURES_SWEEP: Final = "figures"
TODAY_SWEEP: Final = "today"
SYNC_STARTED: Final = "started"
SYNC_QUEUED: Final = "queued"
SYNC_TRUNCATED = "truncated"
SYNC_RATE_LIMITED = "rate_limited"
SYNC_STALE_MINUTES = 180
AUTO_SYNC_COOLING_MINUTES = 15
PRESS_WINDOW_SECONDS = 60
REFRESH_QUEUE: Final = "refresh"
MAX_SYNC_POLLS = 40
MAX_FORMS_POLLS = 5
CAMPAIGNS_PER_PAGE = 25
AUTO_START_WAIT_SECONDS = 10
MAX_AUTO_START_TRIES = 30
AUTO_START_RESYNC_TRY = 6
STARTED_SESSION_KEY = "ads:started_launch"


class LaunchStatus(Choices):
    DRAFT = "draft"
    BUILDING = "building"
    READY = "ready"
    CREATING = "creating"
    CREATED = "created"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


LAUNCH_STATUS_LABELS = {
    LaunchStatus.DRAFT: "Qoralama",
    LaunchStatus.BUILDING: "Tayyorlanmoqda",
    LaunchStatus.READY: "Tayyor",
    LaunchStatus.CREATING: "Yaratilmoqda",
    LaunchStatus.CREATED: "Yaratildi",
    LaunchStatus.FAILED: "Xato",
    LaunchStatus.ROLLED_BACK: "Bekor qilindi",
}


class LaunchStep(Choices):
    ANSWERS = "answers"
    PRESET = "preset"
    ASKING = "asking"
    LLM = "llm"
    VALIDATE = "validate"
    INTERESTS = "interests"
    ESTIMATE = "estimate"
    FORM = "form"
    IMAGE = "image"
    CAMPAIGN = "campaign"
    ADSET = "adset"
    CREATIVE = "creative"
    AD = "ad"
    VERIFY = "verify"


LAUNCH_STEP_LABELS = {
    LaunchStep.ANSWERS: "Javoblar",
    LaunchStep.PRESET: "Shablon tanlandi",
    LaunchStep.ASKING: "AI so'raldi",
    LaunchStep.LLM: "AI tayyorladi",
    LaunchStep.VALIDATE: "Tekshirildi",
    LaunchStep.INTERESTS: "Qiziqishlar tasdiqlandi",
    LaunchStep.ESTIMATE: "Qamrov hisoblandi",
    LaunchStep.FORM: "Forma yaratildi",
    LaunchStep.IMAGE: "Rasm yuklandi",
    LaunchStep.CAMPAIGN: "Kampaniya yaratildi",
    LaunchStep.ADSET: "Guruh yaratildi",
    LaunchStep.CREATIVE: "Kreativ yaratildi",
    LaunchStep.AD: "Reklama yaratildi",
    LaunchStep.VERIFY: "Tasdiqlandi",
}
GEO_AROUND = "around"
GEO_PLACES = "places"
GEO_COUNTRY = "country"
GEO_MODE_CHOICES: tuple[tuple[str, Any], ...] = (
    (GEO_AROUND, "Xaritada belgilangan joy atrofida"),
    (GEO_PLACES, "Tanlangan shaharlarda"),
    (GEO_COUNTRY, "Butun mamlakat bo'ylab"),
)
MAX_GEO_PLACES = 10
MAX_GEO_LOOKUPS = 5
MIN_GEO_SEARCH = 2
MAX_GEO_SEARCH = 100
MAX_GEO_ADDRESS = 300
GEO_SEARCHES_PER_MINUTE = 60


class GeoAreaKind(Choices):
    REGION = "region"
    CITY = "city"


GEO_AREA_KIND_LABELS = {GeoAreaKind.REGION: "Viloyat", GeoAreaKind.CITY: "Shahar"}
QUESTION_TYPES: Final[dict[str, str]] = {
    "full_name": "FULL_NAME",
    "first_name": "FIRST_NAME",
    "last_name": "LAST_NAME",
    "phone": "PHONE",
    "email": "EMAIL",
    "city": "CITY",
    "state": "STATE",
    "country": "COUNTRY",
    "zip": "ZIP",
    "street_address": "STREET_ADDRESS",
}
CUSTOM: Final = "CUSTOM"
PHONE_QUESTION_LABEL = "Telefon raqamingiz"
# The words an AI form asks a name and a number in, typed by hand rather
# than prefilled: the form's own, so Uzbek like every question the model writes.
TYPED_NAME_LABEL: Final = "Ism familiyangiz"
TYPED_FIRST_NAME_LABEL: Final = "Ismingiz"
TYPED_PHONE_LABEL: Final = "Telefon raqamingiz"


class DraftSection(Choices):
    AUDIENCE = "audience"
    INTERESTS = "interests"
    TRAITS = "traits"
    CREATIVE = "creative"
    FORM = "form"


DRAFT_SECTION_LABELS = {
    DraftSection.AUDIENCE: "Auditoriya",
    DraftSection.INTERESTS: "Qiziqishlar",
    DraftSection.TRAITS: "Holat va odatlar",
    DraftSection.CREATIVE: "Reklamalar",
    DraftSection.FORM: "Lid formasi",
}
ADVICE_REASONS: dict[str, Any] = {
    "provider_expands": "Meta reklamaga kim javob berishini o'zi o'rganib, shunday odamlarni topib boradi. Meta ham shuni tavsiya qiladi.",
    "provider_default": "Meta reklamani hamma joyda sinab ko'radi va qaysi biri arzonroq ishlashini o'zi topadi. Meta ham shuni tavsiya qiladi.",
    "same_questions": "Bu formada aynan shu savollar bor — yangisini yasashning hojati yo'q. Meta formani o'chirishga ruxsat bermaydi.",
    "nothing_matches": "Tayyor formalaringiz orasida aynan shu savollarni so'raydigani yo'q.",
    "signal_is_ready": "Siz yetarlicha lidni baholab bo'ldingiz va ular Meta'ga yuborilyapti. Endi Meta shunchaki forma to'ldiruvchini emas, aynan shunday mijozlarni qidira oladi.",
    "calls_cheapest": "Qo'ng'iroq uchun odatda eng arzon yo'l: reklama ko'p odamga ko'rsatiladi va bosganlar sizga qo'ng'iroq qiladi.",
    "form_leads_proven": "Ariza formasi uchun mijozlarimizda ishlab turgan yo'l.",
    "site_visits_counted": "Saytingizga yetib kelganlar sanaladi. Saytda Meta pikseli topilmasa, havolani bosganlar sanaladi.",
    "site_requests_counted": "Saytingizdagi arizalarni Meta pikseli sanaydi va Meta shunday ariza qoldiradiganlarni qidiradi.",
    "seen_most": "Reklama iloji boricha ko'p marta ko'rsatiladi.",
    "chat_proven": "Suhbat uchun mijozlarimizda ishlab turgan yo'l.",
    "event_already_arriving": "Saytingiz shu hodisani Meta'ga yuborib turibdi — reklama aynan shunga qarab o'rganadi.",
    "event_nothing_seen": "Saytingizdan hali birorta hodisa ko'rinmadi. Eng keng tarqalgan nomi tanlandi — saytingiz boshqa nom yuborsa, Meta hech narsani sanamaydi.",
    "proven_default": "Mijozlarimizda ishlab turgan yo'l.",
}
CAMPAIGN_TYPE_LABELS: dict[str, Any] = {
    "calls_many": "Qo'ng'iroqlar",
    "calls_engaged": "Qo'ng'iroqlar",
    "calls_ready": "Qo'ng'iroqlar",
    "form_leads": "Reklama ichidagi forma",
    "form_quality_leads": "Sifatli arizalar",
    "site_page_views": "Sahifani ochganlar",
    "site_link_clicks": "Havolani bosganlar",
    "site_daily_reach": "Kuniga yangi odamlar",
    "site_impressions": "Ko'p marta ko'rsatish",
    "site_requests": "Saytingizdagi forma",
    "site_requests_views": "Ariza sahifasi ochilishi",
    "site_requests_clicks": "Ariza havolasi bosilishi",
    "site_requests_reach": "Ariza sahifasiga yangi odamlar",
    "seen_often": "Ko'proq marta",
    "seen_widely": "Ko'proq odamga",
    "seen_remembered": "Eslab qolsin",
    "chat_conversations": "Suhbatlar",
    "chat_link_clicks": "Chat havolasi bosilishi",
    "profile_visits": "Profilga o'tsin",
}
OUTCOME_LABELS: dict[str, Any] = {
    "requests": "Ariza yig'ish",
    "calls": "Qo'ng'iroq",
    "messages": "Xabar yozishsin",
    "visits": "Saytga tashrif",
    "profile": "Profilga o'tsin",
    "reach": "Ko'proq odam ko'rsin",
    "sales": "Sotuv",
}
OUTCOME_HINTS: dict[str, Any] = {
    "requests": "Odam ismi va raqamini qoldiradi — ariza sizga keladi.",
    "calls": "Odam reklamadagi tugmani bosib, sizga qo'ng'iroq qiladi.",
    "messages": "Odam reklamani bosib, sizga yozadi.",
    "visits": "Odam reklamani bosib, saytingizga o'tadi.",
    "profile": "Odam reklamani bosib, Instagram profilingizga o'tadi.",
    "reach": "Reklama ko'proq odamga ko'rsatiladi. Ariza kutilmaydi.",
    "sales": "Saytingizda xarid qilishadi.",
}
CLOSED_REASONS: dict[str, Any] = {
    "pixel": "Piksel ulanmagan",
    "quality_signal": "28 kunda 50 ta belgilangan ariza kerak",
    "instagram": "Instagram ulanmagan",
    "not_built": "Tez orada",
}
ROW_PHRASES: Final[tuple[tuple[str, Any], ...]] = (
    ("form_leads", "Raqamini qoldirsin"),
    ("chat_conversations", "Instagram'da yozsin"),
    ("calls_many", "Menga qo'ng'iroq qilsin"),
    ("site_page_views", "Saytimga kirsin"),
    ("seen_widely", "Ko'proq odam bilsin"),
    ("site_requests", "Saytda ariza qoldirsin"),
)
ATTRIBUTION_LABELS: dict[str, Any] = {
    "click_7_view_1": "7 kun bosish, 1 kun ko'rish",
    "click_7": "7 kun bosish",
    "click_1_view_1": "1 kun bosish, 1 kun ko'rish",
    "click_1": "1 kun bosish",
}
BUTTON_LABELS: dict[str, Any] = {
    "LEARN_MORE": "Batafsil",
    "SHOP_NOW": "Xarid qilish",
    "SIGN_UP": "Ro'yxatdan o'tish",
    "ORDER_NOW": "Buyurtma berish",
    "BOOK_TRAVEL": "Band qilish",
    "APPLY_NOW": "Ariza topshirish",
    "GET_QUOTE": "Narxni bilish",
    "GET_OFFER": "Taklifni olish",
    "CONTACT_US": "Bog'lanish",
    "SUBSCRIBE": "Obuna bo'lish",
    "DOWNLOAD": "Yuklab olish",
    "SEE_MENU": "Menyuni ko'rish",
    "GET_DIRECTIONS": "Yo'l ko'rsatish",
    "SEND_MESSAGE": "Xabar yuborish",
    "CALL_NOW": "Qo'ng'iroq qilish",
    "NO_BUTTON": "Tugmasiz",
    "VIEW_INSTAGRAM_PROFILE": "Profilga o'tish",
}
CONVERSION_EVENT_LABELS: dict[str, Any] = {
    "LEAD": "Ariza",
    "CONTACT": "Bog'lanish",
    "COMPLETE_REGISTRATION": "Ro'yxatdan o'tish",
    "SUBMIT_APPLICATION": "Ariza yuborish",
    "SCHEDULE": "Uchrashuv belgilash",
    "START_TRIAL": "Sinovni boshlash",
    "SUBSCRIBE": "Obuna bo'lish",
    "FIND_LOCATION": "Manzilni topish",
    "CONTENT_VIEW": "Sahifani ko'rish",
    "SEARCH": "Qidiruv",
    "ADD_TO_CART": "Savatga qo'shish",
    "ADD_TO_WISHLIST": "Saqlanganlarga qo'shish",
    "INITIATED_CHECKOUT": "To'lovni boshlash",
    "ADD_PAYMENT_INFO": "To'lov ma'lumotini kiritish",
    "PURCHASE": "Xarid",
    "DONATE": "Xayriya",
    "OTHER": "Boshqa hodisa",
}
CAMPAIGN_TYPE_HINTS: dict[str, Any] = {
    "calls_many": "Meta reklamani qo'ng'iroq qilishi ehtimoli yuqori odamlarga ko'rsatadi.",
    "calls_engaged": "Xuddi shu qo'ng'iroq — farqi faqat Meta maqsadida (kulrang yozuv).",
    "calls_ready": "Xuddi shu qo'ng'iroq — farqi faqat Meta maqsadida (kulrang yozuv).",
    "form_leads": "Odam reklamadagi formani to'ldiradi, ismi va raqami sizga keladi.",
    "form_quality_leads": "Meta siz sifatli deb belgilagan arizalarga o'xshash odamlarni qidiradi.",
    "site_page_views": "Sayt sahifasi ochilganda sanaladi.",
    "site_link_clicks": "Havola bosilganda sanaladi, sahifa ochilmasa ham.",
    "site_daily_reach": "Har kuni iloji boricha ko'proq turli odamga ko'rsatiladi.",
    "site_impressions": "Reklama ko'p marta ko'rsatiladi — bir odamga bir necha marta tushishi mumkin.",
    "site_requests": "Saytdagi ariza Meta pikseli orqali sanaladi.",
    "site_requests_views": "Meta arizani emas, ariza sahifasi ochilishini qidiradi.",
    "site_requests_clicks": "Meta arizani emas, havola bosilishini qidiradi.",
    "site_requests_reach": "Har kuni ko'proq turli odam ariza sahifangizni ko'radi.",
    "seen_often": "Reklama iloji boricha ko'p marta ko'rsatiladi — bir odamga bir necha marta tushishi mumkin.",
    "seen_widely": "Iloji boricha ko'proq turli odamga ko'rsatiladi.",
    "seen_remembered": "Meta reklamani esda qoladigan qilib ko'rsatishga harakat qiladi.",
    "chat_conversations": "Odam reklamani bosib, sizga xabar yozadi.",
    "chat_link_clicks": "Meta suhbatni emas, bosishni qidiradi — yozadiganlar kamroq bo'lishi mumkin.",
    "profile_visits": "Meta Instagram profilingizga o'tishi ehtimoli yuqori odamlarga ko'rsatadi.",
}


class ChatChannel(Choices):
    MESSENGER = "messenger"
    INSTAGRAM = "instagram"


CHAT_CHANNEL_LABELS = {
    ChatChannel.MESSENGER: "Messenger",
    ChatChannel.INSTAGRAM: "Instagram Direct",
}
CHAT_CHANNEL_NOTES: dict[str, Any] = {
    ChatChannel.MESSENGER: "Xabar Facebook sahifangizning yozishmalariga tushadi.",
    ChatChannel.INSTAGRAM: "Xabar Instagram akkauntingizning Direct'iga tushadi.",
}


class TargetingMode(Choices):
    AUTOMATIC = "automatic"
    INTERESTS = "interests"
    BROAD = "broad"


TARGETING_MODE_LABELS = {
    TargetingMode.AUTOMATIC: "Meta o'zi tanlaydi",
    TargetingMode.INTERESTS: "Siz tanlagan qiziqishlar bo'yicha",
    TargetingMode.BROAD: "Keng - faqat hudud, yosh va jins",
}
TARGETING_MODE_NOTES = {
    TargetingMode.AUTOMATIC: "Qiziqishlar yuborilmaydi - Meta kimga ko'rsatishni o'zi topadi. Hudud va eng kichik yosh o'zgarmaydi; yoshning yuqori chegarasi esa olib tashlanadi.",
    TargetingMode.INTERESTS: "Reklama faqat shu qiziqishlardagi odamlarga ko'rsatiladi. Tanlaganingiz - o'zgarmaydi.",
    TargetingMode.BROAD: "Qiziqishlar ishlatilmaydi. Hudud, yosh va jins aniq saqlanadi - Meta ulardan tashqariga chiqmaydi.",
}
INSTAGRAM_ONLY_LABEL: Final = "Faqat Instagram"
INSTAGRAM_ONLY_NOTE: Final = "Reklama odamni Instagram profilingizga olib boradi, shuning uchun u faqat Instagram'da ko'rsatiladi — lenta, Stories, Reels va qidiruvda."
LEGACY_PLAN_DESTINATIONS: Final[frozenset[str]] = frozenset(
    {"form", "website", "phone", "chat", "nothing"}
)


class PlacementMode(Choices):
    AUTOMATIC = "automatic"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    STANDARD = "standard"


PLACEMENT_MODE_LABELS = {
    PlacementMode.AUTOMATIC: "Meta o'zi tanlaydi",
    PlacementMode.INSTAGRAM: "Faqat Instagram",
    PlacementMode.FACEBOOK: "Faqat Facebook",
    PlacementMode.STANDARD: "Faqat Facebook va Instagram",
}
OFFERED_PLACEMENT_MODES: Final[tuple[PlacementMode, ...]] = (
    PlacementMode.AUTOMATIC,
    PlacementMode.INSTAGRAM,
    PlacementMode.FACEBOOK,
)
PLACEMENT_MODE_NOTES = {
    PlacementMode.AUTOMATIC: "Meta reklamani o'zi tanlagan joylarda - jumladan boshqa ilovalarda ham - ko'rsatadi va arzonrog'ini qidiradi. Ko'rsatish arzonlashadi, lekin murojaat sifati o'zgarishini biz joylashuv bo'yicha o'lchay olmaymiz.",
    PlacementMode.INSTAGRAM: "Reklama faqat Instagram lentasi, Stories va Reels'da ko'rsatiladi. Facebook'ga va boshqa ilovalarga chiqmaydi.",
    PlacementMode.FACEBOOK: "Reklama faqat Facebook lentasi, Stories va Reels'da ko'rsatiladi. Instagram'ga va boshqa ilovalarga chiqmaydi.",
    PlacementMode.STANDARD: "Reklama faqat Facebook lentasida, Instagram lentasi, Stories va Reels'da ko'rsatiladi. Boshqa ilovalarga chiqmaydi.",
}


class LeadBuying(Choices):
    VOLUME = "volume"
    QUALITY = "quality"


LEAD_BUYING_LABELS = {
    LeadBuying.VOLUME: "Har bir ariza",
    LeadBuying.QUALITY: "Faqat sifatli lidlar",
}
LEAD_BUYING_NOTES = {
    LeadBuying.VOLUME: "Meta formani to'ldiradigan odamni qidiradi. Bugungacha hamma kampaniya shunday ishlagan.",
    LeadBuying.QUALITY: "Siz «Sifatli» deb belgilagan lidlar Meta'ga qaytariladi va Meta shunday odamlarni qidira boshlaydi. Lid narxi ko'tarilishi mumkin, lekin sifatli lid narxi tushadi. Lid oqimi kamayishi ham mumkin - Meta kamroq uchraydigan natijani qidiradi.",
}


class InterestSource(Choices):
    CATALOG = "catalog"
    AI = "ai"
    USER = "user"


INTEREST_SOURCE_LABELS = {
    InterestSource.CATALOG: "Katalog",
    InterestSource.AI: "AI",
    InterestSource.USER: "Foydalanuvchi",
}
MAX_REGENERATIONS = 1
NARROW_AUDIENCE = 20000


class MediaKind(Choices):
    IMAGE = "image"
    VIDEO = "video"
    POST = "post"
    UPLOAD = "upload"
    IG_IMAGE = "ig_image"
    IG_VIDEO = "ig_video"


MEDIA_KIND_LABELS = {
    MediaKind.IMAGE: "Rasm",
    MediaKind.VIDEO: "Video",
    MediaKind.POST: "Sahifa posti",
    MediaKind.UPLOAD: "Yuklangan fayl",
    MediaKind.IG_IMAGE: "Instagram rasmi",
    MediaKind.IG_VIDEO: "Instagram videosi",
}
IG_KINDS: Final[tuple[str, ...]] = (MediaKind.IG_IMAGE, MediaKind.IG_VIDEO)
POSTS_NOT_PROMOTED: Final = "posts_not_promoted"


class PostRoute(Choices):
    PROMOTED = "promoted"
    COPIED_FOR_CALLS = "calls"
    COPIED_FOR_WORDS = "words"


POST_ROUTE_LABELS = {
    PostRoute.PROMOTED: "Post o'z joyida reklama qilinadi — layk va izohlar saqlanadi.",
    PostRoute.COPIED_FOR_CALLS: "Qo'ng'iroq maqsadida post o'z joyida reklama qilinmaydi — reklama yangi post bo'lib chiqadi. Layk va izohlar ko'chmaydi.",
    PostRoute.COPIED_FOR_WORDS: "Matn o'zgardi — reklama yangi post bo'lib chiqadi. Layk va izohlar ko'chmaydi.",
}


class LibraryUpload(Choices):
    PENDING = "pending"
    FAILED = "failed"


LIBRARY_UPLOAD_LABELS = {
    LibraryUpload.PENDING: "Kutubxonaga yuklanmoqda",
    LibraryUpload.FAILED: "Kutubxonaga yuklanmadi",
}


class TextMode(Choices):
    SHARED = "shared"
    EACH = "each"


TEXT_MODE_LABELS = {
    TextMode.SHARED: "Hammasiga bitta",
    TextMode.EACH: "Har biriga alohida",
}


class CreativeKind(Choices):
    LINK = "link"
    VIDEO = "video"
    POST = "post"


CREATIVE_KIND_LABELS = {
    CreativeKind.LINK: "Rasm va havola",
    CreativeKind.VIDEO: "Video",
    CreativeKind.POST: "Sahifa posti",
}
ALLOWED_IMAGE_TYPES = ("jpg", "jpeg", "png", "webp")
ALLOWED_VIDEO_TYPES = ("mp4", "mov")
ALLOWED_UPLOAD_TYPES = ALLOWED_IMAGE_TYPES + ALLOWED_VIDEO_TYPES
MAX_IMAGE_MB = 30
MAX_VIDEO_MB = 200
MIN_IMAGE_SIDE = 600
MEDIA_REFRESH_SECONDS = 60
MEDIA_STALE_SECONDS = 600
MEDIA_RECENT_STALE_SECONDS = 120
MEDIA_POLL_TRIES = 60
LIBRARY_POLL_TRIES = 200
LIBRARY_WORK_FRESH_MINUTES = 10
UPLOAD_RETRIES = 3
UPLOAD_RETRY_SECONDS = 20
STILL_POLL_SECONDS = 8
STILL_TRIES = 30
UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024
PARTIAL_UPLOAD_DIR = "launch-media/partial"
PARTIAL_UPLOAD_HOURS = 24
UPLOAD_ABANDONED_MINUTES = 30
UPLOAD_SWEEP_BATCH = 50
UPLOAD_SWEEP_SAMPLE = 10
MAX_BRIEF_CHARS = 1000
START_LEAD_MINUTES = 20
MAX_OPTIONS = 5
OPTIONS_PENDING = "options_pending"
OPTIONS_FIELD = "options-"
LABEL_FIELD = "label-"
TEXT_ANSWER_FIELD = "text-"
ROWS_FIELD = "rows"
NEW_ROW_PREFIX: Final = "new:"
MAX_CUSTOM_QUESTIONS = 15
CUSTOM_QUESTION_PREFIX: Final = "custom:"
LEAD_FORM_CHOICE: Final = "lead_form_choice"
LEAD_FORM_QUESTIONS: Final = "lead_form_questions"
LEAD_FORM_NAME: Final = "lead_form_name"
LEAD_FORM_ENDING: Final = "lead_form_ending"
ENDING_TITLE_MAX: Final = 60
ENDING_BODY_MAX: Final = 300
ENDING_BUTTON_MAX: Final = 30
ENDING_LABELS: Final = {
    "none": "Tugmasiz",
    "website": "Saytga o'tish",
    "telegram": "Telegram",
    "call": "Qo'ng'iroq qilish",
}
CAMPAIGN_TYPE: Final = "campaign_type"
CONVERSION_EVENT: Final = "conversion_event"
PIXEL_ID: Final = "pixel_id"
URL_TAGS: Final = "url_tags"
CALL_TO_ACTION: Final = "call_to_action"
ATTRIBUTION: Final = "attribution"
FREQUENCY_CAP: Final = "frequency_cap"
HIGHER_INTENT: Final = "higher_intent"
FORM_DEPTH: Final = "form_depth"
FORM_DEPTH_WANTED: Final = "form_depth_wanted"


class FormDepth(Choices):
    SHORT = "short"
    DEEP = "deep"


FORM_DEPTH_LABELS = {
    FormDepth.SHORT: "Ko'p va arzon",
    FormDepth.DEEP: "Kam, lekin sifatli",
}
FORM_DEPTH_LIMITS: Final[dict[str, int]] = {FormDepth.SHORT: 3, FormDepth.DEEP: 7}
ADVANCED_SECTION: Final = "advanced"
LEAD_FORM_NAME_MAX: Final = 255
GOAL_TEXT: Final = "goal_text"
GOAL_READING: Final = "goal_reading"
GOAL_TEXT_MIN: Final = 5
GOAL_TEXT_MAX: Final = 300
GOAL_PENDING: Final = "pending"
GOAL_FAILED: Final = "failed"
GOAL_BY_AI: Final = "ai"
GOAL_BY_PHRASE: Final = "phrase"
GOAL_BY_PICK: Final = "pick"
READING_V3: Final = 3
GOAL_POLL_MS: Final = 1500
MAX_GOAL_POLLS: Final = 20
GOAL_PENDING_SECONDS: Final = 120
GOAL_READINGS_PER_HOUR: Final = 30
CHAT_QUESTIONS: Final = "chat_questions"
CHAT_QUESTIONS_READING: Final = "chat_questions_reading"
CHAT_QUESTIONS_PENDING: Final = "pending"
CHAT_QUESTIONS_DONE: Final = "done"
CHAT_QUESTIONS_FAILED: Final = "failed"
CHAT_QUESTION_POLL_MS: Final = 1500
MAX_CHAT_QUESTION_POLLS: Final = 20
CHAT_QUESTION_SUGGESTIONS_PER_HOUR: Final = 30
GOAL_HINTS: Final[dict[str, Any]] = {
    "leads": "Odam formani to'ldiradi — ismi va raqami sizga keladi.",
    "messages": "Odam reklamani bosib, sizga yozadi.",
    "calls": "Odam reklamadagi tugmani bosib, sizga qo'ng'iroq qiladi.",
    "views": "Reklama ko'proq odamga ko'rsatiladi. Ariza kutilmaydi.",
    "traffic": "Odam reklamani bosib, saytingizga o'tadi.",
    "site_leads": "Odam saytingizga o'tib, ariza qoldiradi. Saytda Meta pikseli kerak.",
}
GOAL_PHRASES: Final[tuple[tuple[str, Any], ...]] = (
    ("leads", "Raqamini qoldirsin"),
    ("messages", "Instagram'da yozsin"),
    ("calls", "Menga qo'ng'iroq qilsin"),
)
MESSAGES_PHRASE_WITHOUT_INSTAGRAM: Final = "Menga yozsin"
GOAL_EXAMPLES: Final[dict[str, Any]] = {
    "auto": "Masalan: transport olmoqchi bo'lganlar telefon raqamini qoldirsin.",
    "beauty": "Masalan: mijozlar Instagram'da yozib, navbatga yozilsin.",
    "construction": "Masalan: ta'mir qilmoqchi bo'lganlar menga qo'ng'iroq qilsin.",
    "ecommerce": "Masalan: odamlar saytimizga kirib, mahsulotlarni ko'rsin.",
    "education": "Masalan: ingliz tili kursiga o'quvchi kerak, raqamini qoldirsin.",
    "fitness": "Masalan: zalga yozilmoqchi bo'lganlar raqamini qoldirsin.",
    "medical": "Masalan: bemorlar qabulga yozilish uchun qo'ng'iroq qilsin.",
    "real_estate": "Masalan: kvartira olmoqchi bo'lganlar raqamini qoldirsin.",
    "restaurant": "Masalan: joy band qilish uchun Instagram'da yozishsin.",
    "retail_store": "Masalan: do'konimizni ko'proq odam bilsin.",
    "services": "Masalan: xizmatga buyurtma berish uchun menga qo'ng'iroq qilsin.",
    "travel": "Masalan: umra safariga boradiganlar raqamini qoldirsin.",
}
GOAL_EXAMPLE_FALLBACK: Final = (
    "Masalan: mijozlar telefon raqamini qoldirsin. Yoki: Instagram'da yozishsin."
)
START_TODAY = "today"
START_TOMORROW = "tomorrow"
START_DAY_CHOICES: tuple[tuple[str, Any], ...] = (
    (START_TODAY, "Bugun"),
    (START_TOMORROW, "Ertaga"),
)
LAUNCH_NAME_MAX = 80
MAX_ADS_PER_CAMPAIGN = 6
DEFAULT_ADSETS_PER_CAMPAIGN = 5
PRIMARY_TEXT_MAX = 600
SAVED_FLAG = "saved"
MEDIA_STALE_MINUTES = 720
LAUNCH_PROGRESS: dict[str, int] = {
    LaunchStep.VALIDATE: 10,
    LaunchStep.IMAGE: 25,
    LaunchStep.CAMPAIGN: 45,
    LaunchStep.ADSET: 62,
    LaunchStep.FORM: 75,
    LaunchStep.CREATIVE: 88,
    LaunchStep.AD: 95,
}
BUILD_STAGES: dict[str, Any] = {
    LaunchStep.ANSWERS: "Javoblaringiz o'qilmoqda",
    LaunchStep.ASKING: "Auditoriya, matn va forma yozilmoqda",
    LaunchStep.LLM: "Taklif yig'ilmoqda",
}
BUILD_STAGES_DONE: dict[str, Any] = {
    LaunchStep.ANSWERS: "Javoblaringiz o'qildi",
    LaunchStep.ASKING: "Auditoriya, matn va forma yozildi",
    LaunchStep.LLM: "Taklif yig'ildi",
}
CREATE_STAGES: tuple[tuple[Any, Any], ...] = (
    ("Tekshirilmoqda", "Tekshirildi"),
    ("Reklama Meta'da yaratilmoqda", "Reklama Meta'da yaratildi"),
    ("Ishga tushirilmoqda", "Ishga tushdi"),
)
BUILD_STAGE_FALLBACK = "AI reklamani tayyorlayapti"
BUILD_NOTES: tuple[Any, ...] = (
    "Auditoriya tanlanmoqda",
    "Qiziqishlar saralanmoqda",
    "Reklama matni yozilmoqda",
    "Forma savollari tuzilmoqda",
)
BUILD_NOTE_SECONDS: Final = 5
WRITING_TIMEOUT_SECONDS: Final = 180
BUILD_PROGRESS: dict[str, tuple[int, int]] = {
    LaunchStep.ANSWERS: (5, 14),
    LaunchStep.ASKING: (15, 78),
    LaunchStep.LLM: (80, 98),
}
BUILD_STAGE_SECONDS: Final = 26
CREATION_STEPS: tuple[str, ...] = (
    LaunchStep.VALIDATE,
    LaunchStep.IMAGE,
    LaunchStep.CAMPAIGN,
    LaunchStep.ADSET,
    LaunchStep.FORM,
    LaunchStep.CREATIVE,
    LaunchStep.AD,
    LaunchStep.VERIFY,
)
HARMLESS_STEPS: tuple[str, ...] = (LaunchStep.FORM, LaunchStep.CREATIVE)
ROLLBACK_ORDER: tuple[str, ...] = (
    LaunchStep.AD,
    LaunchStep.CREATIVE,
    LaunchStep.ADSET,
    LaunchStep.CAMPAIGN,
)
STRANDED_SWEEP_DAYS = 7
STRANDED_SWEEP_COOLDOWN_MINUTES = 60
STRANDED_SWEEP_BATCH = 50
VIDEO_POLL_SECONDS = 5
VIDEO_POLL_ATTEMPTS = 24
STALLED_AFTER_MINUTES = 15
PREPARATION_NEEDS_FIXING: Final = frozenset(
    {"subscription_expired", "profile_incomplete", "free_proposals_used"}
)
LAUNCH_DRAFT_PROMPT: Final = "launch_draft"
FREE_PROPOSALS: Final = 3
LAUNCH_RELATED_TYPE = "campaign_launch"
LAUNCH_LOG_PREFIX = "launch"
LAUNCH_REF_MIRRORS: dict[str, str] = {
    LaunchStep.CAMPAIGN: "ads.Campaign",
    LaunchStep.ADSET: "ads.AdSet",
    LaunchStep.CREATIVE: "ads.AdCreative",
    LaunchStep.AD: "ads.Ad",
    LaunchStep.FORM: "leads.LeadForm",
}


class ManagedLevel(Choices):
    CAMPAIGN = "campaign"
    ADSET = "adset"
    AD = "ad"


MANAGED_LEVEL_LABELS = {
    ManagedLevel.CAMPAIGN: "Kampaniya",
    ManagedLevel.ADSET: "Guruh",
    ManagedLevel.AD: "Reklama",
}
MANAGED_MIRRORS: dict[str, str] = {
    ManagedLevel.CAMPAIGN: "ads.Campaign",
    ManagedLevel.ADSET: "ads.AdSet",
    ManagedLevel.AD: "ads.Ad",
}
MANAGED_ACCOUNT_PATH: dict[str, str] = {
    ManagedLevel.CAMPAIGN: "ad_account",
    ManagedLevel.ADSET: "campaign__ad_account",
    ManagedLevel.AD: "adset__campaign__ad_account",
}
PREVIEW_AD_FORMAT = "MOBILE_FEED_STANDARD"
PREVIEW_FRESH_MINUTES = 30
MAX_PREVIEW_POLLS = 10
PREVIEW_POLL_SECONDS = 2
MANAGE_LOG_PREFIX = "manage"
ACTION_STALE_MINUTES = 10
MAX_ACTION_POLLS = 15
ACTION_POLL_SECONDS = 2
ACTIONS_PER_CAMPAIGN = 10
META_SIDE_FAILURES: tuple[str, ...] = (
    "page_terms",
    "page_role",
    "account_action",
    "account_disabled",
    "payment_due",
    "payment_missing",
)
ACCOUNT_FAILURES: tuple[str, ...] = ("account_action", "account_disabled")
PAYMENT_FAILURES: tuple[str, ...] = ("payment_due", "payment_missing")
UNCHANGED_REFUSALS: tuple[str, ...] = (
    "refused",
    "bid_refused",
    "location_invalid",
    "location_overlap",
    "media_too_large",
    "media_foreign",
    "form_privacy_missing",
)


class EditSection(Choices):
    BUDGET = "budget"
    AUDIENCE = "audience"
    LIMITS = "limits"


EDIT_SECTION_LABELS = {
    EditSection.BUDGET: "Kunlik byudjet",
    EditSection.AUDIENCE: "Auditoriya",
    EditSection.LIMITS: "Muddat va chegara",
}
EDIT_SECTIONS: tuple[tuple[str, str], ...] = (
    (EditSection.BUDGET, "ads/partials/_edit_budget.html"),
    (EditSection.AUDIENCE, "ads/partials/_edit_audience.html"),
    (EditSection.LIMITS, "ads/partials/_edit_limits.html"),
)
LIST_POLL_SECONDS = 4


class Shown(Choices):
    RUNNING = "running"
    STOPPED = "stopped"
    ALL = "all"


SHOWN_LABELS = {
    Shown.RUNNING: "Ishlayotgan",
    Shown.STOPPED: "To'xtatilgan",
    Shown.ALL: "Hammasi",
}
DEFAULT_SHOWN: Final = Shown.RUNNING
CAMPAIGN_FILTERS_SESSION_KEY: Final = "ads:campaign_filters"


class SiteOutcome(Choices):
    OK = "ok"
    NOT_FOUND = "not_found"
    HTTP_ERROR = "http_error"
    NO_SUCH_HOST = "no_such_host"
    REFUSED = "refused"
    TIMEOUT = "timeout"
    TLS_ERROR = "tls_error"
    BLOCKED = "blocked"
    TOO_MANY_REDIRECTS = "too_many_redirects"
    UNREACHABLE = "unreachable"


SITE_OUTCOME_LABELS = {
    SiteOutcome.OK: "Ochildi",
    SiteOutcome.NOT_FOUND: "Sahifa topilmadi",
    SiteOutcome.HTTP_ERROR: "Sayt xato qaytardi",
    SiteOutcome.NO_SUCH_HOST: "Bunday sayt yo'q",
    SiteOutcome.REFUSED: "Sayt ulanishni rad etdi",
    SiteOutcome.TIMEOUT: "Sayt javob bermadi",
    SiteOutcome.TLS_ERROR: "Xavfsiz ulanish xatosi",
    SiteOutcome.BLOCKED: "Tekshirib bo'lmaydigan manzil",
    SiteOutcome.TOO_MANY_REDIRECTS: "Yo'naltirish tugamaydi",
    SiteOutcome.UNREACHABLE: "Saytga ulanib bo'lmadi",
}
MAX_SITES_PER_OWNER: Final = 20
SITE_CHECK_BUDGET_SECONDS: Final = 400
COST_CAP_LABEL: Final = "Bitta murojaat uchun eng ko'pi"


class GoogleGoal(Choices):
    VISITS = "visits"
    CALLS = "calls"


GOOGLE_GOAL_LABELS = {
    GoogleGoal.VISITS: "Saytga kirish",
    GoogleGoal.CALLS: "Qo'ng'iroq",
}
GOOGLE_KEYWORDS_MAX = 20
GOOGLE_NEGATIVES_MAX = 15
GOOGLE_PLACES_MAX = 10
GOOGLE_FAILURES: dict[str, Any] = {
    "subscription_expired": "Obuna muddati tugagan.",
    "profile_incomplete": "Google akkauntining biznes ma'lumotlarini to'ldiring.",
    "google_unreachable": "Google bilan bog'lanib bo'lmadi. Birozdan keyin qayta urinib ko'ring.",
    "ai_failed": "AI matn yoza olmadi. Qayta urinib ko'ring.",
    "phone": "Google telefon raqamini qabul qilmadi. Raqam saytingizda ko'rinib turishi kerak.",
    "policy": "Google matnni o'z qoidalariga zid deb topdi. Sarlavha va tavsiflarni o'zgartiring.",
    "busy": "Google hozir band. Bir daqiqadan keyin qayta bosing.",
    "connection": "Google ruxsati ishlamayapti. «Ulanishlar» sahifasida qayta ulang.",
    "google": "Google kampaniyani qabul qilmadi. Ma'lumotlarni tekshirib, qayta urinib ko'ring.",
}
LAPSE_DELETE_AFTER: Final = timedelta(days=3)
LAPSE_LAST_WARNING: Final = timedelta(hours=48)
LAPSE_MARK: Final = "lapse_hold"


class StopReason(Choices):
    ADS_MANAGER = "ads_manager"
    CARD_DECLINED = "card_declined"
    BALANCE_USED_UP = "balance_used_up"
    SPEND_CAP = "spend_cap"
    PAYMENT_GRACE = "payment_grace"
    PAYMENT_PENDING = "payment_pending"


STOP_REASON_LABELS = {
    StopReason.ADS_MANAGER: "Ads Manager'da o'chirildi",
    StopReason.CARD_DECLINED: "Kartadan pul yechilmadi",
    StopReason.BALANCE_USED_UP: "Balans tugadi",
    StopReason.SPEND_CAP: "Xarajat chegarasiga yetdi",
    StopReason.PAYMENT_GRACE: "To'lov o'tmadi, muhlat bor",
    StopReason.PAYMENT_PENDING: "To'lov kutilmoqda",
}
BLOCKED_STANDINGS: frozenset[str] = frozenset(
    {"payment_failed", "disabled_payment", "disabled", "closed"}
)
MONEY_STOPS: frozenset[str] = frozenset(
    {StopReason.CARD_DECLINED, StopReason.BALANCE_USED_UP, StopReason.SPEND_CAP}
)


# A launch these statuses hold may be sent to the provider.
STARTABLE: Final[tuple[str, ...]] = (
    str(LaunchStatus.READY),
    str(LaunchStatus.ROLLED_BACK),
    str(LaunchStatus.FAILED),
)
