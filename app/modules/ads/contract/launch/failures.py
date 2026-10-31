"""Why the network refused a launch, and what to press: the help base's ready answers.

One answer per code, written here and never by the AI (copied from the
screens' catalog, as the browser held it in ``live/launch-map.ts``). A code
the help base does not know keeps the network's own sentence.
"""

from dataclasses import dataclass
from typing import Any

from app.modules.ads.contract.launch.words import LaunchErrorCode, failure_code_of

RETRY = "«Reklamani yaratib bo'lmadi» sahifasiga qaytib, «Qayta urinish» ni bosing."


@dataclass(frozen=True)
class Context:
    ad: int | None
    """The refused advert, 1-based; None when it was not one advert."""
    page: str
    budget: str
    min: str
    detail: str
    """The backend's sentence, for a code the help base does not know."""


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
                "href": "https://business.facebook.com/billing_hub/payment_methods",
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
                "href": "https://www.facebook.com/accountquality/",
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
    return {
        "opening": "" if c.detail else "Meta noma'lum xato qaytardi.",
        "say": "Meta reklamani yaratmadi. Sababi va nima qilish kerakligi pastda."
        if c.detail
        else "Meta sababini aytmagan xato qaytardi. Avval qayta urinib ko'ring — ko'pincha shu yetadi.",
        "title": "Meta reklamani yaratmadi",
        "hint": "Birozdan keyin qayta urining",
        "explain": c.detail
        or "Meta sababini aytmadi — bunday xato ko'pincha Meta tomonidagi vaqtincha nosozlikdan bo'ladi. 5–10 daqiqadan keyin qayta urining; takrorlansa, supportga yozing.",
        "guide": {
            "cause": c.detail
            or "Meta sababini aytmadi. Bunday xato ko'pincha Meta tomonidagi vaqtincha nosozlikdan bo'ladi — reklamangizda xato bo'lmasligi mumkin.",
            "steps": [
                "5–10 daqiqa kuting va «Qayta urinish» ni bosing — ko'p hollarda shu yetadi.",
                "Takrorlansa, «Ulanishlarni tekshirish» ni bosing va Meta ulanishi «Faol» ekanini ko'ring.",
                "business.facebook.com da reklama hisobingizda qizil ogohlantirish yo'qligini tekshiring.",
                "Yana takrorlansa, «Supportga murojaat» ni bosing — Telegram'da mutaxassisga shu sahifadagi xato nomini yozing, u tekshirib javob beradi.",
            ],
        },
        "fix": {"label": "Ulanishlarni tekshirish", "to": "connections"},
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
    known = code != "other"
    said = str(state.get("error_message") or "")
    found = _help(
        code,
        Context(
            ad=position + 1 if isinstance(position, int) else None,
            page=page,
            budget=budget,
            min=minimum,
            detail="" if known else said,
        ),
    )
    opening = found.pop("opening")
    raw = "" if known else str(state.get("error_code") or "")
    return {
        "code": code,
        **found,
        "text": " ".join(part for part in (opening, made_text(made)) if part),
        "made": made,
        "raw": raw or None,
        "explanation_html": state.get("explanation_html") or None,
        "explaining": bool(state.get("explaining")) or None,
    }


__all__ = ["failure", "made_text"]
