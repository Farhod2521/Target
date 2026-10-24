"""Turning the domain's intent into the rule document Meta wants."""

from typing import Any, Final

from adskit.dto import AudienceRuleDTO, RuleSupportDTO
from adskit.refs import AudienceAction, AudienceSource

SOURCE_TYPES: Final[dict[AudienceSource, str]] = {
    "pixel": "pixel",
    "page": "page",
    "lead_form": "lead",
}

EVENTS: Final[dict[tuple[AudienceSource, AudienceAction], str]] = {
    ("pixel", "visited"): "PageView",
    ("pixel", "visited_not_purchased"): "PageView",
    ("pixel", "viewed_item"): "ViewContent",
    ("pixel", "added_to_cart"): "AddToCart",
    ("pixel", "added_to_cart_not_purchased"): "AddToCart",
    ("pixel", "purchased"): "Purchase",
    ("page", "engaged"): "page_engaged",
    ("page", "engaged_not_messaged"): "page_engaged",
    ("page", "visited"): "page_visited",
    ("page", "messaged"): "page_messaged",
    ("lead_form", "opened"): "lead_generation_opened",
    ("lead_form", "submitted"): "lead_generation_submitted",
    ("lead_form", "abandoned"): "lead_generation_dropoff",
}

EXCLUDED_EVENTS: Final[dict[tuple[AudienceSource, AudienceAction], str]] = {
    ("pixel", "visited_not_purchased"): "Purchase",
    ("pixel", "added_to_cart_not_purchased"): "Purchase",
    ("page", "engaged_not_messaged"): "page_messaged",
}

EVENT_OPERATOR: Final = "eq"

EVENT_FIELD: Final = "event"

MAX_RETENTION_DAYS: Final[dict[AudienceSource, int]] = {
    "pixel": 365,
    "page": 730,
    "lead_form": 90,
}

SECONDS_PER_DAY: Final = 86_400


def supported_rules() -> list[RuleSupportDTO]:
    """What Meta will build, derived from the table rather than repeated."""
    actions: dict[AudienceSource, list[AudienceAction]] = {}
    for kind, action in EVENTS:
        actions.setdefault(kind, []).append(action)

    return [
        RuleSupportDTO(
            kind=kind,
            actions=tuple(found),
            max_retention_days=MAX_RETENTION_DAYS[kind],
        )
        for kind, found in actions.items()
    ]


def event_of(rule: AudienceRuleDTO) -> str:
    """Meta's own word for what this rule gathers on."""
    return EVENTS.get((rule.kind, rule.action), "")


def excluded_event_of(rule: AudienceRuleDTO) -> str:
    """Meta's own word for who this rule takes back out. Empty for most."""
    return EXCLUDED_EVENTS.get((rule.kind, rule.action), "")


def rule_document(rule: AudienceRuleDTO) -> dict[str, Any]:
    """The rule as Meta reads it."""
    kind = rule.kind
    event = EVENTS.get((kind, rule.action))
    if event is None:
        raise ValueError(f"Meta builds no audience from {kind!r} + {rule.action!r}")

    document: dict[str, Any] = {"inclusions": _block(rule=rule, event=event)}

    excluded = EXCLUDED_EVENTS.get((kind, rule.action))
    if excluded is not None:
        document["exclusions"] = _block(rule=rule, event=excluded)

    return document


def _block(*, rule: AudienceRuleDTO, event: str) -> dict[str, Any]:
    """One side of the document. Both sides have this shape exactly."""
    return {
        "operator": "or",
        "rules": [
            {
                "event_sources": [
                    {"id": rule.source.id, "type": SOURCE_TYPES[rule.kind]}
                ],
                "retention_seconds": rule.retention_days * SECONDS_PER_DAY,
                "filter": {
                    "operator": "and",
                    "filters": [
                        {
                            "field": EVENT_FIELD,
                            "operator": EVENT_OPERATOR,
                            "value": event,
                        }
                    ],
                },
            }
        ],
    }


__all__ = [
    "EVENTS",
    "EVENT_FIELD",
    "EVENT_OPERATOR",
    "EXCLUDED_EVENTS",
    "MAX_RETENTION_DAYS",
    "SECONDS_PER_DAY",
    "SOURCE_TYPES",
    "event_of",
    "excluded_event_of",
    "rule_document",
    "supported_rules",
]
