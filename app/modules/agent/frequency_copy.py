"""What a frequency alert says, the same words in the cabinet and on the phone.

Three figures on every one, as the brief writes them: how often one person
saw the advert, how its click rate moved since it was new, and what a
result costs against what it usually costs here.
"""

from typing import Any, Final

from app.common.money import format_minor
from app.modules.agent.constants import FrequencyLevel
from app.modules.agent.figures import bp_percent, hundredths
from app.modules.agent.models import FrequencyAlert

TITLES: Final[dict[str, Any]] = {
    FrequencyLevel.ADVICE: "Kreativ qo'shish vaqti keldi",
    FrequencyLevel.WARNING: "Kreativni almashtirish kerak",
    FrequencyLevel.REQUIRED: "Kreativni almashtirish majburiy",
}
ADD_CREATIVE: Final = "Qo'shimcha kreativ qo'shamiz"
WORKING_WELL: Final = "Reklama yaxshi ishlayapti"


def frequency_title(row: FrequencyAlert) -> str:
    return str(TITLES[row.level])


def frequency_body(row: FrequencyAlert) -> str:
    """The sentence, then the three figures on one line."""
    seen = hundredths(row.frequency)
    if row.level == FrequencyLevel.ADVICE:
        said = "«%(name)s» reklamasi bir odamga o'rtacha %(seen)s marta ko'rsatildi. Odamlar bu reklamani ko'rishdan charchay boshlaydi - hozir yangi rasm yoki video qo'shsangiz, natija tushmaydi."
    elif row.level == FrequencyLevel.WARNING:
        said = "«%(name)s» reklamasi bir odamga o'rtacha %(seen)s marta ko'rsatildi. Auditoriya bu reklamani ko'p ko'rgan - almashtirilmasa, natija narxi oshib boradi."
    else:
        said = "«%(name)s» reklamasi bir odamga o'rtacha %(seen)s marta ko'rsatildi. Pulning katta qismi reklamani avval ko'rgan odamlarga sarflanyapti. Yangi kreativ qo'shilmaguncha bu xabar yopilmaydi."
    sentence = said % {"name": row.name or row.adset_external_id, "seen": seen}
    figures = " · ".join(part for part in (_ctr(row), _cost(row)) if part)
    return f"{sentence}\n{figures}" if figures else sentence


def _ctr(row: FrequencyAlert) -> str:
    if row.ctr_before_bp is None or row.ctr_now_bp is None:
        return ""
    return "Havolaga bosish ulushi: %(before)s → %(now)s" % {
        "before": bp_percent(row.ctr_before_bp),
        "now": bp_percent(row.ctr_now_bp),
    }


def _cost(row: FrequencyAlert) -> str:
    if row.cost_minor is None:
        return ""
    cost = format_minor(amount_minor=row.cost_minor, currency=row.currency)
    if row.cost_usual_minor is None:
        return "Natija narxi: %(cost)s" % {"cost": cost}
    usual = format_minor(amount_minor=row.cost_usual_minor, currency=row.currency)
    return "Natija narxi: %(cost)s (odatda %(usual)s)" % {"cost": cost, "usual": usual}


__all__ = [
    "ADD_CREATIVE",
    "TITLES",
    "WORKING_WELL",
    "frequency_body",
    "frequency_title",
]
