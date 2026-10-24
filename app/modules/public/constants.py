from dataclasses import dataclass
from datetime import date
from typing import Final

from app.common.choices import Choices

Text = str | str


class DeletionRequestSource(Choices):
    WEB_FORM = "web_form"
    META_CALLBACK = "meta_callback"


DELETION_REQUEST_SOURCE_LABELS = {
    DeletionRequestSource.WEB_FORM: "Sayt formasi",
    DeletionRequestSource.META_CALLBACK: "Meta so'rovi",
}


class DeletionRequestStatus(Choices):
    RECEIVED = "received"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REJECTED = "rejected"


DELETION_REQUEST_STATUS_LABELS = {
    DeletionRequestStatus.RECEIVED: "Qabul qilindi",
    DeletionRequestStatus.IN_PROGRESS: "Bajarilmoqda",
    DeletionRequestStatus.COMPLETED: "Bajarildi",
    DeletionRequestStatus.REJECTED: "Rad etildi",
}
DELETION_SLA_DAYS: Final = 30
CONFIRMATION_CODE_BYTES: Final = 12
CONSULT_PER_ADDRESS: Final = 5
CONSULT_WINDOW_SECONDS: Final = 60 * 60
CONSULT_SENT_KEY: Final = "public.consult_sent"
TESTIMONIAL_UPLOAD_DIR: Final = "testimonials/"
TESTIMONIAL_IMAGE_EXTENSIONS: Final = ["jpg", "jpeg", "png", "webp"]
TESTIMONIAL_VIDEO_EXTENSIONS: Final = ["mp4", "webm"]
TESTIMONIAL_AUDIO_EXTENSIONS: Final = [
    "mp3",
    "m4a",
    "aac",
    "ogg",
    "oga",
    "opus",
    "wav",
    "webm",
]
TESTIMONIAL_TEXT_MAX: Final = 3000


class TestimonialKind(Choices):
    __test__ = False
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    TEXT = "text"


TESTIMONIAL_KIND_LABELS = {
    TestimonialKind.IMAGE: "Rasm",
    TestimonialKind.VIDEO: "Video",
    TestimonialKind.AUDIO: "Audio",
    TestimonialKind.TEXT: "Matn",
}
TESTIMONIAL_SECONDS_PER_CARD: Final = 6
TESTIMONIAL_MIN_SET: Final = 8
LEGAL_UPDATED_AT: Final = date(2026, 9, 21)
ADVERTISER_POLICY_UPDATED_AT: Final = date(2026, 9, 14)


@dataclass(frozen=True, slots=True)
class Card:
    icon: str
    title: Text
    body: Text


@dataclass(frozen=True, slots=True)
class Question:
    question: Text
    answer: Text


PROBLEMS: Final[tuple[Card, ...]] = (
    Card(
        icon="wallet",
        title="Qimmat mutaxassis",
        body="Tajribali targetolog oyiga 5-10 mln so'm oladi.",
    ),
    Card(
        icon="file-text",
        title="Tushunarsiz hisobotlar",
        body="Hisobot - bir nechta skrinshot. Pul qayerga ketgani noma'lum.",
    ),
    Card(
        icon="search",
        title="Yaxshisini topish qiyin",
        body="Kuchlilari band, kuchsizlari byudjetni yeydi.",
    ),
)
STEPS: Final[tuple[Card, ...]] = (
    Card(
        icon="facebook",
        title="Meta akkauntni ulang",
        body="Reklama kabineti va Facebook sahifangizni ulaysiz. Ruxsatni istalgan payt bekor qilasiz.",
    ),
    Card(
        icon="message-square",
        title="Bir necha savolga javob bering",
        body="Nima sotasiz, qayerda va kuniga qancha - oddiy tilda.",
    ),
    Card(
        icon="sparkles",
        title="AI reklamani tayyorlaydi",
        body="Ishga tushishidan oldin hammasini ko'rib, tasdiqlaysiz.",
    ),
    Card(
        icon="inbox",
        title="Arizalar keladi",
        body="Lidlar kabinetga darhol tushadi. AI natijani har kuni kuzatadi.",
    ),
)
FEATURES: Final[tuple[Card, ...]] = (
    Card(
        icon="target",
        title="Auditoriyani avtomatik tanlaydi",
        body="Biznesingiz va maqsadingizga qarab yosh, hudud va qiziqishlar tanlanadi.",
    ),
    Card(
        icon="gauge",
        title="Reklamani boshqaradi",
        body="Ishga tushiradi, to'xtatadi va byudjetni yaxshi natijaga o'tkazishni taklif qiladi. Har bir o'zgarish jurnalga yoziladi.",
    ),
    Card(
        icon="inbox",
        title="Arizalar real vaqtda",
        body="Facebook va Instagram formalaridan ism, telefon va javoblar - bitta joyda. Excelga yuklab olasiz.",
    ),
    Card(
        icon="send",
        title="Telegram xabarnomalar",
        body="Kunlik hisobot, rad etilgan reklama va natijasiz sarf haqida darhol xabar.",
    ),
    Card(
        icon="trending-up",
        title="Natijalar raqamlarda",
        body="Ariza narxi, eng yaxshi reklamalar va sarf - har kuni. Har hafta hisobot.",
    ),
)
QUESTIONS: Final[tuple[Question, ...]] = (
    Question(
        question="Meta reklama kabineti kerakmi?",
        answer="Ha. Facebook sahifangiz bo'lsa, kabinetni bepul ochish mumkin. Sahifa bo'lmasa, avval uni yaratish kerak.",
    ),
    Question(
        question="Reklama byudjetini kimga to'layman?",
        answer="To'g'ridan-to'g'ri Meta'ga, o'z reklama kabinetingiz orqali. Biz byudjetingizni qabul qilmaymiz va saqlamaymiz.",
    ),
    Question(
        question="Ma'lumotlarimni kim ko'radi?",
        answer="Faqat siz. Qo'llab-quvvatlashga murojaat qilsangiz, xodimlarimiz faqat kerakli qismini ko'radi.",
    ),
    Question(
        question="Obunani bekor qilsam, arizalarim nima bo'ladi?",
        answer="Avval ularni faylga yuklab oling. Arizalar obuna tugaganidan keyin 90 kun saqlanadi, so'ng o'chiriladi. Darhol o'chirishni ham so'rashingiz mumkin.",
    ),
    Question(
        question="Reklamani to'liq nazorat qila olamanmi?",
        answer="Ha. Istalgan reklamani to'xtatish, kunlik byudjetni o'zgartirish yoki o'chirish mumkin.",
    ),
    Question(
        question="Natija qachon ko'rinadi?",
        answer="Meta reklamani kimga ko'rsatishni o'rganadi: dastlabki ikki hafta - sozlash davri.",
    ),
    Question(
        question="Qaysi bizneslarga mos?",
        answer="Xizmatlar, ta'lim, tibbiyot, ko'chmas mulk, qurilish materiallari, avtosalon va go'zallik salonlari. Onlayn do'konlar - ariza formasi orqali.",
    ),
)


@dataclass(frozen=True, slots=True)
class TargetingTag:
    label: Text | None
    value: Text


TARGETING_SAMPLE: Final[tuple[TargetingTag, ...]] = (
    TargetingTag(label="Yosh", value="25-44"),
    TargetingTag(label="Shahar", value="Toshkent"),
    TargetingTag(label=None, value="Samarqand"),
    TargetingTag(label="Qiziqish", value="Ta'mirlash"),
    TargetingTag(label=None, value="Ko'chmas mulk"),
    TargetingTag(label=None, value="Uy jihozlari"),
    TargetingTag(label=None, value="Sayohat"),
)
TIER_INCLUDES: Final[tuple[Text, ...]] = (
    "AI targeting va kundalik optimizatsiya",
    "Mijozlar bazasi va Excel eksport",
    "Telegram bildirishnomalari",
    "Haftalik hisobot va tavsiyalar",
)
