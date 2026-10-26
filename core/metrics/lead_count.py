"""The one lead count every screen, report, card, rule and answer uses.

**The provider's count wherever it has read the figures.** It is what Ads
Manager prints, and an owner who finds a different number here than there
stops trusting both - whatever the reason for the difference, a webhook a
minute late or a lead either side of midnight. Ours stands in only where the
provider has nothing yet: a day not read, or an account connected before any
figures arrived.

**One exception, and it is a question rather than a figure:** "has this
group brought anything at all today". The provider counts a lead some
minutes after we receive it, so a rule that stops or warns about a group on
the unfinished day asks :func:`heard_leads` - either side having seen one is
enough to hold off. Nothing shows that number to anybody.
"""


def measured(*, spend_minor: int, impressions: int, reported: int) -> bool:
    """Whether the provider has read these figures at all."""
    return bool(spend_minor or impressions or reported)


def counted_leads(*, ours: int, reported: int, measured: bool) -> int:
    """The lead count to show and to price by."""
    return reported if measured else ours


def heard_leads(*, ours: int, reported: int) -> int:
    """Whether any lead came, by either count. Only for today's stop and warn."""
    return max(ours, reported)


__all__ = ["counted_leads", "heard_leads", "measured"]
