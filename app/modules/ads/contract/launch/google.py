"""The Google Search wizard as the cabinet's one draft.

A Google launch is its own row with its own steps (answers, words, review);
the screens read it through the same draft as Meta's, with what Google has
no use for left neutral.
"""

from datetime import datetime
from typing import Any, Final
from urllib.parse import urlsplit

from app.common.contract import Money, money, zero_or
from app.modules.ads.constants import GOOGLE_FAILURES, GoogleGoal, LaunchStatus
from app.modules.ads.contract.launch.words import LaunchStatus as Shown
from app.modules.ads.contract.launch.words import Step
from app.modules.ads.models import GoogleLaunch
from app.modules.ads.selectors.google import keyword_rows

WHOLE_COUNTRY: Final = "Butun mamlakat"
GOALS: Final[dict[str, str]] = {GoogleGoal.VISITS: "click", GoogleGoal.CALLS: "call"}
GOAL_KEYS: Final[dict[str, str]] = {shown: key for key, shown in GOALS.items()}


def chosen_areas(launch: GoogleLaunch) -> list[str]:
    return sorted({str(row.get("area")) for row in launch.places or []})


def areas_of(options: list[dict[str, str]]) -> list[dict[str, str | None]]:
    """The places the answers step offers."""
    return [
        {"key": row["key"], "name": row["name"], "parent": row.get("parent") or None}
        for row in options
    ]


def words_of(launch: GoogleLaunch, *, places: list[str]) -> dict[str, Any] | None:
    keywords = [
        {
            "text": row["text"],
            "volume": row["searches"] if isinstance(row["searches"], int) else 0,
        }
        for row in keyword_rows(launch=launch)
    ]
    headlines = list(launch.headlines or [])
    if not keywords and not headlines:
        return None
    return {
        "say": "",
        "keywords": keywords,
        "minus": list(launch.negative_keywords or []),
        "headlines": headlines,
        "descriptions": list(launch.descriptions or []),
        "url": launch.final_url,
        "url_check": None,
        "paths": [launch.path1, launch.path2],
        "places": places,
    }


def standing(
    launch: GoogleLaunch, step: str | None, *, written: bool
) -> tuple[Shown, Step]:
    """Where the draft stands: the launch's word, then the step the screen is on."""
    status = launch.status
    if status == LaunchStatus.CREATING:
        return "creating", "review"
    if status == LaunchStatus.CREATED:
        return "sent", "review"
    if status == LaunchStatus.FAILED:
        return "failed", "review"
    if status == LaunchStatus.BUILDING and step != "plan":
        return "building", "words"
    if status == LaunchStatus.READY and step not in ("plan", "words"):
        return "ready", "review"
    return "draft", step or ("words" if written else "plan")  # type: ignore[return-value]


def _host(url: str) -> str:
    return (urlsplit(url).hostname or url).removeprefix("www.")


def draft(
    launch: GoogleLaunch,
    *,
    taps: dict[str, Any],
    options: list[dict[str, str]],
    region: str,
    now: datetime,
) -> dict[str, Any]:
    pending = taps.get("answers") or {}
    provider = launch.ad_account.provider
    currency = launch.currency
    zero = zero_or(0, currency, provider=provider)
    tapped = pending.get("daily_budget")
    saved = money(launch.daily_budget_minor, currency, provider=provider)
    daily_budget = Money.model_validate(tapped) if tapped else saved or zero
    goal = pending["goal"] if "goal" in pending else GOALS.get(launch.goal)
    link_url = pending.get("link_url", launch.final_url)
    phone = pending.get("phone", launch.phone)
    areas = pending["areas"] if "areas" in pending else chosen_areas(launch)
    names = {row["key"]: row["name"] for row in options}
    places = [names.get(key, key) for key in areas] or [WHOLE_COUNTRY]
    google = words_of(launch, places=places)
    status, step = standing(launch, taps.get("step"), written=google is not None)
    kind = "call" if goal == "call" else "click"
    why = str(GOOGLE_FAILURES.get(launch.error_code) or launch.error_message or "")
    sent = status == "sent"
    return {
        "id": str(launch.id),
        "flow": "google",
        "network_id": "google",
        "status": status,
        "step": step,
        "goal_mode": taps.get("goal_mode") or "list",
        "goal_words": taps.get("goal_words") or "",
        "goal": goal,
        "ai_goal": None,
        "method": None,
        "daily_budget": daily_budget,
        "min_budget": zero,
        "budget_presets": [],
        "start": "today",
        "media_source": "lib",
        "media": [],
        "text_mode": "one",
        "offer": "",
        "offers": {},
        "building": None,
        "proposal": None
        if status in ("draft", "building")
        else {
            "say": "",
            "name": launch.campaign_name,
            "goal": {
                "kind": kind,
                "by": "me",
                "site": _host(link_url),
                "search": True,
                "dest": phone if kind == "call" else None,
            },
            "audience": {
                "by": "me",
                "places": places,
                "age": None,
                "genders": "all",
                "keywords": len(launch.keywords or []),
                "minus": len(launch.negative_keywords or []),
            },
            "budget": {
                "by": "me",
                "ends_at": None,
                "total": None,
                "starts_at": now.isoformat(),
                "fixed_currency": True,
            },
            "changes": [],
            "ads": [],
            "attention": [],
            "blockers": [],
        },
        "creation": {
            "stage": 3 if sent else 1,
            "campaign": sent,
            "adset": sent,
            "ads_done": 1 if sent else 0,
            "ads_total": 1,
            "sent_at": launch.finished_at.isoformat()
            if sent and launch.finished_at
            else None,
        }
        if status in ("creating", "sent")
        else None,
        "failure": {
            "code": "other",
            "say": why,
            "title": why or "Google reklamani qabul qilmadi",
            "text": why,
            "explain": why,
            "hint": why,
            "guide": {"cause": why, "steps": []},
            "fix": {"label": "So'zlarni tekshirish", "to": "words"},
            "raw": why or None,
            "made": {"campaign": False, "adset": False, "ads_done": 0, "ads_total": 1},
        }
        if status == "failed"
        else None,
        "first_launch": False,
        "campaign_id": None,
        "review_eta": "hours",
        "google": google,
        "link_url": link_url,
        "phone": phone,
        "chat_channel": "messenger",
        "welcome_text": "",
        "chat_questions": [],
        "lead_form": None,
        "areas": areas,
        "page": {"has_instagram": False, "pixel": None, "region": region or "UZ"},
        "reading": None,
        "goal_phrases": [],
        "prep_error": None,
        "delivery": None,
        "created_ad_id": None,
        "regenerated": [],
    }


__all__ = ["GOAL_KEYS", "areas_of", "chosen_areas", "draft"]
