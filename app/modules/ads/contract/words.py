"""The cabinet's enums, from the mirror's own words.

Each of these was a table in the browser (``bridges/campaigns.ts``) reading
the words this backend sent; they are kept here now, beside the words.
"""

from datetime import datetime, timedelta
from typing import Any, Final, Literal

from app.common.db import utcnow
from app.modules.ads.constants import Delivery
from core.targeting import AudienceSketch

Status = Literal[
    "active", "learning", "pending", "rejected", "paused", "finished", "paused_above"
]
Goal = Literal["lead", "chat", "call", "click", "profile", "view", "sub", "other"]
Kind = Literal["lead", "chat", "call", "view", "click", "site", "profile", "sub"]
Origin = Literal["here", "network", "other_account"]

STATUSES: Final[dict[str, Status]] = {
    Delivery.ACTIVE: "active",
    Delivery.PAUSED: "paused",
    Delivery.PAUSED_ABOVE: "paused_above",
    Delivery.PENDING: "pending",
    Delivery.BILLING: "pending",
    Delivery.REJECTED: "rejected",
    Delivery.FINISHED: "finished",
    Delivery.UNKNOWN: "pending",
}
GOALS: Final[dict[str, Goal]] = {
    "lead": "lead",
    "leads": "lead",
    "outcome_leads": "lead",
    "lead_generation": "lead",
    "site_lead": "lead",
    "site_leads": "lead",
    "chat": "chat",
    "chats": "chat",
    "messages": "chat",
    "outcome_engagement": "chat",
    "call": "call",
    "calls": "call",
    "click": "click",
    "clicks": "click",
    "traffic": "click",
    "outcome_traffic": "click",
    "link_clicks": "click",
    "view": "view",
    "views": "view",
    "awareness": "view",
    "outcome_awareness": "view",
    "reach": "view",
    "brand_awareness": "view",
    "video_views": "view",
    "recall": "view",
    "profile": "profile",
    "profile_visits": "profile",
    "sub": "sub",
    "subs": "sub",
    "followers": "sub",
    "page_likes": "sub",
}
KINDS: Final[dict[Goal, Kind]] = {
    "lead": "lead",
    "chat": "chat",
    "call": "call",
    "click": "click",
    "profile": "profile",
    "view": "view",
    "sub": "sub",
}
NETWORKS: Final[dict[str, tuple[str, str]]] = {
    "meta": ("M", "Meta"),
    "google": ("G", "Google"),
}
RUNNING: Final[frozenset[Status]] = frozenset({"active", "learning", "pending"})
# The learning phase as the cabinet draws it: hours done of this many.
LEARNING_HOURS: Final = 72


def status_word(word: str) -> Status:
    return STATUSES.get(word, "pending")


def status_of(row: Any, *, learning: bool = False) -> Status:
    """What the row draws: the badge (the worst of its adverts), else its own delivery."""
    status = status_word(str(getattr(row, "badge", None) or row.delivery))
    if status == "active" and learning:
        return "learning"
    controls = getattr(row, "controls", None)
    if status == "paused" and controls is not None and controls.parent_off:
        return "paused_above"
    return status


def goal_of(word: str) -> Goal:
    return GOALS.get(word.strip().lower(), "other")


def kind_of(goal: Goal, objective: str) -> Kind:
    found = KINDS.get(goal)
    if found is not None:
        return found
    lowered = objective.lower()
    return "site" if "sales" in lowered or "conversion" in lowered else "click"


def network_of(provider: str) -> dict[str, str]:
    key = (provider or "meta").lower()
    letter, name = NETWORKS.get(key, (key[:1].upper() or "M", provider or "Meta"))
    return {"id": key, "letter": letter, "name": name}


def controls_of(controls: Any, *, early_hours: int = 0) -> dict[str, Any]:
    out: dict[str, Any] = {
        "can_pause": bool(getattr(controls, "can_pause", False)),
        "can_resume": bool(getattr(controls, "can_resume", False)),
        "can_budget": bool(getattr(controls, "can_budget", False)),
        "learning": bool(getattr(controls, "warns_learning", False)),
        "early_hours": getattr(controls, "early_hours", None) or early_hours,
    }
    if getattr(controls, "watched_account", False):
        out["watched"] = True
    return out


def learning_of(left: int, *, now: datetime | None = None) -> dict[str, Any] | None:
    """Hours of learning done, of how many, and when it ends; None when it has."""
    if left <= 0:
        return None
    at = now or utcnow()
    return {
        "hours": max(0, LEARNING_HOURS - left),
        "total": max(LEARNING_HOURS, left),
        "ready_at": (at + timedelta(hours=left)).isoformat(),
    }


def place_of(sketch: AudienceSketch | None) -> str:
    if sketch is None:
        return ""
    if sketch.geo == "around" and sketch.radius:
        return f"+{sketch.radius} {sketch.radius_unit or 'km'}"
    if sketch.geo == "places" and sketch.places:
        return f"{sketch.places} ta joy"
    if sketch.geo == "country":
        return "Butun mamlakat"
    return ""


def audience_of(sketch: AudienceSketch | None) -> str:
    """Where and whom, in a few words: "+5 km, 25–45 yosh, ayollar"."""
    if sketch is None:
        return ""
    parts = [place_of(sketch)]
    if sketch.age_min or sketch.age_max:
        parts.append(f"{sketch.age_min or 18}–{sketch.age_max or 65} yosh")
    if sketch.genders == "male":
        parts.append("erkaklar")
    if sketch.genders == "female":
        parts.append("ayollar")
    return ", ".join(part for part in parts if part)


def last_action_of(action: Any) -> str | None:
    if action is None:
        return None
    if action.status == "failed":
        return "failed"
    return "dry_run" if action.dry_run else None


__all__ = [
    "RUNNING",
    "Goal",
    "Kind",
    "Origin",
    "Status",
    "audience_of",
    "controls_of",
    "goal_of",
    "kind_of",
    "last_action_of",
    "learning_of",
    "network_of",
    "place_of",
    "status_of",
    "status_word",
]
