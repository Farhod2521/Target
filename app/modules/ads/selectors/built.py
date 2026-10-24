"""What a mirrored campaign was built as, read back from its ad sets."""

from dataclasses import dataclass
from typing import Any

from app.modules.ads.constants import CAMPAIGN_TYPE_LABELS, CONVERSION_EVENT_LABELS
from app.modules.ads.models import Campaign
from core.targeting import EVENT_KEY, conversion_event, type_built_as


@dataclass(frozen=True, slots=True)
class BuiltCampaignType:
    label: Any
    provider_label: str
    provider_goal_label: str


def built_campaign_type(*, campaign: Campaign) -> BuiltCampaignType | None:
    rows = {
        type_built_as(
            provider=campaign.provider,
            objective=campaign.objective_raw,
            destination_type=adset.destination_type_raw,
            optimization_goal=adset.optimization_goal_raw,
        )
        for adset in campaign.adsets
    }
    if len(rows) != 1:
        return None
    row = rows.pop()
    if row is None:
        return None
    return BuiltCampaignType(
        label=CAMPAIGN_TYPE_LABELS.get(row.key, row.key),
        provider_label=row.provider_label,
        provider_goal_label=row.provider_goal_label,
    )


@dataclass(frozen=True, slots=True)
class BuiltConversionEvent:
    label: Any
    provider_label: str


def built_conversion_event(*, campaign: Campaign) -> BuiltConversionEvent | None:
    named = {
        str((adset.promoted_object_raw or {}).get(EVENT_KEY) or "")
        for adset in campaign.adsets
    }
    if len(named) != 1:
        return None
    found = conversion_event(provider=campaign.provider, key=named.pop())
    if found is None:
        return None
    return BuiltConversionEvent(
        label=CONVERSION_EVENT_LABELS.get(found.key, found.key),
        provider_label=found.provider_label,
    )
