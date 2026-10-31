"""The answers of ``/api/v2/campaigns``: version 1's, with what it could not say."""

from typing import Literal

from pydantic import Field

from app.common.contract import Camel
from app.modules.ads.contract.shapes import CampaignList, ListedCampaign, ManagerRow
from app.modules.ads.contract.words import Kind

KindV2 = Literal[Kind, "conversion", "recall", "other"]


class ListedCampaignV2(ListedCampaign):
    kind: KindV2  # type: ignore[assignment]
    result_label: str | None = Field(
        None, description="What a `conversion` result is, in words."
    )


class CampaignListV2(CampaignList):
    campaigns: list[ListedCampaignV2]  # type: ignore[assignment]


class ManagerRowV2(ManagerRow):
    kind: KindV2  # type: ignore[assignment]
    result_label: str | None = Field(
        None, description="What a `conversion` result is, in words."
    )
    reach: int | None = Field(  # type: ignore[assignment]
        description="People reached; null when Meta was not asked about these days."
    )
    clicks: int = Field(description="Link clicks; `clicks / impressions` is link CTR.")


class ManagerDataV2(Camel):
    campaigns: list[ManagerRowV2]
    adsets: list[ManagerRowV2]
    ads: list[ManagerRowV2]


__all__ = [
    "CampaignListV2",
    "KindV2",
    "ListedCampaignV2",
    "ManagerDataV2",
    "ManagerRowV2",
]
