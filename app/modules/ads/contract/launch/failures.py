"""Why the network refused a launch, and what to press: the help base's ready answers.

One answer per code, written here and never by the AI (copied from the
screens' catalog, as the browser held it in ``live/launch-map.ts``). A code
the help base does not know keeps what the network wrote for the advertiser,
never the developer's sentence, which is a log line.
"""

from dataclasses import dataclass
from typing import Any, Final

from app.common.contract import Refusal, RefusalFix
from app.modules.ads.contract.launch.shapes import NoticeTarget
from app.modules.ads.contract.launch.words import LaunchErrorCode, failure_code_of

RETRY = "«Reklamani yaratib bo'lmadi» sahifasiga qaytib, «Qayta urinish» ni bosing."
ACCOUNT_QUALITY = "https://www.facebook.com/accountquality/"
BILLING = "https://business.facebook.com/billing_hub/payment_methods"


@dataclass(frozen=True)
class Context:
    ad: int | None
    """The refused advert, 1-based; None when it was not one advert."""
    page: str
    budget: str
    min: str
    detail: str
    """What the network wrote for the advertiser, for a code the help base does not know."""
    terms_url: str = ""
    manager_url: str = ""
    billing_url: str = ""


@dataclass(frozen=True)
class Ready:
    """A refusal with one way out, written once."""

    title: str
    hint: str
    cause: str
    steps: tuple[str, ...]
    fix: str
    to: NoticeTarget
    href: str = ""
    """Which of the context's own addresses the button opens."""


READY: Final[dict[LaunchErrorCode, Ready]] = {
    "page_terms": Ready(
        title="Sahifa Meta'ning lid shartlarini qabul qilmagan",
        hint="Lid shartlarini qabul qiling",
        cause="Lid formali reklama uchun Meta sahifadan o'z shartlarini bir marta qabul qilishni so'raydi. Qabul qilinmaguncha reklama yaratilmaydi.",
        steps=(
            "«Shartlarni ochish» tugmasini bosing — Meta sahifasi ochiladi. Sahifa administratori akkaunti bilan kiring.",
            "Shartlarni o'qib, «Accept» (Qabul qilish) ni bosing.",
            RETRY,
        ),
        fix="Shartlarni ochish",
        to="connections",
        href="terms_url",
    ),
    "page_role": Ready(
        title="Facebook sahifasida huquqingiz yetarli emas",
        hint="Sahifada to'liq huquq oling",
        cause="Ulangan Facebook profili bu sahifa nomidan reklama bera olmaydi: unda kerakli huquq yo'q.",
        steps=(
            "business.facebook.com da «Settings» → «Accounts» → «Pages» ga kiring va sahifani tanlang.",
            "Ulangan profilingizga sahifa ustidan to'liq boshqaruv huquqini bering.",
            "«Ulanishlar» sahifasida Meta qatoridagi «Qayta ulash» ni bosing.",
            RETRY,
        ),
        fix="Ulanishlarni ochish",
        to="connections",
    ),
    "account_action": Ready(
        title="Meta hisobingizni tasdiqlashni kutmoqda",
        hint="Ads Manager'da tasdiqlang",
        cause="Meta sizdan xavfsizlik tekshiruvi yoki shaxsni tasdiqlashni so'ragan. Bu tugamaguncha hech qanday reklama yaratilmaydi.",
        steps=(
            "«Ads Manager'ni ochish» tugmasini bosing va reklama hisobi egasining Facebook akkaunti bilan kiring.",
            "Yuqorida chiqqan so'rovni oching va Meta so'ragan tasdiqlashni oxirigacha bajaring.",
            RETRY,
        ),
        fix="Ads Manager'ni ochish",
        to="connections",
        href="manager_url",
    ),
    "account_disabled": Ready(
        title="Reklama akkaunti cheklangan",
        hint="Account Quality'da holatni ko'ring",
        cause="Meta bu reklama akkauntini o'chirgan yoki cheklagan. Bu cheklovni faqat Meta olib tashlaydi.",
        steps=(
            "«Account Quality'ni ochish» tugmasini bosing va akkauntingizni tanlang.",
            "Cheklov sababini o'qing. Xato deb hisoblasangiz, «Request review» (Ko'rib chiqishni so'rash) ni bosing.",
            "Shoshilinch bo'lsa, «Ulanishlar» sahifasida boshqa reklama akkauntini tanlang.",
            RETRY,
        ),
        fix="Account Quality'ni ochish",
        to="connections",
        href="account_quality",
    ),
    "location_invalid": Ready(
        title="Meta tanlangan joyni tanimadi",
        hint="Joylashuvni o'zgartiring",
        cause="Auditoriyadagi joylardan birini Meta tanimadi: u o'chirilgan yoki noto'g'ri belgilangan bo'lishi mumkin.",
        steps=(
            "«Joylashuvni tuzatish» tugmasini bosing.",
            "Joylarni tekshiring va tanilmaganini olib tashlang yoki qidiruvdan qayta tanlang.",
            "«Saqlash» ni bosing.",
            RETRY,
        ),
        fix="Joylashuvni tuzatish",
        to="geo",
    ),
    "location_overlap": Ready(
        title="Tanlangan joylar bir-birini qoplaydi",
        hint="Ortiqcha joyni olib tashlang",
        cause="Ikki joy bir hududni qoplaydi: masalan, shahar va u joylashgan viloyat. Meta bunday auditoriyani qabul qilmaydi.",
        steps=(
            "«Joylashuvni tuzatish» tugmasini bosing.",
            "Bir-birini qoplaydigan joylardan bittasini olib tashlang.",
            "«Saqlash» ni bosing.",
            RETRY,
        ),
        fix="Joylashuvni tuzatish",
        to="geo",
    ),
    "interest_retired": Ready(
        title="Meta qiziqishlardan birini olib tashlagan",
        hint="Qiziqishlarni ko'rib chiqing",
        cause="Auditoriyadagi qiziqishlardan biri endi Meta ro'yxatida yo'q. O'rnini bosadigan varianti bo'lsa, uni o'zimiz qo'ydik.",
        steps=(
            "«Qiziqishlarni ko'rish» tugmasini bosing va yangilangan ro'yxatni tekshiring.",
            RETRY,
        ),
        fix="Qiziqishlarni ko'rish",
        to="int",
    ),
    "form_privacy_missing": Ready(
        title="Formada maxfiylik siyosati havolasi yo'q",
        hint="Formani tuzating",
        cause="Tanlangan lid formasida maxfiylik siyosatiga havola yo'q. Meta bunday formali reklamani qabul qilmaydi.",
        steps=(
            "«Formani ochish» tugmasini bosing.",
            "Maxfiylik siyosati havolasi bor boshqa formani tanlang yoki yangisini yarating.",
            "«Saqlash» ni bosing.",
            RETRY,
        ),
        fix="Formani ochish",
        to="form",
    ),
    "media_missing": Ready(
        title="Rasm yoki video tanlanmagan",
        hint="Rasm yoki video tanlang",
        cause="Reklamada rasm yoki video yo'q.",
        steps=("«Rasmlarni ochish» tugmasini bosing va fayl tanlang.", RETRY),
        fix="Rasmlarni ochish",
        to="media",
    ),
    "media_unsupported": Ready(
        title="Meta bu faylni qabul qilmaydi",
        hint="Boshqa fayl tanlang",
        cause="Tanlangan fayl turini Meta reklamada qabul qilmaydi. Matnni o'zgartirish yordam bermaydi.",
        steps=(
            "«Rasmlarni ochish» tugmasini bosing.",
            "Faylni JPG, PNG yoki MP4 ko'rinishidagi boshqasiga almashtiring.",
            RETRY,
        ),
        fix="Rasmlarni ochish",
        to="media",
    ),
    "media_too_large": Ready(
        title="Fayl Meta qabul qiladiganidan katta",
        hint="Kichikroq fayl tanlang",
        cause="Fayl hajmi Meta chegarasidan oshgan. Faylning o'zida xato yo'q, u faqat juda og'ir.",
        steps=(
            "«Rasmlarni ochish» tugmasini bosing.",
            "Faylni siqilgan yoki qisqaroq variantiga almashtiring.",
            RETRY,
        ),
        fix="Rasmlarni ochish",
        to="media",
    ),
    "media_foreign": Ready(
        title="Rasm boshqa sahifaga tegishli",
        hint="O'z rasmingizni tanlang",
        cause="Tanlangan rasm yoki post boshqa Facebook sahifasiga tegishli, shuning uchun u shu sahifa nomidan ishlatilmaydi.",
        steps=(
            "«Rasmlarni ochish» tugmasini bosing.",
            "Shu sahifaning posti yoki o'zingiz yuklagan faylni tanlang.",
            RETRY,
        ),
        fix="Rasmlarni ochish",
        to="media",
    ),
    "video_not_ready": Ready(
        title="Video hali tayyor emas",
        hint="Video tayyor bo'lishini kuting",
        cause="Meta videoni qayta ishlashni hali tugatmagan.",
        steps=(
            "Bir necha daqiqa kuting: uzun videolar ko'proq vaqt oladi.",
            RETRY,
        ),
        fix="Rasmlarni ochish",
        to="media",
    ),
    "bid_refused": Ready(
        title="Meta bu maqsad uchun narx chegarasini qabul qilmaydi",
        hint="«Qayta urinish» ni bosing",
        cause="Bu maqsadda Meta narxni faqat o'zi avtomatik boshqaradi.",
        steps=(
            "Chegarani keyingi urinishda yubormaymiz, Meta narxni o'zi belgilaydi.",
            RETRY,
        ),
        fix="Rejani ko'rish",
        to="plan",
    ),
    "chat_channel": Ready(
        title="Suhbat kanali tanlanmagan",
        hint="Suhbat kanalini tanlang",
        cause="Bu reklama odamlarni suhbatga olib boradi, lekin kanal belgilanmagan yoki sahifaga Instagram ulanmagan.",
        steps=(
            "«Rejani ochish» tugmasini bosing va suhbat kanalini tanlang.",
            "«Saqlash» ni bosing.",
            RETRY,
        ),
        fix="Rejani ochish",
        to="plan",
    ),
    "phone_missing": Ready(
        title="Telefon raqami kiritilmagan",
        hint="Telefon raqamini kiriting",
        cause="Bu reklama qo'ng'iroq olib keladi, lekin telefon raqami yozilmagan.",
        steps=(
            "«Rejani ochish» tugmasini bosing va raqamni kiriting.",
            "«Saqlash» ni bosing.",
            RETRY,
        ),
        fix="Rejani ochish",
        to="plan",
    ),
    "site_missing": Ready(
        title="Sayt manzili kiritilmagan",
        hint="Sayt manzilini kiriting",
        cause="Bu reklama saytga olib boradi, lekin manzil yozilmagan.",
        steps=(
            "«Rejani ochish» tugmasini bosing va sayt manzilini kiriting.",
            "«Saqlash» ni bosing.",
            RETRY,
        ),
        fix="Rejani ochish",
        to="plan",
    ),
    "site_unusable": Ready(
        title="Bu manzilga reklama berib bo'lmaydi",
        hint="Boshqa manzil kiriting",
        cause="Yozilgan manzil Meta'ning o'z sahifasiga olib boradi. Reklama o'zingizning saytingizga olib borishi kerak.",
        steps=(
            "«Rejani ochish» tugmasini bosing va o'z saytingiz manzilini kiriting.",
            "«Saqlash» ni bosing.",
            RETRY,
        ),
        fix="Rejani ochish",
        to="plan",
    ),
    "site_unreachable": Ready(
        title="Sayt javob bermadi",
        hint="Saytni tekshiring",
        cause="Tekshirganimizda sayt ochilmadi. Ishlamaydigan saytga reklama berilsa, pul behuda ketadi.",
        steps=(
            "Manzilni brauzerda ochib ko'ring.",
            "Ochilmasa, saytni tuzating yoki «Rejani ochish» orqali boshqa manzil kiriting.",
            RETRY,
        ),
        fix="Rejani ochish",
        to="plan",
    ),
    "instagram_profile": Ready(
        title="Sahifada Instagram profili yo'q",
        hint="Instagram'ni ulang",
        cause="Reklama odamlarni Instagram profilga olib boradi, lekin sahifaga profil ulanmagan.",
        steps=(
            "Facebook sahifangiz sozlamalarida Instagram akkauntingizni ulang.",
            "«Ulanishlar» sahifasida sahifalarni yangilang.",
            RETRY,
        ),
        fix="Ulanishlarni ochish",
        to="connections",
    ),
    "profile_incomplete": Ready(
        title="Biznes profili to'ldirilmagan",
        hint="Biznes profilini to'ldiring",
        cause="Reklama yaratish uchun biznes profilingizdagi majburiy maydonlar kerak.",
        steps=(
            "«Profilni ochish» tugmasini bosing va bo'sh maydonlarni to'ldiring.",
            "«Saqlash» ni bosing.",
            RETRY,
        ),
        fix="Profilni ochish",
        to="profile",
    ),
    "no_provider": Ready(
        title="Reklama akkaunti tanlanmagan",
        hint="Reklama akkauntini tanlang",
        cause="Bu reklama uchun reklama akkaunti tanlanmagan.",
        steps=(
            "«Ulanishlarni ochish» tugmasini bosing va akkauntni tanlang.",
            RETRY,
        ),
        fix="Ulanishlarni ochish",
        to="connections",
    ),
    "not_launchable": Ready(
        title="Reklamani hozirgi holatda yaratib bo'lmaydi",
        hint="Reja bo'limini tekshiring",
        cause="Reklama sozlamalarida yetishmayotgan yoki bir-biriga zid ma'lumot bor.",
        steps=(
            "«Rejani ochish» tugmasini bosing va maydonlarni tekshiring.",
            "«Saqlash» ni bosing.",
            RETRY,
        ),
        fix="Rejani ochish",
        to="plan",
    ),
    "temporary": Ready(
        title="Meta hozir javob bermadi",
        hint="Birozdan keyin qayta urining",
        cause="Meta tomonida vaqtincha nosozlik yoki so'rovlar limiti. Reklamangizda xato yo'q.",
        steps=(
            "5–10 daqiqa kuting va «Qayta urinish» ni bosing.",
            "Takrorlansa, «Supportga murojaat» ni bosing.",
        ),
        fix="Ulanishlarni tekshirish",
        to="connections",
    ),
}


def _help(code: LaunchErrorCode, c: Context) -> dict[str, Any]:
    ad = f"{c.ad}-reklama" if c.ad else "Reklama"
    page = f"«{c.page}» sahifasi" if c.page else "Sahifangiz"
    if code == "text_phone":
        return {
            "opening": "",
            "say": f"Meta {ad}ni qabul qilmadi. Sababi va tuzatish yo'li pastda.",
            "title": f"Meta {ad}ni qabul qilmadi",
            "hint": f"{ad} matnini tuzating",
            "explain": f"{ad} matnida telefon raqami bor. Meta reklama matnida raqam yozishga ruxsat bermaydi — raqamni forma o'zi so'raydi. Raqamni olib tashlang va qayta urining.",
            "guide": {
                "cause": f"{ad} matnida telefon raqami bor. Ariza formali reklamada Meta matnga raqam yozishga ruxsat bermaydi — raqamni formaning o'zi so'raydi.",
                "steps": [
                    f"«{ad}ni tuzatish» tugmasini bosing — «Reklamalar» bo'limi ochiladi.",
                    f"{ad} ostidagi «Raqamni olib tashlash» ni bosing yoki raqamni matndan o'zingiz o'chiring.",
                    "«Saqlash» ni bosing.",
                    RETRY,
                ],
            },
            "fix": {"label": f"{ad}ni tuzatish", "to": "ads"},
        }
    if code == "policy":
        return {
            "opening": "",
            "say": f"Meta {ad}ni reklama qoidalariga zid deb topdi. Nimani o'zgartirish kerakligini pastda yozdim.",
            "title": f"Meta {ad}ni qoidalarga zid deb topdi",
            "hint": f"{ad} matnini o'zgartiring",
            "explain": f"{ad} matnida natijani kafolatlaydigan va'da yoki «oldin/keyin» taqqoslash bor. Meta bunday matnni rad etadi — va'dani olib tashlang va qayta urining.",
            "guide": {
                "cause": f"{ad} matnida «100% kafolat», «albatta» kabi va'dalar yoki «oldin/keyin» taqqoslash bor. Meta reklama qoidalari natijani kafolatlashni va «oldin/keyin» taqqoslashni taqiqlaydi.",
                "steps": [
                    f"«{ad}ni tuzatish» tugmasini bosing — «Reklamalar» bo'limi ochiladi.",
                    f"{ad} matnidan «100% kafolat», «albatta», «oldin/keyin» so'zlarini olib tashlang.",
                    "Rasmning o'zida ham shunday yozuv bo'lsa, «Rasmlar» qadamida boshqa rasm tanlang.",
                    "«Saqlash» ni bosing, keyin «Reklamani yaratib bo'lmadi» sahifasida «Qayta urinish» ni bosing.",
                    "Matnda va'da qolmagan bo'lsa-yu, Meta baribir rad etsa: facebook.com/accountquality sahifasida shu reklama yonidagi «Request review» (qayta ko'rib chiqish) ni bosing. Javob odatda 24 soatda keladi.",
                ],
            },
            "fix": {"label": f"{ad}ni tuzatish", "to": "ads"},
        }
    if code == "payment":
        return {
            "opening": "Meta reklama hisobingizda amal qiladigan to'lov usulini topmadi.",
            "say": "Meta to'lov usuli yo'qligi uchun kampaniyani yaratmadi. Kartani qanday qo'shishni bosqichma-bosqich yozdim.",
            "title": "Reklama hisobida to'lov usuli yo'q",
            "hint": "Meta'da to'lov usulini qo'shing",
            "explain": "Reklama hisobiga karta ulanmagan yoki oxirgi to'lov o'tmagan. Meta Billing Hub'da Visa yoki Mastercard kartani qo'shing va qayta urining.",
            "guide": {
                "cause": "Meta reklama hisobingizda amal qiladigan to'lov usuli yo'q yoki oxirgi to'lov rad etilgan. To'lov usulisiz Meta yangi reklama yaratmaydi.",
                "steps": [
                    "«Meta'da to'lov usulini qo'shish» tugmasini bosing — Meta Billing Hub ochiladi. Reklama hisobi egasining Facebook akkaunti bilan kiring.",
                    "Yuqoridagi ro'yxatdan reklama hisobingizni tanlang.",
                    "«Payment methods» (To'lov usullari) → «Add payment method» ni bosing va Visa yoki Mastercard kartangizni kiriting. Kartada xalqaro to'lovlar yoqilgan bo'lsin.",
                    "Oxirgi to'lov o'tmagan bo'lsa, «Pay now» (Hozir to'lash) bilan qarzni yoping — kartada yetarli mablag' bo'lsin.",
                    RETRY,
                ],
            },
            "fix": {
                "label": "Meta'da to'lov usulini qo'shish",
                "to": "connections",
                "href": c.billing_url or BILLING,
            },
        }
    if code == "token":
        return {
            "opening": "Ulanish muddati tugagan yoki kerakli ruxsatlar berilmagan.",
            "say": "Facebook bilan ulanish uzilgan — Meta so'rovimizni qabul qilmadi. Qayta ulash 1 daqiqa oladi.",
            "title": "Facebook bilan ulanish uzilgan",
            "hint": "Facebook'ni qayta ulang",
            "explain": "Facebook bergan ruxsat muddati tugagan yoki reklama uchun kerakli ruxsat olib tashlangan. Ulanishlar sahifasida Facebook'ni qayta ulang va qayta urining.",
            "guide": {
                "cause": "Facebook bergan ruxsat muddati tugagan (Facebook parolini o'zgartirganda ham shunday bo'ladi) yoki ulashda reklama hisobini boshqarish ruxsati olib tashlangan.",
                "steps": [
                    "«Facebook'ni qayta ulash» tugmasini bosing — «Ulanishlar» sahifasi ochiladi.",
                    "Meta qatoridagi «Qayta ulash» ni bosing va Facebook'ga kiring.",
                    "Ruxsatlar oynasida hamma belgilarni yoqilgan holda qoldiring: sahifa, reklama hisobi va lid formalari. Birortasini o'chirsangiz, reklama yaratilmaydi.",
                    "Reklama hisobi va sahifa to'g'ri tanlanganini tekshiring.",
                    RETRY,
                ],
            },
            "fix": {"label": "Facebook'ni qayta ulash", "to": "connections"},
        }
    if code == "page_restricted":
        return {
            "opening": f"Meta {page} nomidan reklama berishni cheklagan.",
            "say": f"Meta {page}dan reklama berishni cheklab qo'ygan. Cheklovni qanday olib tashlashni yozdim.",
            "title": "Sahifaga reklama berish cheklangan",
            "hint": "Account Quality'da cheklovni ko'ring",
            "explain": "Meta sahifani reklama berishdan cheklagan — odatda oldingi reklamalar qoidaga zid deb topilganda. Account Quality'da sababini ko'ring va qayta ko'rib chiqishni so'rang.",
            "guide": {
                "cause": f"Meta {page}ni reklama berishdan cheklagan. Odatda oldingi reklamalar qoidalarga zid deb topilganda yoki sahifa tekshiruvga tushganda shunday bo'ladi. Bu cheklovni faqat Meta olib tashlaydi.",
                "steps": [
                    "«Account Quality'ni ochish» tugmasini bosing — Meta'ning hisob holati sahifasi ochiladi.",
                    "Chapdagi ro'yxatdan sahifangizni tanlang va cheklov sababini o'qing.",
                    "Cheklov xato deb hisoblasangiz, «Request review» (Ko'rib chiqishni so'rash) ni bosing va Meta so'ragan ma'lumotni yuboring. Javob odatda 1–3 kunda keladi.",
                    "Cheklov olib tashlangach, «Reklamani yaratib bo'lmadi» sahifasiga qaytib «Qayta urinish» ni bosing. Shoshilinch bo'lsa, «Ulanishlar» da boshqa sahifani tanlashingiz mumkin.",
                ],
            },
            "fix": {
                "label": "Account Quality'ni ochish",
                "to": "connections",
                "href": ACCOUNT_QUALITY,
            },
        }
    if code == "budget_low":
        return {
            "opening": "",
            "say": "Kunlik byudjet Meta talab qilgandan kam. Bitta tugma bilan tuzatsa bo'ladi.",
            "title": "Kunlik byudjet Meta minimumidan kam",
            "hint": f"Kunlik byudjetni {c.min} qiling",
            "explain": f"Kunlik byudjet {c.budget}, Meta esa bu maqsad uchun kuniga kamida {c.min} so'raydi. Byudjetni {c.min} qiling va qayta urining.",
            "guide": {
                "cause": f"Kunlik byudjet {c.budget}, Meta esa bu maqsad uchun kuniga kamida {c.min} talab qiladi.",
                "steps": [
                    f"«Byudjetni {c.min} qilish» tugmasini bosing — byudjet minimumga ko'tariladi.",
                    f"Boshqa summa kerak bo'lsa, «Reja» qadamida kunlik byudjetni o'zingiz yozing — kamida {c.min}.",
                    "Byudjetni o'zgartirgach, «Reklamani yaratib bo'lmadi» sahifasida «Qayta urinish» ni bosing.",
                ],
            },
            "fix": {"label": f"Byudjetni {c.min} qilish", "to": "budget_fit"},
        }
    ready = READY.get(code)
    if ready is not None:
        return _ready(ready, c)
    return {
        "opening": "" if c.detail else "Meta aniq sababini aytmadi.",
        "say": "Meta reklamani yaratmadi. Sababi va nima qilish kerakligi pastda.",
        "title": "Meta reklamani yaratmadi",
        "hint": "Sababini pastda o'qing",
        "explain": c.detail
        or "Meta aniq sababini aytmadi. Quyidagi joylarni tartib bilan tekshiring.",
        "guide": {
            "cause": c.detail or "Meta aniq sababini aytmadi.",
            "steps": [
                "«Ulanishlarni tekshirish» ni bosing va Meta ulanishi «Faol» ekanini ko'ring.",
                "business.facebook.com da reklama hisobingizda qizil ogohlantirish yo'qligini tekshiring.",
                RETRY,
                "Yana takrorlansa, «Supportga murojaat» ni bosing — Telegram'da mutaxassisga shu sahifadagi xato nomini yozing, u tekshirib javob beradi.",
            ],
        },
        "fix": {"label": "Ulanishlarni tekshirish", "to": "connections"},
    }


def _ready(ready: Ready, c: Context) -> dict[str, Any]:
    """One written answer as the sheet draws it."""
    href = {
        "terms_url": c.terms_url,
        "manager_url": c.manager_url,
        "account_quality": ACCOUNT_QUALITY,
    }.get(ready.href)
    return {
        "opening": "",
        "say": f"{ready.title}. Nima qilish kerakligini pastda yozdim.",
        "title": ready.title,
        "hint": ready.hint,
        "explain": ready.cause,
        "guide": {"cause": ready.cause, "steps": list(ready.steps)},
        "fix": {"label": ready.fix, "to": ready.to} | ({"href": href} if href else {}),
    }


def made_text(made: dict[str, Any]) -> str:
    """What the failed creation left, in one sentence."""
    if not made["campaign"]:
        return "Hech narsa yaratilmadi, pul sarflanmayapti."
    if not made["adset"]:
        return "Kampaniya yaratildi, reklama guruhi va reklamalar esa yo'q. Pul sarflanmayapti."
    if not made["ads_done"]:
        return "Kampaniya va reklama guruhi yaratildi, reklamalar esa yo'q. Reklama hali ko'rsatilmayapti, pul sarflanmayapti."
    return f"Kampaniya, reklama guruhi va {made['ads_done']} ta reklama yaratildi, qolganlari yo'q. Yaratilmagan reklama ko'rsatilmaydi, unga pul sarflanmaydi."


def failure(
    state: dict[str, Any], *, ads_total: int, page: str, budget: str, minimum: str
) -> dict[str, Any]:
    """The refused creation as the «Reklamani yaratib bo'lmadi» sheet draws it."""
    code = failure_code_of(state.get("error_code"))
    detail = state.get("error_detail") or {}
    position = detail.get("position")
    if isinstance(position, str) and position.strip().isdigit():
        position = int(position)
    made = {
        "campaign": bool(state.get("has_stranded")),
        "adset": False,
        "ads_done": 0,
        "ads_total": ads_total,
    }
    said = " — ".join(
        part
        for part in (str(detail.get("title") or ""), str(detail.get("message") or ""))
        if part
    )
    found = _help(
        code,
        Context(
            ad=position + 1 if isinstance(position, int) else None,
            page=page,
            budget=budget,
            min=minimum,
            detail=said,
            terms_url=str(state.get("page_terms_url") or ""),
            manager_url=str(state.get("ads_manager_url") or ""),
            billing_url=str(state.get("billing_url") or ""),
        ),
    )
    opening = found.pop("opening")
    html = state.get("explanation_html") or None
    explaining = bool(state.get("explaining"))
    return {
        "code": code,
        **found,
        "text": " ".join(part for part in (opening, made_text(made)) if part),
        "made": made,
        "raw": said or None,
        "explanation_html": html,
        "explaining": explaining or None,
        "refusal": Refusal(
            key=state.get("refusal_key") or None,
            retryable=code == "temporary",
            title=found["title"],
            cause=found["guide"]["cause"],
            steps=found["guide"]["steps"],
            provider_words=said or None,
            html=html,
            explaining=explaining,
            fix=RefusalFix(
                label=found["fix"]["label"],
                url=found["fix"].get("href"),
                to=found["fix"]["to"],
            ),
        ).model_dump(by_alias=True),
    }


__all__ = ["failure", "made_text"]
