from collections.abc import Mapping
from typing import Any, Final

from app.common.dates import number_format
from app.common.money import format_minor
from app.modules.agent.constants import RESULT_WORDS, USUAL_COST_LABEL

MONEY_KEYS: Final = frozenset(
    {
        "spend_minor",
        "budgeted_minor",
        "dropped_spend_minor",
        "account_cpl_minor",
        "account_cpql_minor",
        "cpl_minor",
        "cpql_minor",
        "from_minor",
        "to_minor",
        "adset_spend_minor",
    }
)
LABELS: Final[dict[str, Any]] = {
    "days": "Necha kun ishladi",
    "spend_minor": "Sarflandi",
    "impressions": "Ko'rsatildi",
    "leads": "Murojaat",
    "qualified": "Shundan sifatli",
    "cpql_minor": "Bitta sifatli murojaat narxi",
    "cpl_minor": "Bitta murojaat narxi",
    "account_cpl_minor": "Hisobda bitta murojaat odatda",
    "account_cpql_minor": "Hisobda bitta sifatli murojaat odatda",
    "spend_share": "Byudjetning necha foizi sarflandi",
    "budgeted_minor": "Ruxsat etilgan edi",
    "from_minor": "Hozirgi kunlik byudjet",
    "to_minor": "Yangi kunlik byudjet",
    "from_km": "Hozirgi qamrov, km",
    "to_km": "Yangi qamrov, km",
    "from_min": "Hozirgi eng kichik yosh",
    "to_min": "Yangi eng kichik yosh",
    "from_max": "Hozirgi eng katta yosh",
    "to_max": "Yangi eng katta yosh",
    "dropped": "Olib tashlanadigan qiziqishlar",
    "stopped_in_campaign": "Kampaniyadagi guruhlar",
    "account_quality_share": "Hisobda sifatli murojaat ulushi, %",
    "expected_qualified": "Shuncha sifatli murojaat kutilgan edi",
    "ctr_drop_pct": "Bosish darajasi qancha tushdi, %",
    "early_frequency": "Avval har odam necha marta ko'rdi",
    "late_frequency": "Endi har odam necha marta ko'rdi",
    "dead_share_pct": "Behuda ketgan sarf ulushi, %",
    "dropped_spend_minor": "Shu qismga sarflangan",
    "from_age": "Hozirgi yosh chegarasi",
    "to_age": "Yangi yosh chegarasi",
    "ad_leads_reported": "Shu reklamadan murojaat",
    "ad_spend_share_pct": "Guruh sarfining necha foizi shunga ketdi",
    "adset_spend_minor": "Guruh jami sarfladi",
    "adset_leads_reported": "Guruhga jami murojaat",
    "live_ads": "Guruhda ishlayotgan reklamalar",
    "dropped_audiences": "Olib tashlanadigan auditoriyalar",
    "down_url": "Ochilmayotgan sahifa",
    "kept_audiences": "Qoladigan auditoriyalar",
}
_HIDDEN: Final = frozenset(
    {
        "currency",
        "step",
        "multiple",
        "campaign_external_id",
        "early_ctr_bp",
        "late_ctr_bp",
        "cut",
        "dropped_gender",
        "leads_reported",
        "issue_codes",
        "dropped_audience_ids",
        "delivery",
        "reason_on_earlier_figures",
        "qualified",
        "cpql_minor",
        "account_cpql_minor",
        "expected_qualified",
        "account_quality_share",
        "changed",
    }
)
_PERCENTAGES: Final = frozenset(
    {
        "spend_share",
        "ctr_drop_pct",
        "dead_share_pct",
        "account_quality_share",
        "ad_spend_share_pct",
    }
)
_HUNDREDTHS: Final = frozenset({"early_frequency", "late_frequency"})
_UNGROUPED: Final = frozenset(
    {
        "days",
        "from_age",
        "to_age",
        "expected_qualified",
        "from_km",
        "to_km",
        "from_min",
        "to_min",
        "from_max",
        "to_max",
        "dropped",
        "stopped_in_campaign",
        "live_ads",
        "dropped_audiences",
        "kept_audiences",
    }
)


def readable(evidence: Mapping[str, Any], *, currency: str) -> list[tuple[Any, str]]:
    lines: list[tuple[Any, str]] = []
    for key, label in LABELS.items():
        if key in _HIDDEN:
            continue
        value = evidence.get(key)
        if value is not None:
            lines.append((label, _value(key, value, currency)))
        if key == "spend_minor":
            lines += result_lines(evidence, currency=currency)
    return lines


def result_lines(
    evidence: Mapping[str, Any], *, currency: str
) -> list[tuple[Any, str]]:
    kind = str(evidence.get("outcome") or "")
    words = RESULT_WORDS.get(kind)
    count = evidence.get("results")
    if words is None or not isinstance(count, int):
        return []
    if kind == "lead" and "leads" in evidence:
        return []
    count_label, cost_label = words
    lines: list[tuple[Any, str]] = [
        (count_label, number_format(count, force_grouping=True))
    ]
    for label, key in (
        (cost_label, "cost_minor"),
        (USUAL_COST_LABEL, "account_cost_minor"),
    ):
        value = evidence.get(key)
        if isinstance(value, int):
            lines.append((label, format_minor(amount_minor=value, currency=currency)))
    return lines


def _value(key: str, value: Any, currency: str) -> str:
    if key in MONEY_KEYS:
        return format_minor(amount_minor=int(value), currency=currency)
    if key in _HUNDREDTHS and isinstance(value, int):
        return hundredths(value)
    if key in _PERCENTAGES:
        return f"{int(value)}%"
    if key in _UNGROUPED or not isinstance(value, int):
        return str(value)
    return number_format(value, force_grouping=True)


def decimal_of(value: int, unit: int) -> str:
    places = 0 if value % unit == 0 else 1
    return str(number_format(value / unit, decimal_pos=places))


def whole(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def hundredths(value: int) -> str:
    places = 0 if value % 100 == 0 else 1 if value % 10 == 0 else 2
    return str(number_format(value / 100, decimal_pos=places))


def bp_percent(bp: int) -> str:
    return f"{decimal_of(bp, 100)}%"


__all__ = [
    "LABELS",
    "MONEY_KEYS",
    "bp_percent",
    "decimal_of",
    "hundredths",
    "readable",
    "result_lines",
    "whole",
]
