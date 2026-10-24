from typing import Final

from app.common.choices import Choices
from app.common.llm import Account


class MontageStatus(Choices):
    QUEUED = "queued"
    READING = "reading"
    PLANNING = "planning"
    RENDERING = "rendering"
    DONE = "done"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


MONTAGE_STATUS_LABELS = {
    MontageStatus.QUEUED: "Navbatda",
    MontageStatus.READING: "Video o'qilmoqda",
    MontageStatus.PLANNING: "AI montaj rejasini tuzmoqda",
    MontageStatus.RENDERING: "Video yig'ilmoqda",
    MontageStatus.DONE: "Tayyor",
    MontageStatus.NEEDS_REVIEW: "Tekshirish kerak",
    MontageStatus.FAILED: "Bo'lmadi",
}
OPEN_STATUSES: Final = frozenset(
    {
        MontageStatus.QUEUED,
        MontageStatus.READING,
        MontageStatus.PLANNING,
        MontageStatus.RENDERING,
    }
)
FINISHED_STATUSES: Final = frozenset({MontageStatus.DONE, MontageStatus.NEEDS_REVIEW})
STEPS: Final = (
    ((MontageStatus.QUEUED, MontageStatus.READING), "Ovoz tozalanmoqda"),
    ((MontageStatus.PLANNING,), "AI reja tuzmoqda"),
    ((MontageStatus.RENDERING,), "Video yig'ilmoqda"),
    ((MontageStatus.DONE, MontageStatus.NEEDS_REVIEW), "Tayyor"),
)


class AspectRatio(Choices):
    VERTICAL = "9:16"
    SQUARE = "1:1"
    PORTRAIT = "4:5"
    WIDE = "16:9"


ASPECT_RATIO_LABELS = {
    AspectRatio.VERTICAL: "Tik — Reels, Stories, TikTok",
    AspectRatio.SQUARE: "Kvadrat — lenta",
    AspectRatio.PORTRAIT: "4:5 — Instagram lentasi",
    AspectRatio.WIDE: "Yotiq — YouTube, Telegram",
}


class Pace(Choices):
    DYNAMIC = "dynamic"
    CALM = "calm"


PACE_LABELS = {Pace.DYNAMIC: "Dinamik — tez almashadi", Pace.CALM: "Sokin — bemalol"}


class Sound(Choices):
    CLEAN = "clean"
    LEVEL = "level"


SOUND_LABELS = {Sound.CLEAN: "Shovqinni tozalash", Sound.LEVEL: "Asl ovoz"}


class Subtitles(Choices):
    ON = "on"
    OFF = "off"


SUBTITLES_LABELS = {Subtitles.ON: "Subtitr bilan", Subtitles.OFF: "Subtitrsiz"}
LLM_ACCOUNT: Final[Account] = "montage"


class Failure(Choices):
    NOT_A_VIDEO = "not_a_video"
    TOO_LONG = "too_long"
    NOTHING_KEPT = "nothing_kept"
    SERVICE = "service"
    NOT_SET_UP = "not_set_up"
    TIMED_OUT = "timed_out"
    QA = "qa"
    AI_BUDGET = "ai_budget"


FAILURE_LABELS = {
    Failure.NOT_A_VIDEO: "Fayl video sifatida o'qilmadi.",
    Failure.TOO_LONG: "Video juda uzun. 10 daqiqagacha video yuklang.",
    Failure.NOTHING_KEPT: "AI videodan saqlab qolishga arziydigan bo'lak topmadi.",
    Failure.SERVICE: "Montaj xizmati hozir javob bermadi. Birozdan keyin qayta urinib ko'ring.",
    Failure.NOT_SET_UP: "Montaj hali sozlanmagan.",
    Failure.TIMED_OUT: "Montaj juda uzoq cho'zildi va to'xtatildi.",
    Failure.QA: "Montaj sifat tekshiruvidan o'tmadi.",
    Failure.AI_BUDGET: "Montaj AI byudjeti tugadi.",
}
TARGET_SECONDS: Final = (15, 30, 60)
DEFAULT_TARGET_SECONDS: Final = 30
CTA_MAX_CHARS: Final = 80
BRAND_NAME_MAX_CHARS: Final = 60
DESCRIPTION_MAX_CHARS: Final = 300
TAGLINE_MAX_CHARS: Final = 80
CTA_TEXT_MAX_CHARS: Final = 40
HANDLE_MAX_CHARS: Final = 32
CTA_PHONE_MAX_CHARS: Final = 20
KEYTERMS_MAX: Final = 20
KEYTERM_MAX_CHARS: Final = 40
LOGO_MAX_MB: Final = 5
LOGO_EXTENSIONS: Final = ("png", "jpg", "jpeg", "webp", "svg")
RENDER_LOGO_SIDE: Final = 256
LOGO_PROMPT: Final = "brand_logo"
LOGO_ANALYSIS_VERSION: Final = "v2"
LOGO_RELATED_TYPE: Final = "montage_brand_kit"


class FontPreset(Choices):
    BOLD = "bold"
    MODERN = "modern"
    ELEGANT = "elegant"
    FRIENDLY = "friendly"


FONT_PRESET_LABELS = {
    FontPreset.BOLD: "Qalin — Montserrat",
    FontPreset.MODERN: "Zamonaviy — Inter",
    FontPreset.ELEGANT: "Nafis — Noto Serif",
    FontPreset.FRIENDLY: "Yumshoq — Nunito",
}


class LogoGround(Choices):
    CLEAR = "clear"
    REMOVED = "removed"
    SOLID = "solid"


LOGO_GROUND_LABELS = {
    LogoGround.CLEAR: "Shaffof fon",
    LogoGround.REMOVED: "Oddiy fon olib tashlangan",
    LogoGround.SOLID: "Fon qolgan",
}


class LogoAnalysisStatus(Choices):
    NONE = "none"
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


LOGO_ANALYSIS_STATUS_LABELS = {
    LogoAnalysisStatus.NONE: "Logo yo'q",
    LogoAnalysisStatus.PENDING: "Tahlil qilinmoqda",
    LogoAnalysisStatus.DONE: "Tahlil qilindi",
    LogoAnalysisStatus.FAILED: "Tahlil bo'lmadi",
}
BRIEF_MAX_CHARS: Final = 500
MAX_SOURCE_SECONDS: Final = 600
MAX_UPLOAD_MB: Final = 200
ACCEPTED_EXTENSIONS: Final = ("mp4", "mov", "m4v", "webm")
POLL_SECONDS: Final = 5
GIVE_UP_MINUTES: Final = 30
STEP_SOFT_LIMIT_SECONDS: Final = 19 * 60
STEP_HARD_LIMIT_SECONDS: Final = 20 * 60
MAX_STEP_ATTEMPTS: Final = 2
MAX_BUSY_LOOKS: Final = 6
MAX_BUSY_WAIT_SECONDS: Final = 300
REVIVE_AFTER_MINUTES: Final = 21
REVIVE_BATCH: Final = 50
FRAME_WIDTH: Final = 360
ACTION_TARGET_PROVIDER: Final = "montage"
ACTION_TARGET_LEVEL: Final = "montage"
LLM_RELATED_TYPE: Final = "montage"


class VideoLanguage(Choices):
    UZ = "uz"
    RU = "ru"


VIDEO_LANGUAGE_LABELS = {VideoLanguage.UZ: "O'zbekcha", VideoLanguage.RU: "Ruscha"}
SPEECH_LANGUAGES: Final[dict[str, str]] = {"uz": "uzb", "ru": "rus"}
LANGUAGE_NAMES: Final[dict[str, str]] = {"uz": "Uzbek", "ru": "Russian"}
