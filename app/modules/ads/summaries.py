from dataclasses import dataclass
from typing import Any

from app.modules.ads.constants import PlacementMode, TargetingMode
from core.leads.ending import EndingLine
from core.targeting import resolve_mode, sent_ages

MAX_NAMES = 3


@dataclass(frozen=True, slots=True)
class AudienceSummary:
    where: str
    ages: str
    genders: str
    mode: str
    placement: str


@dataclass(frozen=True, slots=True)
class NameList:
    names: tuple[str, ...]
    extra: int


@dataclass(frozen=True, slots=True)
class FormSummary:
    name: str
    questions: tuple[str, ...]
    is_new: bool
    ending: EndingLine | None = None


def audience_summary(
    *,
    audience: dict[str, Any],
    geo: dict[str, Any],
    places: list[dict[str, str]],
    mode: str,
    placement: str,
) -> AudienceSummary:
    return AudienceSummary(
        where=_where(geo=geo, places=places, radius_km=audience.get("radius_km")),
        ages=_ages(audience),
        genders=_genders(audience.get("genders")),
        mode=_label(TargetingMode, mode),
        placement=_label(PlacementMode, placement),
    )


def interests_summary(*, chosen: list[dict[str, Any]]) -> NameList:
    names = [str(item.get("label", "")) for item in chosen if item.get("label")]
    return NameList(
        names=tuple(names[:MAX_NAMES]), extra=max(0, len(names) - MAX_NAMES)
    )


def traits_summary(*, proposed: list[dict[str, Any]], chosen: list[str]) -> NameList:
    names = [
        str(item.get("label", ""))
        for item in proposed
        if str(item.get("query", "")) in chosen and item.get("label")
    ]
    return NameList(
        names=tuple(names[:MAX_NAMES]), extra=max(0, len(names) - MAX_NAMES)
    )


def form_summary(
    *,
    options: tuple[Any, ...],
    chosen_form: str,
    questions: list[dict[str, Any]],
    chosen_kinds: list[str],
) -> FormSummary:
    for option in options:
        if option.external_id == chosen_form:
            return FormSummary(
                name=option.name,
                questions=tuple(option.questions),
                is_new=False,
                ending=getattr(option, "ending", None),
            )
    return FormSummary(
        name="Yangi forma",
        questions=tuple(
            str(item.get("label", ""))
            for item in questions
            if item.get("kind") in chosen_kinds
        ),
        is_new=True,
    )


def _where(*, geo: dict[str, Any], places: list[dict[str, str]], radius_km: Any) -> str:
    mode = geo.get("mode")
    if mode == "around":
        kilometres = int(radius_km or 0)
        if not kilometres:
            return "Belgilangan joy atrofida"
        return "Belgilangan joydan %(km)s km atrofda" % {"km": kilometres}
    if mode == "places":
        chosen = [row["name"] for row in places] + [
            str(row.get("name", ""))
            for row in geo.get("areas") or []
            if isinstance(row, dict)
        ]
        named = chosen[:MAX_NAMES]
        if not named:
            return "Joy tanlanmagan"
        listed = ", ".join(named)
        left = len(chosen) - len(named)
        if not left:
            return listed
        return "%(places)s va yana %(count)s joy" % {"places": listed, "count": left}
    return "Butun mamlakat bo'ylab"


def _ages(audience: dict[str, Any]) -> str:
    low, high = sent_ages(
        _age(audience.get("age_min")),
        _age(audience.get("age_max")),
        mode=resolve_mode(audience.get("targeting_mode")),
    )
    if low and high:
        return "%(low)s-%(high)s yosh" % {"low": low, "high": high}
    if low:
        return "%(low)s yoshdan katta" % {"low": low}
    return "Yosh chegarasiz"


def _age(value: Any) -> int | None:
    text = str(value).strip() if value is not None else ""
    return int(text) if text.isdigit() else None


def _genders(value: Any) -> str:
    chosen = {int(item) for item in value or [] if str(item).isdigit()}
    if chosen == {1}:
        return "Erkaklar"
    if chosen == {2}:
        return "Ayollar"
    return "Hammaga"


def _label(choices: Any, value: str) -> str:
    try:
        return str(choices(value).label)
    except ValueError:
        return value
