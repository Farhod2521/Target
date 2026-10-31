"""The campaign edit form as the cabinet draws it, and its save read back into sections.

The form sends every field it shows, changed or not; only the sections that
changed and may change go on to be saved, as the browser used to work out.
"""

from datetime import date
from decimal import Decimal
from typing import Any, Final, Literal

from pydantic import Field
from sqlalchemy.orm import Session

from app.common.contract import Camel, zero_or
from app.common.money import provider_money
from app.modules.accounts.models import User
from app.modules.ads import selectors
from app.modules.ads.contract.listing import figures_of
from app.modules.ads.contract.words import goal_of, kind_of, network_of, place_of

# The section a refusal names, as the form field it is drawn under.
FORM_FIELDS: Final[dict[str, str]] = {
    "daily_budget": "dailyBudget",
    "age_min": "ageMin",
    "age_max": "ageMax",
    "genders": "gender",
    "end_date": "endsAt",
    "spend_cap": "limit",
    "budget": "dailyBudget",
    "audience": "ageMin",
    "limits": "endsAt",
}
GENDERS: Final[dict[str, list[int]]] = {"male": [1], "female": [2], "all": []}
# Steps up from today's budget, offered as one-press amounts.
PRESET_STEPS: Final = (1, 1.2, 1.5, 2)


class CampaignPatch(Camel):
    daily_budget: float = Field(description="Major units, as the input shows them.")
    age_min: int
    age_max: int
    gender: Literal["all", "female", "male"]
    ends_at: date | None = None
    limit: float | None = Field(None, description="The spending limit, major units.")
    audience_ids: list[str] = Field(default_factory=list)
    group: str | None = Field(None, description="Split campaigns: the group edited.")


def _major(minor: int | None, places: int) -> float:
    return (minor or 0) / 10**places


def changed_sections(
    sections: dict[str, Any], patch: CampaignPatch
) -> dict[str, Any] | None:
    """Only what the form changed and the rules let change; None when nothing is to be sent."""
    out: dict[str, Any] = {}
    budget = sections.get("budget")
    if (
        budget
        and budget["can_change"]
        and patch.daily_budget != _major(budget["current_minor"], budget["places"])
    ):
        out["budget"] = {"daily_budget": Decimal(str(patch.daily_budget))}
    audience = sections.get("audience")
    genders = GENDERS[patch.gender]
    if audience and audience["can_change"]:
        moved = (
            patch.age_min != audience["age_min"]
            or patch.age_max != audience["age_max"]
            or genders != audience["genders"]
        )
        if moved:
            out["audience"] = {
                "age_min": patch.age_min,
                "age_max": patch.age_max,
                "genders": genders if audience["allows_gender"] else None,
                "radius_km": audience["radius_km"]
                if audience["offers_radius"]
                else None,
                "keep_interests": True,
            }
    limits = sections.get("limits")
    if limits and limits["can_change"]:
        cap = float(limits["spend_cap"]) if limits["spend_cap"] else None
        if patch.ends_at != limits["end_date"] or patch.limit != cap:
            out["limits"] = {
                "end_date": patch.ends_at if limits["offers_end_time"] else None,
                "spend_cap": Decimal(str(patch.limit))
                if limits["offers_spend_cap"] and patch.limit is not None
                else None,
            }
    return out or None


def edit_form(
    db: Session, *, owner: User, edit: Any, form: dict[str, Any]
) -> dict[str, Any]:
    from app.modules.ads.contract.listing import ListAsk, figures_range
    from app.modules.metrics.selectors.panel import campaign_chips

    campaign = edit.campaign
    group = edit.group
    settings = selectors.row_settings(campaign=campaign)
    sections = form["sections"]
    budget, audience, limits = (
        sections.get("budget"),
        sections.get("audience"),
        sections.get("limits"),
    )
    currency = (budget or {}).get("currency") or settings.currency or campaign.currency
    provider = campaign.provider
    places = (
        budget["places"]
        if budget
        else provider_money(provider=provider).decimal_places(currency)
    )
    current = _major(
        budget["current_minor"] if budget else campaign.daily_budget_minor, places
    )
    chosen, _ = figures_range(
        db, owner=owner, account=campaign.ad_account, ask=ListAsk(period="7d")
    )
    chips = next(
        iter(
            campaign_chips(
                db,
                owner=owner,
                campaigns=[campaign],
                date_range=chosen,
                account=campaign.ad_account,
            )
        ),
        None,
    )
    figures = figures_of(chips, currency=currency, provider=provider)
    sketch = (
        selectors.group_settings(adset=group, campaign=campaign).audience
        if group is not None
        else settings.audience
    )
    objective = campaign.objective_raw or ""
    gender = {(1,): "male", (2,): "female"}.get(
        tuple((audience or {}).get("genders") or ()), "all"
    )
    early = form["early_hours"]
    return {
        "id": str(campaign.id),
        "name": group.name if group is not None else campaign.name,
        "kind": kind_of(goal_of(objective), objective),
        "network": network_of(provider),
        "currency": currency,
        "daily_budget": current,
        "min_budget": _major(budget["floor_minor"] if budget else 0, places),
        "presets": sorted(
            {
                round(current * step)
                for step in PRESET_STEPS
                if round(current * step) > 0
            }
        ),
        "spent7d": figures["spent"]
        if figures
        else zero_or(0, currency, provider=provider),
        "spent_total": zero_or(settings.spending_minor, currency, provider=provider),
        "unit_cost": figures["unit_cost"] if figures else None,
        "place": place_of(sketch),
        "age_min": (audience or {}).get("age_min", 18),
        "age_max": (audience or {}).get("age_max", 65),
        "age_bounds": (audience or {}).get("age_bounds", [18, 65]),
        "gender": gender,
        "audiences": [],
        "reach": [0, 0],
        "ends_at": limits["end_date"].isoformat()
        if limits and limits["end_date"]
        else None,
        "limit": float(limits["spend_cap"]) if limits and limits["spend_cap"] else None,
        "group": {"external_id": group.external_id, "name": group.name}
        if group is not None
        else None,
        "split": group is None and form["groups"] > 1,
        "locks": {
            "budget": _lock(budget["can_change"], early > 0) if budget else "closed",
            "audience": _lock(audience["can_change"], audience["is_learning"])
            if audience
            else "closed",
            "limits": None if limits and limits["can_change"] else "ended",
        },
        "early_hours": early,
    }


def _lock(open_now: bool, learning: bool) -> str | None:
    if open_now:
        return None
    return "learning" if learning else "closed"


__all__ = ["FORM_FIELDS", "CampaignPatch", "changed_sections", "edit_form"]
