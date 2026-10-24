"""Whether a movement is larger than the noise underneath it.

A week is a short range and a small advertiser's week is a handful of
leads. Two leads becoming three is a fifty percent improvement by
arithmetic and nothing at all by evidence, and a product that says the
first thing teaches somebody to move a budget on a coin toss.

The rule is the one already written into
``core.metrics.segment_compare.MIN_SEGMENT_LEADS``: a count of events has a
relative standard error of about one over its square root. Comparing two
counts carries both errors, so a movement is only worth speaking about when
it exceeds their sum. At ten leads against ten that bar is roughly sixty
percent - high, and honestly so.

Deliberately the same arithmetic and not a rounder threshold. A second rule
about when a number means something would be a second source of truth about
the same question, and the two would disagree the week somebody needed
them to agree.
"""

from math import sqrt

# The smallest count a comparison may rest on at all. Below this the error
# is larger than any movement worth reporting, so the answer is not "the
# change is small" but "there is nothing here to compare".
MIN_WEEK_LEADS = 5


def noise_pct(*, now: int, before: int) -> int | None:
    """How large a movement has to be before it is not the counting error.

    ``None`` when either side has no events. That is not a bar of zero and
    not a bar of a hundred - it is the absence of a rate to compare, and a
    caller that treated it as a number would be comparing against something
    that was never measured.
    """
    if now <= 0 or before <= 0:
        return None
    return round(100 / sqrt(now) + 100 / sqrt(before))


def is_beyond_noise(
    *, percent: int, now: int, before: int, floor: int = MIN_WEEK_LEADS
) -> bool:
    """Whether a movement of ``percent`` is worth explaining.

    Both the floor and the error bar apply, and they are not the same test.
    The floor rejects a week nobody can say anything about; the error bar
    rejects a movement that is real arithmetic on counts too small to carry
    it. A single test would let four leads against forty pass on the
    strength of the forty.
    """
    if now < floor or before < floor:
        return False
    bar = noise_pct(now=now, before=before)
    return bar is not None and percent > bar
