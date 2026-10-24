from collections.abc import Iterable, Mapping
from typing import Any, Final

from core.agent import ProviderAdvice

WEAK_CONFIDENCE: Final = frozenset({"LOW"})
_PHRASES: Final[dict[str, ProviderAdvice]] = {
    "advantage+ audience": "broader_audience",
    "advantage audience": "broader_audience",
    "detailed targeting expansion": "broader_audience",
    "audience expansion": "broader_audience",
}


def meaning(item: Mapping[str, Any]) -> ProviderAdvice | None:
    if _text(item.get("confidence")).upper() in WEAK_CONFIDENCE:
        return None
    said = f"{_text(item.get('title'))} {_text(item.get('message'))}".lower()
    if not said.strip():
        return None
    for phrase, means in _PHRASES.items():
        if phrase in said:
            return means
    return None


def meanings(recommendations: Iterable[Any]) -> tuple[ProviderAdvice, ...]:
    found: list[ProviderAdvice] = []
    for item in recommendations or ():
        if not isinstance(item, Mapping):
            continue
        means = meaning(item)
        if means is not None and means not in found:
            found.append(means)
    return tuple(found)


def _text(value: Any) -> str:
    return str(value or "").strip()


__all__ = ["WEAK_CONFIDENCE", "meaning", "meanings"]
