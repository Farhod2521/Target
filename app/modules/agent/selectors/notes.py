"""What last night's diagnosis says about groups no proposal answers."""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.models import AdSet, Campaign
from app.modules.agent.causes import cause_line
from app.modules.agent.constants import DiagnosisCause
from app.modules.agent.models import AdSetDiagnosis
from app.modules.agent.selectors.policy import diagnoses
from app.modules.agent.selectors.suggestions import waiting
from core.agent.diagnosis import CAUSE_OF
from core.metrics import outcome_of

RESULT_EVIDENCE: Final[dict[str, str]] = {
    "lead": "leads",
    "chat": "results",
    "call": "results",
    "click": "results",
    "view": "impressions",
}

NOTED: Final = (
    DiagnosisCause.TOO_EARLY,
    DiagnosisCause.LANDING_BLOCKS,
    DiagnosisCause.WEAK_CREATIVE,
    DiagnosisCause.WORN_OUT,
    DiagnosisCause.COSTLY_AUDIENCE,
    DiagnosisCause.NOT_DELIVERING,
    DiagnosisCause.LEARNING_LIMITED,
)

ANSWERS: Final[dict[str, set[str]]] = {
    DiagnosisCause.WEAK_CREATIVE: {"refresh_ad", "weak_ad"},
    DiagnosisCause.WORN_OUT: {"refresh_ad", "saturated"},
    DiagnosisCause.COSTLY_AUDIENCE: {"saturated", "starved", "narrow_audience"},
    DiagnosisCause.NOT_DELIVERING: {"starved", "saturated"},
    DiagnosisCause.LEARNING_LIMITED: {"starved"},
}

CREATIVE: Final = (DiagnosisCause.WEAK_CREATIVE, DiagnosisCause.WORN_OUT)

CREATIVE_ADVICE: Final[dict[str, Any]] = {
    DiagnosisCause.WEAK_CREATIVE: (
        "Odamlar reklamani ko'ryapti, lekin kam bosyapti. Kutubxonaga yangi rasm "
        "yoki video yuklang - e'tiborni matn emas, birinchi navbatda rasm tortadi."
    ),
    DiagnosisCause.WORN_OUT: (
        "Bir xil odamlar reklamani ko'p marta ko'rib bo'ldi. Kutubxonaga yangi "
        "rasm yoki video yuklang."
    ),
}

VIDEO_ADVICE: Final[dict[str, Any]] = {
    "opening": (
        "Videoning boshi odamni to'xtatmayapti. Birinchi 1-2 soniyasini almashtiring: "
        "savol, natija, kuchli kadr yoki yozuv bilan boshlang."
    ),
    "middle": (
        "Odamlar boshini ko'rib, keyin tashlab ketyapti. Videoni qisqartiring va "
        "asosiy taklifni oldinga olib chiqing."
    ),
    "whole": (
        "Videoning boshi ham, o'rtasi ham odamni ushlab qolmayapti. Kreativni "
        "butunlay almashtiring."
    ),
    "offer": (
        "Video ko'rilyapti, lekin bosilmayapti. Chaqiruv (tugma va matn) yoki "
        "taklifning o'zi zaif - shuni kuchaytiring."
    ),
}

AUDIENCE_ADVICE: Final[dict[str, Any]] = {
    DiagnosisCause.COSTLY_AUDIENCE: (
        "Bu auditoriyaga ko'rsatish odatdagidan qimmat. Auditoriyani kengaytiring: "
        "qiziqishlarni kamaytiring yoki yosh va hududni kengroq oling."
    ),
    DiagnosisCause.NOT_DELIVERING: (
        "Reklama kunlik byudjetining katta qismini sarflay olmayapti - Meta uni "
        "kam ko'rsatyapti. Auditoriyani kengaytiring yoki kreativni almashtiring."
    ),
    DiagnosisCause.LEARNING_LIMITED: (
        "Meta o'rganishi uchun haftasiga taxminan 50 ta natija kerak. Auditoriyani "
        "kengaytiring, byudjetni oshiring yoki o'xshash guruhlarni bittaga "
        "birlashtiring."
    ),
}

WAIT_ADVICE: Final = (
    "Hozircha hech narsani o'zgartirmang: har o'zgarish o'rganishni boshidan boshlaydi."
)

LANDING_ADVICE: Final[dict[str, Any]] = {
    "site_down": (
        "Sayt ishlashini tekshiring - tuzatilmaguncha bosganlar hech narsa ko'rmaydi."
    ),
    "long_form": (
        "Savollari kamroq formaga almashtiring: shu guruhda yangi forma bilan "
        "reklama qo'shiladi, eskisi to'xtatiladi."
    ),
    "low_click_to_lead": (
        "Bosganlar formani to'ldirmayapti: savollar reklamadagi va'daga mosmi, "
        "tekshiring yoki boshqa formaga almashtiring."
    ),
    "low_arrival": (
        "Bosganlar saytga yetib bormayapti: sahifa sekin yoki telefonda noto'g'ri "
        "ochilayotgan bo'lishi mumkin."
    ),
    "junk_numbers": (
        "Formaga yuborishdan oldin raqamni tasdiqlash qadamini qo'shing - "
        "noto'g'ri va takror raqamlar kamayadi."
    ),
    "conversion_ranking_low": (
        "Bosgandan keyingi qadamni soddalashtiring: forma yoki sahifa ortiqcha "
        "narsa so'rayotgan bo'lishi mumkin."
    ),
}


@dataclass(frozen=True, slots=True)
class DiagnosisNote:
    """One group's cause, as the waiting list draws it."""

    adset_id: str
    name: str
    cause: str
    signal: str
    line: str
    advice: Any
    campaign_pk: str


_NO_MIRROR: Final = (None, "", "")


def diagnosis_notes(
    db: Session,
    *,
    owner: User,
    currency: str,
    now: datetime,
    hidden_adsets: Collection[str] = (),
) -> list[DiagnosisNote]:
    """The groups too young to judge, held back by a form or page, or needing a new picture."""
    from app.modules.ads.selectors import all_launched_campaign_ids

    query = diagnoses(owner).where(AdSetDiagnosis.cause.in_(NOTED))
    if hidden_adsets:
        query = query.where(
            AdSetDiagnosis.adset_external_id.not_in(list(hidden_adsets))
        )
    found = list(db.scalars(query.order_by(AdSetDiagnosis.name)))
    if not found:
        return []

    mirror = {
        external_id: (campaign_pk, goal, campaign_id)
        for external_id, campaign_pk, goal, campaign_id in db.execute(
            select(
                AdSet.external_id,
                AdSet.campaign_id,
                AdSet.optimization_goal_raw,
                Campaign.external_id,
            )
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .where(
                AdSet.owner_id == owner.id,
                AdSet.external_id.in_([row.adset_external_id for row in found]),
            )
        )
    }
    ours = (
        all_launched_campaign_ids(db, owner=owner)
        if any(row.cause in CREATIVE for row in found)
        else frozenset()
    )
    rows = [
        row
        for row in found
        if _worth_saying(
            row, mirror=mirror.get(row.adset_external_id, _NO_MIRROR), ours=ours
        )
    ]
    if not rows:
        return []

    answered: dict[str, set[str]] = {}
    for suggestion in waiting(db, owner=owner, now=now):
        group = suggestion.target_parent_id or suggestion.target_external_id
        answered.setdefault(group, set()).add(suggestion.rule)
    return [
        _note(
            row=row,
            currency=currency,
            campaign_pk=mirror.get(row.adset_external_id, _NO_MIRROR)[0],
        )
        for row in rows
        if not answered.get(row.adset_external_id, set())
        & ANSWERS.get(row.cause, set())
    ]


def _note(*, row: AdSetDiagnosis, currency: str, campaign_pk: Any) -> DiagnosisNote:
    signal = next(
        (str(each) for each in row.signals or () if CAUSE_OF.get(each) == row.cause),
        "",
    )
    reading = {"cause": row.cause, "signals": row.signals, "evidence": row.evidence}
    return DiagnosisNote(
        adset_id=row.adset_external_id,
        name=row.name,
        cause=row.cause,
        signal=signal,
        line=cause_line(reading, currency=currency),
        advice=_advice(
            cause=row.cause,
            signal=signal,
            signals=frozenset(str(each) for each in row.signals or ()),
            video=(row.evidence or {}).get("hook_bp") is not None,
        ),
        campaign_pk=str(campaign_pk) if campaign_pk else "",
    )


def _advice(*, cause: str, signal: str, signals: frozenset[str], video: bool) -> Any:
    if cause == DiagnosisCause.TOO_EARLY:
        return WAIT_ADVICE
    if (
        cause == DiagnosisCause.WEAK_CREATIVE
        and video
        and (part := _video_part(signals))
    ):
        return VIDEO_ADVICE[part]
    if cause in CREATIVE:
        return CREATIVE_ADVICE[cause]
    if cause in AUDIENCE_ADVICE:
        return AUDIENCE_ADVICE[cause]
    return LANDING_ADVICE.get(signal, "")


def _video_part(signals: frozenset[str]) -> str:
    """Where a video loses people: the opening, the middle, both, or neither."""
    hook, hold = "weak_hook" in signals, "weak_hold" in signals
    if hook and hold:
        return "whole"
    if hook:
        return "opening"
    if hold:
        return "middle"
    return "offer" if "low_ctr" in signals else ""


def _worth_saying(
    row: AdSetDiagnosis, *, mirror: tuple[Any, str, str], ours: frozenset[str]
) -> bool:
    _, goal, campaign_id = mirror
    if row.cause == DiagnosisCause.TOO_EARLY:
        return _spent_for_nothing(row, goal=goal)
    if row.cause in CREATIVE:
        return campaign_id in ours
    return True


def _spent_for_nothing(row: AdSetDiagnosis, *, goal: str) -> bool:
    """Whether the group spent and has nothing of its own kind to show."""
    field = RESULT_EVIDENCE.get(outcome_of(goal) if goal.strip() else "lead")
    evidence = row.evidence or {}
    if field is None or (field == "results" and field not in evidence):
        return False
    spend = evidence.get("spend_minor")
    return isinstance(spend, int) and spend > 0 and not evidence.get(field)


__all__ = [
    "ANSWERS",
    "AUDIENCE_ADVICE",
    "CREATIVE",
    "CREATIVE_ADVICE",
    "LANDING_ADVICE",
    "NOTED",
    "RESULT_EVIDENCE",
    "VIDEO_ADVICE",
    "WAIT_ADVICE",
    "DiagnosisNote",
    "diagnosis_notes",
]
