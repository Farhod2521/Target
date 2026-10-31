"""The wizard's enums, from the launch's own words.

Each was a table in the browser (``live/launch-map.ts``) reading what this
backend sent; older and singular spellings are still read, as they were there.
"""

from decimal import Decimal, InvalidOperation
from typing import Any, Final, Literal

from app.common.contract import Money
from app.common.money import provider_money

LaunchGoal = Literal["lead", "call", "chat", "click", "profile", "view", "sub"]
LaunchMethod = Literal["instant_form", "website"]
LaunchStatus = Literal[
    "draft", "building", "prep_failed", "ready", "failed", "creating", "created", "sent"
]
PrepError = Literal[
    "rate_limited",
    "subscription_expired",
    "profile_incomplete",
    "free_proposals_used",
    "stalled",
    "other",
]
LaunchErrorCode = Literal[
    "text_phone", "policy", "payment", "token", "page_restricted", "budget_low", "other"
]
Step = Literal["plan", "media", "words", "review"]
ResultKind = Literal["lead", "chat", "call", "view", "click", "site", "profile", "sub"]

STATUSES: Final[dict[str, LaunchStatus]] = {
    "draft": "draft",
    "new": "draft",
    "answering": "draft",
    "plan": "draft",
    "media": "draft",
    "form": "draft",
    "preparing": "building",
    "building": "building",
    "queued": "building",
    "pending": "building",
    "regenerating": "building",
    "prep_failed": "prep_failed",
    "preparation_failed": "prep_failed",
    "stalled": "prep_failed",
    "ready": "ready",
    "proposed": "ready",
    "review": "ready",
    "rolled_back": "ready",
    "failed": "failed",
    "creation_failed": "failed",
    "refused": "failed",
    "creating": "creating",
    "launching": "creating",
    "created": "created",
    "paused": "created",
    "not_started": "created",
    "sent": "sent",
    "launched": "sent",
    "started": "sent",
    "active": "sent",
    "live": "sent",
}
PREP_ERRORS: Final[dict[str, PrepError]] = {
    "rate_limited": "rate_limited",
    "too_many_requests": "rate_limited",
    "subscription_expired": "subscription_expired",
    "read_only": "subscription_expired",
    "no_subscription": "subscription_expired",
    "profile_incomplete": "profile_incomplete",
    "free_proposals_used": "free_proposals_used",
    "stalled": "stalled",
    "timeout": "stalled",
}
# Meta's goal keys: leads, messages, calls, views, traffic, profile_visits,
# site_leads (a lead on the owner's site).
GOALS: Final[dict[str, LaunchGoal]] = {
    "lead": "lead",
    "leads": "lead",
    "site_leads": "lead",
    "site_lead": "lead",
    "lead_website": "lead",
    "outcome_leads": "lead",
    "lead_form": "lead",
    "instant_form": "lead",
    "lead_generation": "lead",
    "call": "call",
    "calls": "call",
    "chat": "chat",
    "messages": "chat",
    "message": "chat",
    "outcome_engagement": "chat",
    "click": "click",
    "traffic": "click",
    "site": "click",
    "outcome_traffic": "click",
    "link_clicks": "click",
    "profile": "profile",
    "profile_visits": "profile",
    "view": "view",
    "views": "view",
    "awareness": "view",
    "reach": "view",
    "outcome_awareness": "view",
    "sub": "sub",
    "followers": "sub",
    "page_likes": "sub",
}
SITE_LEADS: Final = frozenset({"site_leads", "site_lead", "lead_website"})
# Each goal's Meta key, sent when the plan's own list does not name it.
META_KEYS: Final[dict[str, str]] = {
    "lead": "leads",
    "chat": "messages",
    "call": "calls",
    "view": "views",
    "click": "traffic",
    "profile": "profile_visits",
    "sub": "",
}
FAILURES: Final[dict[str, LaunchErrorCode]] = {
    "text_phone": "text_phone",
    "phone_in_text": "text_phone",
    "ad_text_phone": "text_phone",
    "policy": "policy",
    "policy_violation": "policy",
    "ad_rejected": "policy",
    "creative_rejected": "policy",
    "disapproved": "policy",
    "payment": "payment",
    "ad_account_payment_due": "payment",
    "payment_method_missing": "payment",
    "no_payment_method": "payment",
    "token": "token",
    "connection_unusable": "token",
    "permissions_missing": "token",
    "token_expired": "token",
    "page_restricted": "page_restricted",
    "page_blocked": "page_restricted",
    "budget_low": "budget_low",
    "budget_below_minimum": "budget_low",
    "group_budget_below_minimum": "budget_low",
}
STEPS: Final[dict[str, Step]] = {
    "plan": "plan",
    "form": "plan",
    "media": "media",
    "review": "review",
}


def status_of(value: str | None) -> LaunchStatus:
    return STATUSES.get((value or "").lower(), "draft")


def prep_error_of(value: str | None) -> PrepError:
    return PREP_ERRORS.get((value or "").lower(), "other")


def failure_code_of(value: str | None) -> LaunchErrorCode:
    return FAILURES.get((value or "").lower(), "other")


def key_of(value: Any) -> str:
    """A goal's key as it is sent: a string, or a row carrying one."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        found = (
            value.get("key")
            or value.get("value")
            or value.get("goal")
            or value.get("id")
        )
        return found if isinstance(found, str) else ""
    return ""


def goal_of(value: Any) -> LaunchGoal | None:
    return GOALS.get(key_of(value).lower())


def method_of(value: Any) -> LaunchMethod | None:
    key = key_of(value).lower()
    if key in SITE_LEADS:
        return "website"
    return "instant_form" if GOALS.get(key) == "lead" else None


def goal_keys(plan: dict[str, Any]) -> list[str]:
    """The keys of the plan's own goal list."""
    goals = plan.get("goals")
    return [key for key in map(key_of, goals) if key] if isinstance(goals, list) else []


def goal_key(goal: str | None, method: str | None, offered: list[str]) -> str:
    """The key the plan's own list uses for a goal, else Meta's own."""
    if not goal:
        return ""
    own = [key for key in offered if goal_of(key) == goal]
    if goal == "lead":
        wanted = "website" if method == "website" else "instant_form"
        fallback = "site_leads" if method == "website" else META_KEYS["lead"]
        return next((key for key in own if method_of(key) == wanted), fallback)
    return own[0] if own else META_KEYS.get(goal, "")


def kind_of(goal_key_: str) -> ResultKind:
    """The result a saved goal key counts, as the proposal's goal line draws it."""
    if method_of(goal_key_) == "website":
        return "site"
    return goal_of(goal_key_) or "lead"


def places_of(currency: str) -> int:
    return provider_money(provider="meta").decimal_places(currency) if currency else 2


def whole_money(value: Any, currency: str) -> Money:
    """Whole currency units (a number, or a decimal string such as "12.50") as money."""
    try:
        amount = Decimal(str(value).replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        amount = Decimal(0)
    if not amount.is_finite():
        amount = Decimal(0)
    places = places_of(currency)
    return Money(minor=round(amount * 10**places), currency=currency, exponent=places)


def minor_money(minor: int, currency: str) -> Money:
    return Money(minor=int(minor), currency=currency, exponent=places_of(currency))


def whole_of(amount: Money) -> Decimal:
    """Money as the whole units PlanIn takes."""
    return Decimal(amount.minor).scaleb(-amount.exponent)


def shown(amount: Money) -> str:
    """ "12.5 USD", as the help base's sentences name an amount."""
    whole = whole_of(amount).normalize()
    return f"{whole:f} {amount.currency}"


__all__ = [
    "LaunchErrorCode",
    "LaunchGoal",
    "LaunchMethod",
    "LaunchStatus",
    "PrepError",
    "ResultKind",
    "Step",
    "failure_code_of",
    "goal_key",
    "goal_keys",
    "goal_of",
    "key_of",
    "kind_of",
    "method_of",
    "minor_money",
    "places_of",
    "prep_error_of",
    "shown",
    "status_of",
    "whole_money",
    "whole_of",
]
