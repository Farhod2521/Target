"""The steps money passes through on its way to becoming a lead.

Shown, clicked, arrived, filled in. The diagnosis reads which step people
stopped at, and these two values are everything it is allowed to look at
below the ad set's own totals.

Apart from :class:`core.metrics.Totals` on purpose. ``Totals`` answers
"what did it cost" and is drawn on every screen; these answer "where did
people stop", which only the diagnosis asks. Every figure is a count summed
over the window, so a rate between two steps is one division of two sums
and never the mean of daily rates.
"""

from dataclasses import dataclass


def per_ten_thousand(*, part: int, whole: int) -> int | None:
    """``part`` per ten thousand of ``whole``, or nothing to divide by.

    The unit :func:`core.agent.facts.ctr_bp` uses, for the same reason: the
    rates here live near one percent, and a whole percentage cannot tell a
    healthy step from one that lost half its people.
    """
    if whole <= 0:
        return None
    return round(part * 10_000 / whole)


@dataclass(frozen=True, slots=True)
class Funnel:
    """One ad set's window, one count per step.

    The provider's counts only. The lead count is not here: which of ours
    and the provider's to trust is a decision the diagnosis makes, and
    ``Totals`` already carries both.
    """

    spend_minor: int = 0
    impressions: int = 0
    # Clicks that went where the money was sent. See ``Half.link_clicks``.
    link_clicks: int = 0
    # Link clicks whose page finished loading. Nought wherever the page
    # carries no pixel, which is a fact about the site and not about its
    # visitors - see ``Landing.pixel_seen``.
    landing_page_views: int = 0
    # A play starts the moment a video is on screen; a three-second view is
    # somebody who stopped scrolling. Both nought on an image advert.
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
        """Three-second views per ten thousand impressions, on a video only.

        Nothing on an image advert rather than nought: an image cannot fail
        to hold somebody for three seconds, and a nought here would read as
        the weakest opening in the account.
        """
        if self.video_plays <= 0:
            return None
        return per_ten_thousand(part=self.video_views_3s, whole=self.impressions)

    @property
    def arrival_bp(self) -> int | None:
        """How many of every ten thousand link clicks reached a loaded page."""
        return per_ten_thousand(part=self.landing_page_views, whole=self.link_clicks)


@dataclass(frozen=True, slots=True)
class Landing:
    """What a click lands on, for the adverts this group is delivering.

    Current state rather than a window, like the site check and the form
    it is read from: a page is down now or it opened last night.
    """

    # Pages a delivering advert links to that did not open on the last
    # look, and would not have opened for anybody - a timeout on our side
    # is not here. See ``apps.ads.models.SiteCheck.is_down``.
    down_urls: tuple[str, ...] = ()
    # Whether any page looked at carries the provider's pixel. Without one,
    # nought arrivals says nothing about how many people arrived.
    pixel_seen: bool = False
    # The most questions any delivering advert's form asks. Nought for a
    # group with no form, and for a form whose questions were never read.
    form_questions: int = 0


__all__ = ["Funnel", "Landing", "per_ten_thousand"]
