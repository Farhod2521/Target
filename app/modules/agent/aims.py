from collections.abc import Mapping
from typing import Any, Final

from app.common.dates import number_format
from app.common.money import format_minor
from app.modules.agent.constants import EXPECTATION_LABELS, RESULT_WORDS
from app.modules.agent.figures import bp_percent, whole
from core.agent import EXPECTATIONS

_CHEAPER: Final = frozenset(
    {"cheaper_leads", "cheaper_reported_leads", "cheaper_group_leads"}
)
_ATTENTION: Final = frozenset({"attention_recovers", "group_attention_recovers"})
_PRICED: Final[dict[str, str]] = {
    "cheaper_results": "attention_recovers",
    "group_cheaper_results": "group_attention_recovers",
}
GOAL_KEYS: Final = ("outcome", "results", "cost_minor", "account_cost_minor")


def goal_of(
    *, evidence: Mapping[str, Any], diagnosis: Mapping[str, Any]
) -> dict[str, Any]:
    found = diagnosis.get("evidence") or {}
    merged = {key: found[key] for key in GOAL_KEYS if key in found}
    merged |= {key: evidence[key] for key in GOAL_KEYS if key in evidence}
    return merged


def expectation(*, rule: str, evidence: Mapping[str, Any]) -> str:
    promise = _promise(rule, evidence)
    words = RESULT_WORDS.get(str(evidence.get("outcome") or ""))
    if words is not None and (promise in _PRICED or promise == "cheaper_leads"):
        return "%(cost)s tushishi kerak." % {"cost": words[1]}
    if words is not None and promise == "more_leads":
        return "%(what)s ko'payishi kerak - bittasining narxi oshmagan holda." % {
            "what": words[0]
        }
    return str(EXPECTATION_LABELS.get(promise, ""))


def result_line(evidence: Mapping[str, Any], *, currency: str) -> str:
    words = RESULT_WORDS.get(str(evidence.get("outcome") or ""))
    count = whole(evidence.get("results"))
    if words is None or count is None:
        return ""
    parts = [f"{words[0]}: {number_format(count, force_grouping=True)}"]
    own, usual = (
        whole(evidence.get("cost_minor")),
        whole(evidence.get("account_cost_minor")),
    )
    if own is not None:
        price = f"{words[1]}: {format_minor(amount_minor=own, currency=currency)}"
        if usual is not None:
            usually = format_minor(amount_minor=usual, currency=currency)
            price += f" ({'odatda'} {usually})"
        parts.append(price)
    return " · ".join(parts)


def expected_figure(*, rule: str, diagnosis: Mapping[str, Any], currency: str) -> str:
    evidence = diagnosis.get("evidence") or {}
    promise = _promise(rule, evidence)
    if promise in _PRICED:
        return _price_aim(evidence, currency=currency)
    if promise in _ATTENTION:
        own = whole(evidence.get("link_ctr_bp"))
        usual = whole(evidence.get("account_link_ctr_bp"))
        if own is None or usual is None or own >= usual:
            return ""
        return (
            "Mo'ljal: bosish ulushi hisobingiz o'rtachasiga, %(value)s ga yaqinlashishi."
            % {"value": bp_percent(usual)}
        )
    if promise in _CHEAPER and "cost_minor" in evidence:
        return _price_aim(evidence, currency=currency)
    if promise in _CHEAPER:
        own = whole(evidence.get("cpl_minor"))
        usual = whole(evidence.get("account_cpl_minor"))
        if usual is None or (own is not None and own <= usual):
            return ""
        return (
            "Mo'ljal: bitta murojaat narxi hisobingiz o'rtachasiga, %(value)s ga yaqinlashishi."
            % {"value": format_minor(amount_minor=usual, currency=currency)}
        )
    return ""


def _price_aim(evidence: Mapping[str, Any], *, currency: str) -> str:
    words = RESULT_WORDS.get(str(evidence.get("outcome") or ""))
    own = whole(evidence.get("cost_minor"))
    usual = whole(evidence.get("account_cost_minor"))
    if words is None or usual is None or (own is not None and own <= usual):
        return ""
    return "Mo'ljal: %(cost)s hisobingiz o'rtachasiga, %(value)s ga yaqinlashishi." % {
        "cost": words[1],
        "value": format_minor(amount_minor=usual, currency=currency),
    }


def _promise(rule: str, evidence: Mapping[str, Any]) -> str:
    promise = EXPECTATIONS.get(rule, "")
    if promise in _PRICED and "cost_minor" not in evidence:
        return _PRICED[promise]
    return promise


__all__ = ["GOAL_KEYS", "expectation", "expected_figure", "goal_of", "result_line"]
