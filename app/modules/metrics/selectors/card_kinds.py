from typing import Any, Final

from app.modules.metrics.selectors.cards import TEXT, CardText, count_text, money_text
from app.modules.metrics.selectors.results import ResultText, words_for
from core.metrics import CardSpec, Outcome, formulas

RESULT_KEYS: Final[frozenset[str]] = frozenset({"cpl", "leads"})


def text_of(spec: CardSpec, *, kind: Outcome = "lead") -> CardText:
    if kind == "lead" or spec.key not in RESULT_KEYS:
        return TEXT[spec.key]
    words = words_for(kind)
    if not words.field:
        return TEXT[spec.key]
    if spec.key == "cpl":
        return CardText(
            label=words.cost_label,
            hint=words.hint,
            display=lambda t, d, c: money_text(_result_cost(t, words), c),
            value=lambda t: _result_cost(t, words),
        )
    return CardText(
        label=words.label,
        hint=words.hint,
        display=lambda t, d, c: count_text(_result_count(t, words)),
        value=lambda t: _result_count(t, words),
    )


def _result_count(totals: Any, words: ResultText) -> int:
    return int(getattr(totals, words.field, 0) or 0)


def _result_cost(totals: Any, words: ResultText) -> int | None:
    return formulas.cost_per_result(
        totals.spend_minor, _result_count(totals, words), per=words.per
    )


__all__ = ["RESULT_KEYS", "text_of"]
