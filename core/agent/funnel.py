"""The steps money passes through on its way to becoming a lead."""

from dataclasses import dataclass


def per_ten_thousand(*, part: int, whole: int) -> int | None:
    """``part`` per ten thousand of ``whole``, or nothing to divide by."""
    if whole <= 0:
        return None
    return round(part * 10_000 / whole)


@dataclass(frozen=True, slots=True)
class Funnel:
    """One ad set's window, one count per step."""

    spend_minor: int = 0
    impressions: int = 0
    link_clicks: int = 0
    landing_page_views: int = 0
    video_plays: int = 0
    video_views_3s: int = 0

    @property
    def cpm_minor(self) -> int | None:
        """What a thousand impressions cost, or nothing when none were bought."""
        if self.impressions <= 0:
            return None
        return round(self.spend_minor * 1_000 / self.impressions)

    @property
    def link_ctr_bp(self) -> int | None:
        """Link clicks per ten thousand impressions."""
        return per_ten_thousand(part=self.link_clicks, whole=self.impressions)

    @property
    def hook_bp(self) -> int | None:
        """Three-second views per ten thousand impressions, on a video only."""
        if self.video_plays <= 0:
            return None
        return per_ten_thousand(part=self.video_views_3s, whole=self.impressions)

    @property
    def arrival_bp(self) -> int | None:
        """How many of every ten thousand link clicks reached a loaded page."""
        return per_ten_thousand(part=self.landing_page_views, whole=self.link_clicks)


@dataclass(frozen=True, slots=True)
class Landing:
    """What a click lands on, for the adverts this group is delivering."""

    down_urls: tuple[str, ...] = ()
    pixel_seen: bool = False
    form_questions: int = 0


__all__ = ["Funnel", "Landing", "per_ten_thousand"]
