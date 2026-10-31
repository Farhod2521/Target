"""One campaign's page: the campaign, its figures, its adverts, its history, in one answer.

The browser used to ask six endpoints for this page and read the figures
back out of their words; it asks this one now, which carries the numbers.
"""

from typing import Any, Final

from sqlalchemy.orm import Session

from app.common.contract import money, zero_or
from app.modules.accounts.models import User
from app.modules.ads.contract.listing import access_of
from app.modules.ads.contract.tree import campaign_tree
from app.modules.ads.contract.words import (
    Kind,
    audience_of,
    controls_of,
    goal_of,
    kind_of,
    learning_of,
    network_of,
    place_of,
    status_of,
    status_word,
)
from app.modules.audit.constants import ActionStatus, ActionType, ActorType

# The creatives report names the result outright; it wins over the objective.
REPORT_KINDS: Final[dict[str, Kind]] = {
    "lead": "lead",
    "chat": "chat",
    "call": "call",
    "view": "view",
    "click": "click",
    "recall": "view",
    "profile": "profile",
    "site_lead": "site",
}
HISTORY_WORDS: Final[dict[str, str]] = {
    ActionType.PAUSE: "To'xtatildi",
    ActionType.RESUME: "Yoqildi",
    ActionType.BUDGET_UP: "Kunlik byudjet",
    ActionType.BUDGET_DOWN: "Kunlik byudjet",
    ActionType.TARGETING_SWAP: "Auditoriya o'zgartirildi",
    ActionType.END_TIME_SET: "Tugash sanasi",
    ActionType.SPEND_CAP_SET: "Umumiy chegara",
    ActionType.CREATIVE_SWAP: "Yangi reklama",
    ActionType.CREATE_ADSET: "Yangi guruh",
    ActionType.CREATE_AD: "Yangi reklama",
    ActionType.DELETE_CAMPAIGN: "O'chirildi",
    ActionType.DELETE_ADSET: "O'chirildi",
    ActionType.DELETE_AD: "O'chirildi",
}
HISTORY_ACTORS: Final[dict[str, str]] = {
    ActorType.USER: "you",
    ActorType.AGENT: "system",
    ActorType.SYSTEM: "system",
}
HISTORY_STATUSES: Final[dict[str, str]] = {
    ActionStatus.APPLIED: "applied",
    ActionStatus.FAILED: "failed",
    ActionStatus.PENDING: "pending",
    ActionStatus.REVERTED: "cancelled",
}
NOTE_TONES: Final[dict[str, str]] = {
    "warn": "warn",
    "warning": "warn",
    "danger": "danger",
    "error": "danger",
    "bad": "danger",
}
COST_KEYS: Final = ("cpl", "platform_cpl", "cpc", "cpm")
RESULT_KEYS: Final = ("leads", "leads_reported", "link_clicks", "clicks")


def panel_of(panel: Any) -> dict[str, Any]:
    """The owner's chosen figures, period by period."""
    return {
        "has_choice": panel.has_choice,
        "has_figures": panel.has_figures,
        "note": str(panel.note) or None,
        "periods": [
            {
                "key": period.key,
                "label": period.label,
                "empty": period.is_empty,
                "cards": [
                    {
                        "key": card.key,
                        "label": card.label,
                        "display": card.display,
                        "trend": card.trend,
                        "delta_pct": card.delta_pct,
                        "good": card.is_good,
                        "hint": card.hint or None,
                        "basis_note": card.basis_note or None,
                    }
                    for group in period.groups
                    for card in group.cards
                ],
                "series": [
                    {
                        "key": series.key,
                        "label": series.label,
                        "labels": [point.label for point in series.points],
                        "values": [point.value or 0 for point in series.points],
                        "floor": series.floor,
                        "peak": series.peak,
                    }
                    for series in period.series
                ],
                "mismatch": str(period.mismatch) or None,
                "funnel": {
                    "heading": str(period.funnel_heading),
                    "lid": str(period.lid),
                    "steps": [
                        {
                            "label": step.label,
                            "value": step.value,
                            "share_pct": step.share_pct,
                            "note": step.note,
                        }
                        for step in period.funnel
                    ],
                }
                if period.funnel
                else None,
            }
            for period in panel.periods
        ],
    }


def stats_of(panel: Any, *, currency: str, provider: str) -> dict[str, Any] | None:
    """The page's hero figures: the panel's seven days, as numbers."""
    period = next((p for p in panel.periods if p.key == "7"), None) or (
        panel.periods[0] if panel.periods else None
    )
    if period is None:
        return None
    cards = {card.key: card for group in period.groups for card in group.cards}
    cost = next((cards[key] for key in COST_KEYS if key in cards), None)
    spend = cards.get("spend")
    if cost is None or spend is None or cost.value is None or spend.value is None:
        return None
    results = next((cards[key] for key in RESULT_KEYS if key in cards), None)
    ctr = cards.get("ctr") or cards.get("link_ctr")
    return {
        "unit_cost": zero_or(int(cost.value), currency, provider=provider),
        "unit_cost_delta_pct": _signed(cost),
        "spent": zero_or(int(spend.value), currency, provider=provider),
        "results": int(results.value or 0) if results is not None else 0,
        "results_delta_pct": _signed(results),
        "impressions": int(cards["impressions"].value or 0)
        if "impressions" in cards
        else 0,
        # Basis points to a fraction: 190 is 1.9%, drawn from 0.019.
        "ctr": (ctr.value or 0) / 10_000 if ctr is not None else 0,
    }


def _signed(card: Any) -> int | None:
    if card is None or card.trend == "flat":
        return None
    return -abs(card.delta_pct) if card.trend == "down" else abs(card.delta_pct)


def creatives_of(report: Any, *, names: dict[str, str]) -> dict[str, Any] | None:
    if not report.has_cards:
        return None

    def cards(rows: Any) -> list[dict[str, Any]]:
        return [_creative(card, names=names) for card in rows]

    return {
        "since": report.since.isoformat() if report.since else "",
        "until": report.until.isoformat() if report.until else "",
        "average": report.average or None,
        "cost_label": str(report.cost_label),
        "result_heading": str(report.result_heading),
        "has_figures": report.has_figures,
        "alone": report.is_alone,
        "min_results": report.min_results,
        "best_results": report.best_results,
        "note": str(report.note) or None,
        "ranked": cards(report.ranked),
        "barren": cards(report.barren),
        "weak": cards(report.weak),
        "thin": cards(report.thin),
        "waiting": cards(report.waiting),
    }


def _creative(card: Any, *, names: dict[str, str]) -> dict[str, Any]:
    external_id = card.ad_external_id or card.external_id
    social = card.reactions or card.comments or card.shares or card.saves
    quality = card.quality or card.engagement or card.conversion
    return {
        "external_id": external_id,
        "place": card.place or None,
        "name": names.get(external_id),
        "thumb": card.thumbnail_url or None,
        "headline": card.headline,
        "message": card.message,
        "status": status_word(card.delivery) if card.delivery else None,
        "kind_label": card.kind_label or None,
        "own_leads": card.own_leads,
        "results": card.results,
        "cost": card.cost or None,
        "verdict": str(card.verdict) or None,
        "spend": card.spend,
        "spend_share": card.spend_share,
        "impressions": card.impressions,
        "link_clicks": card.link_clicks,
        "link_ctr": card.link_ctr or None,
        "days": card.days,
        "social": {
            "reactions": card.reactions,
            "comments": card.comments,
            "shares": card.shares,
            "saves": card.saves,
        }
        if social
        else None,
        "quality": {
            "creative": card.quality or None,
            "engagement": card.engagement or None,
            "conversion": card.conversion or None,
        }
        if quality
        else None,
        "watch": {
            "plays": card.plays,
            "points": [
                {"at": point.at_pct, "share": point.share_pct} for point in card.watch
            ],
        }
        if card.plays and card.watch
        else None,
        "missing": card.is_missing or None,
    }


def history_row(row: Any) -> dict[str, Any]:
    log = row.log
    words = HISTORY_WORDS.get(log.action, log.action)
    moment = log.applied_at or log.created_at
    return {
        "id": str(log.id),
        "text": " ".join(part for part in (words, row.amount) if part),
        "at": moment.isoformat() if moment else "",
        "by": HISTORY_ACTORS.get(log.actor_type, "system"),
        "note": log.reason or None,
        "level": row.level_label or None,
        "status": HISTORY_STATUSES.get(log.status, "pending"),
        "dry_run": log.dry_run or None,
    }


def campaign_detail(
    db: Session,
    *,
    owner: User,
    campaign: Any,
    groups: list[Any],
    history: list[Any],
    chips: dict[str, Any],
) -> dict[str, Any]:
    from app.modules.ads import selectors
    from app.modules.metrics.selectors.campaign_panel import campaign_panel
    from app.modules.metrics.selectors.creative_report import creative_report

    settings = campaign.settings
    currency = settings.currency or campaign.currency or campaign.ad_account.currency
    provider = campaign.provider
    report = creative_report(db, owner=owner, campaign=campaign)
    panel = campaign_panel(db, owner=owner, campaign=campaign)
    objective = campaign.objective_raw or ""
    kind = REPORT_KINDS.get(str(report.kind)) or kind_of(goal_of(objective), objective)
    goal = goal_of(objective)
    if goal == "other":
        goal = goal_of(kind)
    early = int(getattr(campaign, "early_hours", 0) or 0)
    learning = learning_of(early)
    tree = campaign_tree(groups, chips=chips)
    ads = [ad for group in tree["groups"] for ad in group["ads"]]
    audience = settings.audience or (
        selectors.group_settings(adset=groups[0], campaign=campaign).audience
        if groups
        else None
    )
    built = selectors.built_campaign_type(campaign=campaign)
    event = selectors.built_conversion_event(campaign=campaign)
    issue = getattr(campaign, "issue_summary", "")
    daily = (
        campaign.daily_budget_minor
        if campaign.daily_budget_minor is not None
        else settings.daily_budget_minor
        if settings.daily_budget_minor is not None
        else sum(group.daily_budget_minor or 0 for group in groups)
    )
    starts = settings.starts_at or (groups[0].start_time if groups else None)
    return {
        "id": str(campaign.id),
        "name": campaign.name,
        "kind": kind,
        "goal": goal,
        "status": status_of(campaign, learning=learning is not None),
        "network": network_of(provider),
        "parent_name": campaign.name,
        "daily_budget": zero_or(daily, currency, provider=provider),
        "audience": audience_of(audience),
        "ends_at": settings.ends_at.isoformat() if settings.ends_at else None,
        "learning": learning,
        "problem": {"text": issue, "fix": ""} if issue else None,
        "stats": stats_of(panel, currency=currency, provider=provider),
        "daily": None,
        "ads": ads,
        "notes": [
            note
            for note in (
                _note(item) for item in getattr(campaign, "recommendations", [])
            )
            if note is not None
        ],
        "settings": {
            "type_en": (built.provider_goal_label or built.provider_label)
            if built
            else objective,
            "result_event": (event.provider_label or str(event.label)) if event else "",
            "place": place_of(audience),
            "starts_at": starts.isoformat() if starts else None,
            "limit": money(
                campaign.spend_cap_minor or None, currency, provider=provider
            ),
            "form": None,
        },
        "groups": [
            {
                "id": str(group.id),
                "external_id": group.external_id,
                "name": group.name,
                "daily_budget": zero_or(
                    group.daily_budget_minor,
                    group.currency or currency,
                    provider=provider,
                ),
                "status": status_of(group, learning=bool(group.is_learning)),
                "controls": controls_of(
                    getattr(group, "controls", None),
                    early_hours=getattr(group, "early_hours", 0),
                ),
                "min_budget": zero_or(
                    getattr(getattr(group, "controls", None), "floor_minor", 0),
                    group.currency or currency,
                    provider=provider,
                ),
            }
            for group in groups
        ]
        if len(groups) > 1
        else None,
        "history": [history_row(row) for row in history],
        "controls": controls_of(getattr(campaign, "controls", None), early_hours=early),
        "access": access_of(db, owner=owner),
        "panel": panel_of(panel),
        "creatives": creatives_of(
            report,
            names={ad["external_id"]: ad["name"] for ad in ads if ad["name"]},
        ),
    }


def _note(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    text = next(
        (
            item[key]
            for key in ("text", "message", "summary", "title")
            if isinstance(item.get(key), str) and item[key]
        ),
        None,
    )
    if text is None:
        return None
    tone = str(item.get("tone") or item.get("level") or "").lower()
    return {
        "tone": NOTE_TONES.get(tone, "reco"),
        "text": text,
        "where": str(item.get("where") or "") or None,
    }


__all__ = [
    "campaign_detail",
    "creatives_of",
    "history_row",
    "panel_of",
    "stats_of",
]
