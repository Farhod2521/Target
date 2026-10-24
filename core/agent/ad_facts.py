"""One advert inside a group, as the agent sees it.

Apart from :mod:`core.agent.facts` because an advert is now read for two
different things: as a slice of its group's money, which the advert cuts
compare, and as an object the provider can stop on its own - a picture it
cannot find, words it refused - which a fix is proposed for whatever the
group's figures say.
"""

from dataclasses import dataclass

from core.metrics import SegmentFigures

# The delivery states this module reads, spelled as ``adskit.Delivery``
# spells them. Rejected is the provider's stop: refused under a policy, or
# running with a fault it reported.
_ACTIVE = "active"
_REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class AdFacts:
    """One advert inside a group, as the window saw it.

    The first object below an ad set this package forms an opinion about,
    and it holds less than one deliberately: an advert has no budget, no
    audience and no learning stage of its own. All three belong to the
    group above it, which is why the only change proposable here is
    switching one off - and why doing that is a change to the *mix* rather
    than to what the group spends.

    ``figures`` is a :class:`~core.metrics.SegmentFigures` rather than a
    :class:`~core.metrics.Totals`, and the difference is the whole reason
    this exists: adverts inside one group are a **cut** of that group's
    money, the same shape as its age cells and its placements, so they are
    compared by the same arithmetic - see :func:`core.metrics.
    compare_segments`. ``figures.segment`` carries the advert's own id,
    which is what the comparison sorts and what the finding then names.
    """

    name: str
    delivery: str
    figures: SegmentFigures
    days_with_spend: int = 0
    # The provider's newest verdict on this advert against the ones it
    # competes with, in its own words: ``below_average_20`` and so on, or
    # ``unknown`` when it has not seen enough. Blank when nothing was read.
    quality_ranking: str = ""
    engagement_ranking: str = ""
    conversion_ranking: str = ""
    # What the provider says is wrong with this advert: its codes, and its
    # own words for the first of them. The words are English and are never
    # printed - they are read to decide the fix and to explain it.
    issue_codes: tuple[str, ...] = ()
    issue_summary: str = ""
    # Why the provider refused it under a policy, in its own words. Blank
    # for an advert nobody refused.
    refusal: str = ""
    # What the advert shows and says. The kind is the creative's -
    # ``image``, ``video`` or ``post`` - and the picture is named by what a
    # new creative would name it by.
    creative_kind: str = ""
    image_hash: str = ""
    video_id: str = ""
    headline: str = ""
    message: str = ""
    # The window's other steps for this advert alone.
    link_clicks: int = 0
    landing_page_views: int = 0
    video_views_3s: int = 0
    # Leads that reached this product from it. The provider's own count is
    # ``figures.leads_reported``, and the two are kept apart for the reason
    # :func:`core.agent.benchmark.lead_count` gives.
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
        """Whether it spent on any day of the window.

        The advert cuts compare only these. An advert that never delivered -
        new, or stopped by the provider before its first impression - is
        still one the agent can see and propose a fix for, and it has no
        share of the money to be compared on.
        """
        return (
            self.days_with_spend > 0
            or self.figures.spend_minor > 0
            or self.figures.impressions > 0
        )

    @property
    def is_faulted(self) -> bool:
        """Whether the provider has stopped this advert over a fault or a policy.

        The advert-level twin of :func:`troubled`, and it asks the same two
        things: something is reported, and the advert is not delivering.
        """
        return self.delivery == _REJECTED and bool(self.issue_codes or self.refusal)


@dataclass(frozen=True, slots=True)
class LibraryImage:
    """One picture the ad account holds itself, as a new creative names it.

    ``asset_id`` is this product's id for the library row - what the swap
    is asked for - and ``image_hash`` is the provider's, which is what an
    advert's creative is compared against.
    """

    asset_id: str
    image_hash: str
    name: str = ""


__all__ = ["AdFacts", "LibraryImage"]
