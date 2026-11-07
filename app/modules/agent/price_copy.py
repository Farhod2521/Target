"""What a price rise says (TZ 1.5), the same words in the cabinet and on the phone.

The price, the usual one and how many times it is; then at most two causes
with their figures against usual, and what to do about each. The TZ's
sample says "lid"; a group bought for chats or calls says its own word.
"""

from typing import Any, Final

from app.common.money import format_minor
from app.modules.agent.figures import hundredths
from app.modules.agent.models import FrequencyAlert, PriceAlert

ADD_CREATIVE: Final = "Yangi kreativ qo'shish"
PAUSE: Final = "Reklamani to'xtatish"
WATCHING: Final = "Kuzataman"
PAUSE_ASKED: Final = (
    "Reklama guruhi to'xtatiladi. Keyin uni o'zingiz qayta yoqishingiz mumkin."
)

# What one result is called, by the group's result.
WORDS: Final[dict[str, str]] = {
    "lead": "lid",
    "site_lead": "lid",
    "site:LEAD": "lid",
    "chat": "suhbat",
    "call": "qo'ng'iroq",
    "click": "o'tish",
    "profile": "profilga o'tish",
}
WHERE: Final[dict[str, str]] = {
    "account_history": "Oldingi reklamalaringizda",
    "niche_average": "Shu sohadagi reklamalarda",
}
LABELS: Final[dict[str, str]] = {
    "cpm": "CPM",
    "frequency": "Frequency",
    "hook": "Hook Rate",
    "hold": "Hold Rate",
    "ctr": "CTR",
    "cpc": "CPC",
    "conversion": "Konversiya",
}
MONEY: Final = frozenset({"cpm", "cpc"})
# TZ 1.4: the cause, then what to do about it.
CAUSES: Final[dict[str, tuple[str, str]]] = {
    "cpm": (
        "auditoriyaga chiqish qimmatlashgan: auditoriya tor yoki reklama sifati past",
        "Auditoriyani kengaytiring, Quality Ranking'ni tekshiring.",
    ),
    "frequency": (
        "odamlar reklamani ko'p marta ko'rgan",
        "Yangi kreativ qo'shing.",
    ),
    "hook": (
        "videoning boshi odamni to'xtatmayapti",
        "Videoning birinchi 1–2 soniyasini almashtiring. Savol, natija yoki kuchli kadr bilan boshlang.",
    ),
    "hold": (
        "odam boshida qiziqib, keyin tashlab ketyapti",
        "Videoni qisqartiring, taklifni oldinga oling.",
    ),
    "ctr": (
        "reklama ko'rilyapti, lekin bosilmayapti: chaqiruv yoki taklif zaif",
        "Chaqiruv va taklifni kuchaytiring.",
    ),
    "cpc": (
        "bosish qimmatlashgan: ko'rsatish narxi va CTR birga yomonlashgan",
        "Auditoriyani kengaytiring va chaqiruvni kuchaytiring.",
    ),
    "conversion": (
        "bosyapti, lekin ariza qoldirmayapti",
        "Formani soddalashtiring, sayt tezligini tekshiring.",
    ),
    "conversion_chat": (
        "bosyapti, lekin yozmayapti",
        "Xabar shablonini tekshiring.",
    ),
    "conversion_call": (
        "bosyapti, lekin qo'ng'iroq qilmayapti",
        "Telefon raqami va chaqiruvni tekshiring.",
    ),
}
RANKINGS: Final[dict[str, tuple[str, str, str]]] = {
    "quality": (
        "Quality Ranking",
        "Meta reklama sifatini boshqalarnikidan past baholayapti",
        "Kreativni almashtiring.",
    ),
    "engagement": (
        "Engagement Ranking",
        "Meta odamlar reklamaga kam qiziqayotganini aytyapti",
        "Videoning boshini (hook) kuchaytiring.",
    ),
    "conversion": (
        "Conversion Ranking",
        "Meta reklama natijaga kam olib kelayotganini aytyapti",
        "Formani soddalashtiring.",
    ),
}
RANKING_WORDS: Final[dict[str, str]] = {
    "below_average_35": "o'rtachadan past (35%)",
    "below_average_20": "o'rtachadan past (20%)",
    "below_average_10": "o'rtachadan past (10%)",
}
NO_CAUSE: Final = (
    "Har bir bosqich biroz yomonlashgan, aniq bitta sabab yo'q.",
    "Yangi kreativ qo'shing va auditoriyani tekshiring.",
)


def word_of(row: PriceAlert) -> str:
    return WORDS.get(row.result_kind, "natija")


def price_title(row: PriceAlert) -> str:
    return "To'xtang, %(word)s narxi oshib ketdi" % {"word": word_of(row)}


def price_body(row: PriceAlert, *, frequency: FrequencyAlert | None = None) -> str:
    """The price against usual, why, and what to do; with the same group's
    frequency level of the day, when there is one (TZ 6.5.6)."""
    lines = [_price(row)]
    causes = [cause for cause in row.causes or [] if not cause.get("context")]
    if causes:
        lines.append("Sabab: %s." % "; ".join(_cause(row, cause) for cause in causes))
        figures = " · ".join(_figure(cause) for cause in row.causes or [])
        if figures:
            lines.append(figures)
        lines.append("Yechim: %s" % " ".join(_answer(row, cause) for cause in causes))
    else:
        lines += ["Sabab: %s" % NO_CAUSE[0], "Yechim: %s" % NO_CAUSE[1]]
    if frequency is not None:
        lines.append(
            "Frequency: %(seen)s - %(title)s."
            % {
                "seen": hundredths(frequency.frequency),
                "title": _frequency_title(frequency),
            }
        )
    return "\n".join(lines)


def _price(row: PriceAlert) -> str:
    usual = format_minor(amount_minor=row.cost_usual_minor, currency=row.currency)
    values = {
        "name": row.name or row.adset_external_id,
        "word": word_of(row),
        "where": WHERE.get(row.baseline_source, WHERE["account_history"]),
        "usual": usual,
        "times": _times(row.times),
    }
    if row.cost_minor is None:
        values["spent"] = format_minor(
            amount_minor=row.spend_minor, currency=row.currency
        )
        return (
            "«%(name)s» reklamasiga oxirgi 3 kunda %(spent)s sarflandi, lekin bitta "
            "ham %(word)s kelmadi. %(where)s bitta %(word)s odatda %(usual)s bo'lgan."
            % values
        )
    values["cost"] = format_minor(amount_minor=row.cost_minor, currency=row.currency)
    return (
        "«%(name)s» reklamasida %(word)s narxi %(cost)s. %(where)s odatda "
        "%(usual)s bo'lgan, ya'ni hozir %(times)s baravar qimmat." % values
    )


def _times(times: int) -> str:
    """Hundredths as one decimal at most: 3, 3,4."""
    return hundredths(round(times / 10) * 10)


def _cause(row: PriceAlert, cause: dict[str, Any]) -> str:
    if cause["key"] == "ranking":
        return RANKINGS[cause["ranking"]][1]
    return CAUSES[_cause_key(row, cause)][0]


def _answer(row: PriceAlert, cause: dict[str, Any]) -> str:
    if cause["key"] == "ranking":
        return RANKINGS[cause["ranking"]][2]
    return CAUSES[_cause_key(row, cause)][1]


def _cause_key(row: PriceAlert, cause: dict[str, Any]) -> str:
    if cause["key"] == "conversion" and row.result_kind in ("chat", "call"):
        return f"conversion_{row.result_kind}"
    return str(cause["key"])


def _figure(cause: dict[str, Any]) -> str:
    if cause["key"] == "ranking":
        return "%(label)s: %(level)s" % {
            "label": RANKINGS[cause["ranking"]][0],
            "level": RANKING_WORDS.get(cause["level"], cause["level"]),
        }
    return "%(label)s: %(now)s (odatda %(usual)s)" % {
        "label": LABELS[cause["key"]],
        "now": _value(cause, cause["now"]),
        "usual": _value(cause, cause["usual"]),
    }


def _value(cause: dict[str, Any], value: float) -> str:
    if cause["key"] in MONEY:
        return format_minor(
            amount_minor=round(value), currency=cause.get("currency", "")
        )
    if cause["key"] == "frequency":
        return hundredths(round(value * 100))
    # A rate in percent, to one decimal: 12%, 0,6%.
    return "%s%%" % hundredths(round(value * 10) * 10)


def _frequency_title(row: FrequencyAlert) -> str:
    from app.modules.agent.frequency_copy import frequency_title

    return frequency_title(row).lower()


__all__ = [
    "ADD_CREATIVE",
    "PAUSE",
    "PAUSE_ASKED",
    "WATCHING",
    "price_body",
    "price_title",
    "word_of",
]
