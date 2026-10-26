"""How often a keyword is searched, from Google's keyword planner.

Two questions, both under ``KeywordPlanIdeaService`` and both open to an
account at Basic access:

- :func:`keyword_volumes` - the figures for keywords already chosen, so a
  screen can put "1 300 a month" beside each one the AI wrote.
- :func:`keyword_ideas` - more keywords like the ones given, for the person
  who wants to widen the list.

No language is sent. Uzbek is not one of Google's languages, so narrowing
to Russian or English would hide exactly the searches an Uzbek shop wants;
left out, Google counts every language.

Google asks for one request a second per customer and refreshes the figures
monthly: callers should not ask twice for the same list.
"""

from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict

from googleadskit.client import AdsClient

Competition = Literal["low", "medium", "high", "unknown"]

_COMPETITION: Final[dict[str, Competition]] = {
    "LOW": "low",
    "MEDIUM": "medium",
    "HIGH": "high",
}
_NETWORK: Final = "GOOGLE_SEARCH"
# Ideas beyond this are a list nobody reads; the request is paged by Google.
_IDEAS_PAGE: Final = 50


class KeywordVolumeDTO(BaseModel):
    """One keyword and how it is searched in the chosen places."""

    model_config = ConfigDict(frozen=True)

    text: str
    # Average over the last twelve months. Nought is a real answer - too
    # few searches to report - not a missing one.
    monthly_searches: int = 0
    competition: Competition = "unknown"


def keyword_volumes(
    client: AdsClient, customer_id: str, *, keywords: list[str], places: list[str]
) -> list[KeywordVolumeDTO]:
    """Figures for exactly these keywords, in these places (resource names)."""
    if not keywords:
        return []
    answer = client.post(
        f"customers/{customer_id}:generateKeywordHistoricalMetrics",
        {
            "keywords": keywords,
            "geoTargetConstants": places,
            "keywordPlanNetwork": _NETWORK,
        },
    )
    return [
        _volume(row.get("text"), row.get("keywordMetrics"))
        for row in answer.get("results") or []
    ]


def keyword_ideas(
    client: AdsClient, customer_id: str, *, seeds: list[str], places: list[str]
) -> list[KeywordVolumeDTO]:
    """Keywords like ``seeds``, the most searched first."""
    if not seeds:
        return []
    answer = client.post(
        f"customers/{customer_id}:generateKeywordIdeas",
        {
            "keywordSeed": {"keywords": seeds},
            "geoTargetConstants": places,
            "keywordPlanNetwork": _NETWORK,
            "includeAdultKeywords": False,
            "pageSize": _IDEAS_PAGE,
        },
    )
    ideas = [
        _volume(row.get("text"), row.get("keywordIdeaMetrics"))
        for row in answer.get("results") or []
    ]
    return sorted(ideas, key=lambda idea: idea.monthly_searches, reverse=True)


def _volume(text: object, metrics: Any) -> KeywordVolumeDTO:
    metrics = metrics if isinstance(metrics, dict) else {}
    searches = metrics.get("avgMonthlySearches")
    return KeywordVolumeDTO(
        text=str(text or ""),
        monthly_searches=int(str(searches)) if searches not in (None, "") else 0,
        competition=_COMPETITION.get(str(metrics.get("competition") or ""), "unknown"),
    )


__all__ = ["Competition", "KeywordVolumeDTO", "keyword_ideas", "keyword_volumes"]
