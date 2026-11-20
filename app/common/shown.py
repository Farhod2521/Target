"""The product's own short words in the language a person wrote in.

The AI answers in the language and script of the question (``core.written``);
the lines the product adds around that answer - "Looking at your
campaigns…" while it works - have to follow, or an answer in Russian arrives
under an Uzbek status. Each line is written in Uzbek Latin in the code; this
holds its Russian and English, and Uzbek Cyrillic is the Latin transliterated.
"""

from typing import Final

from core.written import to_cyrillic

# A ``Written.key``: uz, uz-cyrl, ru, en.
CYRILLIC_UZBEK: Final = "uz-cyrl"

_OTHER: Final[dict[str, dict[str, str]]] = {
    "Hisobingiz holatini tekshiryapman…": {
        "ru": "Проверяю состояние вашего аккаунта…",
        "en": "Checking your account…",
    },
    "Yechimlar bazasidan qidiryapman…": {
        "ru": "Ищу в базе решений…",
        "en": "Searching the help base…",
    },
    "Mutaxassis uchun zayavka tayyorlayapman…": {
        "ru": "Готовлю заявку для специалиста…",
        "en": "Preparing a request for a specialist…",
    },
    "Tariflarni ko'ryapman…": {
        "ru": "Смотрю тарифы…",
        "en": "Looking at the plans…",
    },
    "CRM natijalarini ko'ryapman…": {
        "ru": "Смотрю результаты CRM…",
        "en": "Looking at CRM results…",
    },
    "Qo'riqchi ogohlantirishlarini ko'ryapman…": {
        "ru": "Смотрю предупреждения охранника…",
        "en": "Looking at the guard's warnings…",
    },
    "Referal va hamyonni ko'ryapman…": {
        "ru": "Смотрю рефералы и кошелёк…",
        "en": "Looking at referrals and the wallet…",
    },
    "Hisobingizni ko'ryapman…": {
        "ru": "Смотрю ваш аккаунт…",
        "en": "Looking at your account…",
    },
    "Qidiryapman…": {"ru": "Ищу…", "en": "Searching…"},
    "Kampaniyalarni ko'ryapman…": {
        "ru": "Смотрю кампании…",
        "en": "Looking at the campaigns…",
    },
    "Reklamalarni ko'ryapman…": {
        "ru": "Смотрю объявления…",
        "en": "Looking at the adverts…",
    },
    "Auditoriyani ko'ryapman…": {
        "ru": "Смотрю аудиторию…",
        "en": "Looking at the audience…",
    },
    "Raqamlarni ko'ryapman…": {
        "ru": "Смотрю цифры…",
        "en": "Looking at the numbers…",
    },
    "Formalarni ko'ryapman…": {
        "ru": "Смотрю формы…",
        "en": "Looking at the forms…",
    },
    "O'zgarishlarni ko'ryapman…": {
        "ru": "Смотрю изменения…",
        "en": "Looking at the changes…",
    },
    "Takliflarni ko'ryapman…": {
        "ru": "Смотрю предложения…",
        "en": "Looking at the suggestions…",
    },
    "Tayyorlangan kampaniyalarni ko'ryapman…": {
        "ru": "Смотрю подготовленные кампании…",
        "en": "Looking at the prepared campaigns…",
    },
    "Ma'lumotlarni ko'ryapman…": {
        "ru": "Смотрю данные…",
        "en": "Looking at the data…",
    },
    "Javob uzun chiqdi va oxiri sig'madi.": {
        "ru": "Ответ получился длинным, и конец не поместился.",
        "en": "The answer ran long and its end did not fit.",
    },
    "Davom et": {"ru": "Продолжай", "en": "Go on"},
    "Mutaxassisga yuborish": {
        "ru": "Отправить специалисту",
        "en": "Send to a specialist",
    },
    "O'zgarishni tayyorlayapman…": {
        "ru": "Готовлю изменение…",
        "en": "Preparing the change…",
    },
}


def shown(uzbek: str, language: str) -> str:
    """The line in this language (a ``Written.key``), Uzbek when there is no
    other spelling of it."""
    if language == CYRILLIC_UZBEK:
        return to_cyrillic(uzbek)
    return _OTHER.get(uzbek, {}).get(language) or uzbek


def shown_language(payload: dict[str, object]) -> str:
    """The key a turn's fixed words are shown in: the script-aware one the
    ask kept, else the language code of a turn queued before it was kept."""
    return str(payload.get("shown") or payload.get("language") or "")


__all__ = ["CYRILLIC_UZBEK", "shown", "shown_language"]
