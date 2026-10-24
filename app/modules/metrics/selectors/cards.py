from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.money import format_minor, number_format
from app.modules.accounts.models import User
from app.modules.metrics.models import MetricPreference
from core.metrics import CardKey, PanelDay, PanelTotals, frequency_bp, stored_or_default

NO_ANSWER: Final = "—"


@dataclass(frozen=True, slots=True)
class CardText:
    label: Any
    hint: Any
    display: Callable[[PanelTotals, PanelDay | None, str], str]
    value: Callable[[PanelTotals], float | None] | None = None


def money_text(amount: int | None, currency: str) -> str:
    return (
        format_minor(amount_minor=amount, currency=currency)
        if amount is not None
        else NO_ANSWER
    )


def count_text(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _percent(bp: int, *, measured: bool = True) -> str:
    if not measured:
        return NO_ANSWER
    return f"{number_format(Decimal(bp) / 100, decimal_pos=2)}%"


def _ratio(bp: int, *, measured: bool = True) -> str:
    if not measured:
        return NO_ANSWER
    return str(number_format(Decimal(bp) / 100, decimal_pos=1))


RANGE_PEOPLE_KEYS: Final = frozenset({"reach", "frequency"})


def counts_range(key: str, totals: PanelTotals) -> bool:
    return key in RANGE_PEOPLE_KEYS and totals.reach > 0


def _reach(totals: PanelTotals, day: PanelDay | None) -> str:
    return count_text(totals.reach) if totals.reach else NO_ANSWER


def _freq(totals: PanelTotals, day: PanelDay | None) -> str:
    return _ratio(frequency_bp(totals)) if totals.reach else NO_ANSWER


TEXT: Final[dict[CardKey, CardText]] = {
    "cpl": CardText(
        label="Murojaat narxi",
        hint="Har qanday murojaat, sifatidan qat'i nazar.",
        display=lambda t, d, c: money_text(t.cpl_minor, c),
        value=lambda t: t.cpl_minor,
    ),
    "spend": CardText(
        label="Sarflandi",
        hint="Reklama uchun to'langan pul.",
        display=lambda t, d, c: format_minor(amount_minor=t.spend_minor, currency=c),
        value=lambda t: t.spend_minor,
    ),
    "cpm": CardText(
        label="Ming ko'rsatish narxi",
        hint="Reklamani ming marta ko'rsatish shuncha turdi.",
        display=lambda t, d, c: money_text(t.cpm_minor, c),
        value=lambda t: t.cpm_minor,
    ),
    "platform_cpl": CardText(
        label="Platforma bo'yicha murojaat narxi",
        hint="Reklama platformasi o'z hisobi bo'yicha. Bizning raqamdan arzonroq chiqsa - murojaat yo'lda yo'qolgan bo'lishi mumkin.",
        display=lambda t, d, c: money_text(t.platform_cpl_minor, c),
        value=lambda t: t.platform_cpl_minor,
    ),
    "cpc": CardText(
        label="Bosish narxi",
        hint="Reklamaga bitta bosish shuncha turdi.",
        display=lambda t, d, c: money_text(t.cpc_minor, c),
        value=lambda t: t.cpc_minor,
    ),
    "leads": CardText(
        label="Jami murojaat",
        hint="Formani to'ldirgan hamma.",
        display=lambda t, d, c: count_text(t.leads),
        value=lambda t: t.leads,
    ),
    "leads_reported": CardText(
        label="Platforma hisobi",
        hint="Reklama platformasining o'z hisobi. Bizning raqamdan farq qilsa, murojaat yo'lda yo'qolgan bo'lishi mumkin.",
        display=lambda t, d, c: count_text(t.leads_reported),
        value=lambda t: t.leads_reported,
    ),
    "impressions": CardText(
        label="Ko'rsatildi",
        hint="Reklama necha marta ekranda paydo bo'ldi.",
        display=lambda t, d, c: count_text(t.impressions),
        value=lambda t: t.impressions,
    ),
    "reach": CardText(
        label="Qamrov",
        hint="Reklamani ko'rgan odamlar soni. Bir odam bir marta sanaladi.",
        display=lambda t, d, c: _reach(t, d),
    ),
    "frequency": CardText(
        label="Chastota",
        hint="Bitta odam reklamani o'rtacha necha marta ko'rdi. Uchdan oshsa - reklama charchagan, kreativni yangilash vaqti.",
        display=lambda t, d, c: _freq(t, d),
    ),
    "ctr": CardText(
        label="Bosish ulushi",
        hint="Reklamani ko'rganlarning qanchasi bosdi.",
        display=lambda t, d, c: _percent(t.ctr_bp, measured=t.impressions > 0),
        value=lambda t: t.ctr_bp,
    ),
    "link_ctr": CardText(
        label="Havolaga bosish ulushi",
        hint="Ko'rganlarning qanchasi reklama yuboradigan joyga o'tdi. Yuqoridagi ulushdan past bo'lishi odatiy.",
        display=lambda t, d, c: _percent(t.link_ctr_bp, measured=t.impressions > 0),
        value=lambda t: t.link_ctr_bp,
    ),
    "clicks": CardText(
        label="Bosishlar",
        hint="Reklamaga har qanday bosish - matnni ochish ham shunga kiradi.",
        display=lambda t, d, c: count_text(t.clicks),
        value=lambda t: t.clicks,
    ),
    "link_clicks": CardText(
        label="Havolaga bosildi",
        hint="Reklama yuboradigan joyga haqiqatan o'tganlar.",
        display=lambda t, d, c: count_text(t.link_clicks),
        value=lambda t: t.link_clicks,
    ),
    "unique_clicks": CardText(
        label="Noyob bosishlar",
        hint="Necha xil odam bosgani. Bir odam o'n marta bossa ham - bitta.",
        display=lambda t, d, c: count_text(d.unique_clicks) if d else NO_ANSWER,
    ),
    "video_plays": CardText(
        label="Video boshlandi",
        hint="Videoni ko'rishni boshlaganlar soni.",
        display=lambda t, d, c: count_text(t.video_plays),
        value=lambda t: t.video_plays,
    ),
    "video_thruplays": CardText(
        label="Oxirigacha ko'rildi",
        hint="Videoni oxirigacha yoki 15 soniyagacha ko'rganlar.",
        display=lambda t, d, c: count_text(t.video_thruplays),
        value=lambda t: t.video_thruplays,
    ),
    "video_hold": CardText(
        label="Ushlab turish",
        hint="Videoni boshlaganlarning qanchasi oxirigacha qoldi.",
        display=lambda t, d, c: f"{t.hold_share}%" if t.video_plays else NO_ANSWER,
        value=lambda t: t.hold_share,
    ),
}
GROUP_TEXT: Final[dict[str, Any]] = {
    "money": "Pul",
    "result": "Natija",
    "delivery": "Ko'rsatish",
    "engagement": "Qiziqish",
    "video": "Video",
}
DAY_NOTE = "Faqat %(day)s kuni"


def day_note(day: date) -> str:
    return str(DAY_NOTE % {"day": day.strftime("%d.%m")})


def chosen_for(db: Session, *, owner: User) -> tuple[CardKey, ...]:
    row = db.scalar(
        select(MetricPreference.chosen).where(MetricPreference.owner_id == owner.id)
    )
    return stored_or_default(row)


__all__ = [
    "DAY_NOTE",
    "GROUP_TEXT",
    "NO_ANSWER",
    "TEXT",
    "CardText",
    "chosen_for",
    "count_text",
    "day_note",
    "money_text",
]
