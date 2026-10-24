"""One advert inside a group, as the agent sees it."""

from dataclasses import dataclass

from core.metrics import SegmentFigures

_ACTIVE = "active"
_REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class AdFacts:
    """One advert inside a group, as the window saw it."""

    name: str
    delivery: str
    figures: SegmentFigures
    days_with_spend: int = 0
    quality_ranking: str = ""
    engagement_ranking: str = ""
    conversion_ranking: str = ""
    issue_codes: tuple[str, ...] = ()
    issue_summary: str = ""
    refusal: str = ""
    creative_kind: str = ""
    image_hash: str = ""
    video_id: str = ""
    headline: str = ""
    message: str = ""
    link_clicks: int = 0
    landing_page_views: int = 0
    video_views_3s: int = 0
    leads: int = 0

    @property
    def external_id(self) -> str:
        """The provider's id for this advert - the cut's own slice name."""
        return self.figures.segment

    @property
    def is_active(self) -> bool:
        """Whether it is delivering. A stopped advert is not in the mix."""
        return self.delivery == _ACTIVE

    @property
    def in_window(self) -> bool:
        """Whether it spent on any day of the window."""
        return (
            self.days_with_spend > 0
            or self.figures.spend_minor > 0
            or self.figures.impressions > 0
        )

    @property
    def is_faulted(self) -> bool:
        """Whether the provider has stopped this advert over a fault or a policy."""
        return self.delivery == _REJECTED and bool(self.issue_codes or self.refusal)


@dataclass(frozen=True, slots=True)
class LibraryImage:
    """One picture the ad account holds itself, as a new creative names it."""

    asset_id: str
    image_hash: str
    name: str = ""


__all__ = ["AdFacts", "LibraryImage"]
