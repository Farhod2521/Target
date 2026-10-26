"""What Meta's answers look like once they have crossed the boundary.

Pydantic, and ``extra="ignore"`` rather than ``forbid``: Meta adds fields
to these payloads without announcing it, and a new one should not take an
account connection down. Missing fields are a different matter and still
fail, because that means the shape changed under us.

Nothing here holds a token that is not the subject of the object itself,
and no model has a ``__str__`` that would print one.

The rows themselves live in seven topical modules: ``connection_rows``,
``account_rows``, ``instagram_rows``, ``lead_rows``, ``campaign_rows``,
``creative_rows`` and ``audience_rows``, over the shared base in
``dto_base``. This module is
the import surface - ``from metaads.dto import CampaignRow`` works
whichever file the row is in, so no caller knows which one that is.
"""

from metaads.account_rows import (
    AdAccountDTO,
    InstagramAccountDTO,
    PageDTO,
    PageLocationDTO,
)
from metaads.audience_rows import (
    AudienceStateRow,
    CustomAudienceDataSourceRow,
    CustomAudienceRow,
    MemberUploadRow,
)
from metaads.campaign_rows import (
    AdSetRow,
    CampaignRow,
    IssueRow,
    RecommendationRow,
    ReviewFeedbackRow,
)
from metaads.connection_rows import (
    AccessTokenDTO,
    GranularScopeDTO,
    MediaDTO,
    PersonDTO,
    PixelDTO,
    PixelEventRow,
    TokenInfoDTO,
)
from metaads.creative_rows import AdRow, CreativeRow
from metaads.dto_base import MetaDTO
from metaads.instagram_rows import InstagramProfileDTO
from metaads.lead_rows import ConversionReceiptRow, LeadFormRow, LeadRow

__all__ = [
    "AccessTokenDTO",
    "AdAccountDTO",
    "AdRow",
    "AdSetRow",
    "AudienceStateRow",
    "CampaignRow",
    "ConversionReceiptRow",
    "CreativeRow",
    "CustomAudienceDataSourceRow",
    "CustomAudienceRow",
    "GranularScopeDTO",
    "InstagramAccountDTO",
    "InstagramProfileDTO",
    "IssueRow",
    "LeadFormRow",
    "LeadRow",
    "MediaDTO",
    "MemberUploadRow",
    "MetaDTO",
    "PageDTO",
    "PageLocationDTO",
    "PersonDTO",
    "PixelDTO",
    "PixelEventRow",
    "RecommendationRow",
    "ReviewFeedbackRow",
    "TokenInfoDTO",
]
