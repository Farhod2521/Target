"""What a frequency alert says, the same words in the cabinet and on the phone.

Three figures on every one, as TZ 6.4 writes them: how often one person
saw the advert, how its CTR moved since it was new, and what a lead costs
against what it usually costs here. The TZ's samples say "video"; the words
here say "kreativ", which is right for a picture as well.
"""

from typing import Any, Final

from app.common.money import format_minor
from app.modules.agent.constants import FrequencyLevel
from app.modules.agent.figures import bp_percent, hundredths
from app.modules.agent.models import FrequencyAlert

TITLES: Final[dict[str, Any]] = {
    FrequencyLevel.ADVICE: "Kreativ qo'shish vaqti keldi",
    FrequencyLevel.WARNING: "Kreativni almashtirish kerak",
    FrequencyLevel.REQUIRED: "Kreativ eskirdi, almashtiring",
}
ADD_CREATIVE: Final = "Qo'shimcha kreativ qo'shamiz"
WORKING_WELL: Final = "Reklama yaxshi ishlayapti"


def frequency_title(row: FrequencyAlert) -> str:
    return str(TITLES[row.level])


def frequency_body(row: FrequencyAlert) -> str:
    """The sentence, then the three figures on one line."""
    seen = hundredths(row.frequency)
    if row.level == FrequencyLevel.ADVICE:
        said = "«%(name)s» reklamasi bir odamga o'rtacha %(seen)s marta ko'rsatildi. Odamlar bu kreativni ko'rishdan charchay boshlaydi. Hozir yangi kreativ qo'shsangiz, natija tushmaydi."
    elif row.level == FrequencyLevel.WARNING:
        said = "«%(name)s» reklamasi bir odamga o'rtacha %(seen)s marta ko'rsatildi. Auditoriya bu kreativni ko'p ko'rib bo'ldi. Almashtirilmasa, lid narxi oshib boradi."
    else:
        said = "«%(name)s» reklamasi bir odamga o'rtacha %(seen)s marta ko'rsatildi. Pulning katta qismi kreativni oldin ko'rgan odamlarga sarflanyapti. Yangi kreativ qo'shilmaguncha bu xabar yopilmaydi."
    sentence = said % {"name": row.name or row.adset_external_id, "seen": seen}
    figures = " · ".join(part for part in (_ctr(row), _cost(row)) if part)
    return f"{sentence}\n{figures}" if figures else sentence


def _ctr(row: FrequencyAlert) -> str:
    if row.ctr_before_bp is None or row.ctr_now_bp is None:
        return ""
    return "CTR: %(before)s → %(now)s" % {
        "before": bp_percent(row.ctr_before_bp),
        "now": bp_percent(row.ctr_now_bp),
    }


def _cost(row: FrequencyAlert) -> str:
    if row.cost_minor is None:
        return ""
    cost = format_minor(amount_minor=row.cost_minor, currency=row.currency)
    if row.cost_usual_minor is None:
        return "Lid narxi: %(cost)s" % {"cost": cost}
    usual = format_minor(amount_minor=row.cost_usual_minor, currency=row.currency)
    return "Lid narxi: %(cost)s (odatda %(usual)s)" % {"cost": cost, "usual": usual}


__all__ = [
    "ADD_CREATIVE",
    "TITLES",
    "WORKING_WELL",
    "frequency_body",
    "frequency_title",
]
