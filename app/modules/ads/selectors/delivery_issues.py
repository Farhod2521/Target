"""Why Meta will not run an advert, when its review was not the reason.

``WITH_ISSUES`` shares the word "rejected" with a refused review, but the fault
is usually elsewhere: the account is closing, an audience is gone, the Page hit
its limit. New words fix none of those, so each known code says where the fault
is and what to press. Written here and never by the AI; a code not listed keeps
Meta's words and gets a written answer.

The codes were read from the production copy on 2026-11-01: ``ads.issues``.
"""

from dataclasses import dataclass
from typing import Final

from app.modules.ads.selectors.failures import (
    ACCOUNT_QUALITY,
    ADS_MANAGER,
    BILLING,
    RECONNECT,
)

SWAP: Final = "swap"
AUDIENCE: Final = "audience"
CAMPAIGNS: Final = "campaigns"
RESEND: Final = "Reklamani saqlang: Meta uni qayta ko'rib chiqadi."


@dataclass(frozen=True, slots=True)
class Trouble:
    """One reason an advert does not run, written once."""

    title: str
    cause: str
    steps: tuple[str, ...]
    fix: str = ""


_ACCOUNT_CLOSING: Final = Trouble(
    title="Reklama akkaunti yopilmoqda",
    cause="Meta bu akkauntni yopish jarayoniga qo'ygan, shuning uchun reklamalar o'chirilgan. Matn yoki rasmni o'zgartirish yordam bermaydi.",
    steps=(
        "«Account Quality» sahifasini oching va akkauntingizni tanlang.",
        "Meta ko'rsatgan muammoni hal qiling yoki qayta ko'rib chiqishni so'rang.",
        "Shoshilinch bo'lsa, «Ulanishlar» sahifasida boshqa reklama akkauntini tanlang.",
    ),
    fix=ACCOUNT_QUALITY,
)
_ACCOUNT_OFF: Final = Trouble(
    title="Reklama akkaunti faol emas",
    cause="Meta bu akkauntni o'chirgan. Faol bo'lmagan akkauntda reklama yaratib ham, o'zgartirib ham bo'lmaydi.",
    steps=(
        "«Account Quality» sahifasida cheklov sababini o'qing.",
        "Xato deb hisoblasangiz, «Request review» (Ko'rib chiqishni so'rash) ni bosing.",
        "Shoshilinch bo'lsa, «Ulanishlar» sahifasida boshqa reklama akkauntini tanlang.",
    ),
    fix=ACCOUNT_QUALITY,
)
_ACCOUNT_EMPTY: Final = Trouble(
    title="Reklama akkauntida faol foydalanuvchi yo'q",
    cause="Bu akkauntga biriktirilgan faol odam qolmagan, shuning uchun Meta reklamalarni to'xtatgan.",
    steps=(
        "business.facebook.com da «Settings» → «Accounts» → «Ad accounts» ga kiring.",
        "Akkauntga o'zingizni yoki faol xodimni qo'shing.",
        "Keyin reklamani qayta yoqing.",
    ),
    fix=ADS_MANAGER,
)
_UNPAID: Final = Trouble(
    title="Reklama akkauntida to'lanmagan qarz bor",
    cause="Oxirgi to'lov o'tmagan. Qarz yopilmaguncha Meta reklamani ishlatmaydi. Matn yoki rasmni o'zgartirish yordam bermaydi.",
    steps=(
        "To'lov sahifasini oching.",
        "Qarzni to'lang yoki yangi karta qo'shing.",
        "To'lov o'tgach, reklama o'zi tiklanadi. Tiklanmasa, uni qayta yoqing.",
    ),
    fix=BILLING,
)
_NO_CARD: Final = Trouble(
    title="Reklama akkauntida to'lov usuli yo'q",
    cause="Meta bu akkauntda ishlaydigan karta topmadi. Matn yoki rasmni o'zgartirish yordam bermaydi.",
    steps=(
        "To'lov sahifasini oching.",
        "Karta qo'shing yoki karta ma'lumotlarini yangilang.",
        "Keyin reklamani qayta yoqing.",
    ),
    fix=BILLING,
)
_CONFIRM: Final = Trouble(
    title="Meta hisobingizni tasdiqlashni kutmoqda",
    cause="Meta profilingizga begona kirishga urinish bo'lgan deb hisoblaydi. Tasdiqlamaguningizcha reklamani o'zgartirib bo'lmaydi.",
    steps=(
        "Ads Manager'ga reklama akkaunti egasining profili bilan kiring.",
        "Meta so'ragan tasdiqlashni oxirigacha bajaring.",
        "Keyin reklamani qayta yoqing.",
    ),
    fix=ADS_MANAGER,
)
_COMPROMISED: Final = Trouble(
    title="Meta reklamani xavfsizlik uchun to'xtatgan",
    cause="Meta bu reklamaga buzilgan profil yoki to'lov cheklovi ta'sir qilgan bo'lishi mumkin deb hisoblaydi.",
    steps=(
        "Ads Manager'da akkauntda notanish odam yoki o'zgarish yo'qligini tekshiring.",
        "Hammasi joyida bo'lsa, reklamani qayta yoqing.",
    ),
    fix=ADS_MANAGER,
)
_AUDIENCE_GONE: Final = Trouble(
    title="Auditoriya endi mavjud emas",
    cause="Reklama guruhidagi auditoriya o'chirilgan yoki yaroqsiz bo'lib qolgan, shuning uchun Meta guruhni to'xtatgan.",
    steps=(
        "Kampaniya tahririni oching.",
        "Yaroqsiz auditoriyani olib tashlang yoki boshqasini tanlang.",
        "Saqlang va guruhni qayta yoqing.",
    ),
    fix=AUDIENCE,
)
_INSTAGRAM_ACCESS: Final = Trouble(
    title="Reklama akkauntida Instagram'ga kirish yo'q",
    cause="Reklama akkauntiga bu Instagram profilidan foydalanishga ruxsat berilmagan. Matn yoki rasmni o'zgartirish yordam bermaydi.",
    steps=(
        "business.facebook.com da «Settings» → «Accounts» → «Instagram accounts» ga kiring.",
        "Instagram profilini tanlang va unga shu reklama akkauntini biriktiring.",
        "Keyin reklamani qayta yoqing.",
    ),
    fix=ADS_MANAGER,
)
_INSTAGRAM_PAGE: Final = Trouble(
    title="Instagram profili sahifaga ulanmagan",
    cause="Reklamadagi Instagram profili shu Facebook sahifasiga ulanmagan.",
    steps=(
        "Facebook sahifangiz sozlamalarida Instagram profilini ulang.",
        "«Ulanishlar» sahifasida sahifalarni yangilang.",
        "Keyin reklamani qayta yoqing.",
    ),
    fix=RECONNECT,
)
_AD_LIMIT: Final = Trouble(
    title="Sahifaning reklama limiti tugagan",
    cause="Bu sahifada bir vaqtda ishlaydigan reklamalar soni Meta chegarasiga yetgan.",
    steps=(
        "Reklamalar ro'yxatini oching.",
        "Keraksiz reklamalarni to'xtating.",
        "Meta 24 soatgacha kutishi mumkin, keyin reklama o'zi ishga tushadi.",
    ),
    fix=CAMPAIGNS,
)
_PAGE_RESTRICTED: Final = Trouble(
    title="Sahifaga reklama berish cheklangan",
    cause="Meta bu sahifa nomidan reklama berishni cheklagan. Bu cheklovni faqat Meta olib tashlaydi.",
    steps=(
        "«Account Quality» sahifasida sahifangizni tanlang va sababini o'qing.",
        "Xato deb hisoblasangiz, «Request review» (Ko'rib chiqishni so'rash) ni bosing.",
        "Shoshilinch bo'lsa, «Ulanishlar» sahifasida boshqa sahifani tanlang.",
    ),
    fix=ACCOUNT_QUALITY,
)
_PAGE_HIDDEN: Final = Trouble(
    title="Facebook sahifasi chop etilmagan",
    cause="Reklama chop etilmagan sahifani ko'rsatmoqda, shuning uchun Meta uni ishlatmaydi.",
    steps=(
        "Facebook sahifangiz sozlamalarini oching.",
        "Sahifani chop eting (Publish).",
        "Keyin reklamani qayta yoqing.",
    ),
)
_WAITS_APPROVAL: Final = Trouble(
    title="Reklama tasdiqni kutmoqda",
    cause="Bu rad etish emas. Reklama chop etilgan, lekin Meta uni akkauntning ishonchli odami yoki biznes administratori tasdiqlashini kutmoqda.",
    steps=(
        "Reklamani o'zgartirmang.",
        "Biznes administratoridan Ads Manager'da reklamani tasdiqlashni so'rang.",
    ),
    fix=ADS_MANAGER,
)
_WAITS_PARTNER: Final = Trouble(
    title="Reklama hamkor ruxsatini kutmoqda",
    cause="Hamkorlik reklamasi uchun Instagram profil egasi ruxsat berishi kerak. Meta unga Instagram orqali so'rov yuboradi.",
    steps=(
        "Profil egasidan Instagram xabarlaridagi so'rovni tasdiqlashni so'rang.",
        "Tasdiqlangach, reklama o'zi ishga tushadi.",
    ),
)
_NOT_DELIVERING: Final = Trouble(
    title="Reklama ko'rsatilmayapti",
    cause="Meta bu guruh sozlamalarida reklamani ko'rsata olmayapti.",
    steps=(
        "Kampaniyada boshqa sozlamalar bilan yangi reklama guruhi yarating.",
        "Eski guruhni to'xtating.",
    ),
    fix=CAMPAIGNS,
)
_REVIEW_REFUSED: Final = Trouble(
    title="Meta reklamani rad etdi",
    cause="Reklama oxirgi tekshiruvdan o'tmagan va o'chirilgan. Uni shu holicha yoqib bo'lmaydi.",
    steps=("Matn va rasmni o'zgartiring.", RESEND),
    fix=SWAP,
)
_MEDIA_UNFIT: Final = Trouble(
    title="Rasm yoki video talabga mos emas",
    cause="Meta bu faylni tanlangan joylashuvda ko'rsata olmaydi: o'lchami yoki formati mos emas. Matnni o'zgartirish yordam bermaydi.",
    steps=(
        "Eni kamida 500 piksel bo'lgan boshqa rasm yoki video tanlang.",
        RESEND,
    ),
    fix=SWAP,
)
_MEDIA_GONE: Final = Trouble(
    title="Rasm yoki video topilmadi",
    cause="Reklamadagi fayl o'chirilgan yoki undan foydalanishga ruxsat yo'q.",
    steps=("Boshqa rasm yoki video tanlang.", RESEND),
    fix=SWAP,
)
_POST_GONE: Final = Trouble(
    title="Reklamadagi post mavjud emas",
    cause="Reklama ko'rsatayotgan post o'chirilgan, arxivlangan yoki yashirilgan.",
    steps=(
        "Postni qayta oching yoki guruhga boshqa post, rasm yoki video bilan yangi reklama qo'shing.",
        "Eski reklamani o'chiring.",
    ),
)
_BAD_LINK: Final = Trouble(
    title="Reklamadagi havola yaroqsiz",
    cause="Meta bu manzilni tashqi sayt deb qabul qilmaydi.",
    steps=("Havolani o'z saytingiz manziliga almashtiring.", RESEND),
    fix=SWAP,
)
_META_FAULT: Final = Trouble(
    title="Meta reklamani qayta ishlay olmadi",
    cause="Meta tomonida qayta ishlash xatosi bo'lgan. Reklamangizda aniq xato ko'rsatilmagan.",
    steps=(
        "Reklamani o'zgartirmasdan qayta saqlang.",
        "Takrorlansa, supportga yozing.",
    ),
    fix=SWAP,
)

TROUBLES: Final[dict[str, Trouble]] = {
    "2490471": _ACCOUNT_CLOSING,
    "1885316": _ACCOUNT_OFF,
    "2490413": _ACCOUNT_EMPTY,
    "1359008": _UNPAID,
    "1487220": _NO_CARD,
    "3858385": _CONFIRM,
    "2490455": _COMPROMISED,
    "1359208": _AUDIENCE_GONE,
    "2446446": _AUDIENCE_GONE,
    "1815199": _INSTAGRAM_ACCESS,
    "2490446": _INSTAGRAM_ACCESS,
    "1815202": _INSTAGRAM_PAGE,
    "3867097": _INSTAGRAM_PAGE,
    "3253001": _AD_LIMIT,
    "1404167": _PAGE_RESTRICTED,
    "3867089": _PAGE_RESTRICTED,
    "2446095": _PAGE_HIDDEN,
    "2446984": _WAITS_APPROVAL,
    "3867026": _WAITS_PARTNER,
    "4469003": _NOT_DELIVERING,
    "2490468": _REVIEW_REFUSED,
    "2643046": _MEDIA_UNFIT,
    "2875006": _MEDIA_UNFIT,
    "1443078": _MEDIA_UNFIT,
    "2446429": _MEDIA_UNFIT,
    "2238239": _MEDIA_UNFIT,
    "2238167": _MEDIA_UNFIT,
    "1772071": _MEDIA_UNFIT,
    "2446386": _MEDIA_GONE,
    "2446289": _MEDIA_GONE,
    "3907143": _MEDIA_GONE,
    "1885180": _POST_GONE,
    "1885557": _POST_GONE,
    "3843076": _POST_GONE,
    "3843077": _POST_GONE,
    "3843078": _POST_GONE,
    "3843042": _POST_GONE,
    "1815765": _BAD_LINK,
    "2490557": _META_FAULT,
    "2643001": _META_FAULT,
    "2643036": _META_FAULT,
    "2643053": _META_FAULT,
    "2643059": _META_FAULT,
    "2643069": _META_FAULT,
    "2643200": _META_FAULT,
    "1815479": _META_FAULT,
    "2142030": _META_FAULT,
}


__all__ = ["AUDIENCE", "CAMPAIGNS", "RESEND", "SWAP", "TROUBLES", "Trouble"]
