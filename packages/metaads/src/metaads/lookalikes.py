"""Turning "people like these" into the spec Meta wants.

The fourth use of the split ``META_CURRENCY_PLACES`` established, and the
one where the two sides are furthest apart. What crosses the boundary is
three domain words - which audience, how wide, which country. What Meta
reads is a ratio, a subtype string and a top-level id that is not part of
the spec at all.

Five things about this call would each have been wrong if guessed at, and
all five follow the v26.0 guides:

* **``subtype`` IS sent, and it is required.** This is the exact opposite
  of :mod:`metaads.audience_rules`, where sending one is at best ignored -
  which is why the note there is about website and engagement audiences
  rather than a rule about ``subtype``. Meta's own curl example for this
  call carries ``subtype=LOOKALIKE`` beside the name.
* **``origin_audience_id`` is a top-level field**, not a member of
  ``lookalike_spec``. The spec holds how wide and where; the seed is
  named outside it.
* **``origin_audience_id`` cannot be read back.** It is absent from the
  Custom Audience node's field list. What is readable is
  ``lookalike_spec`` on the child and ``lookalike_audience_ids`` on the
  seed - the parent can count its children and no child can name its
  parent. Anything this product wants to remember about which audience a
  lookalike came from, it has to write down itself.
* **``ratio`` runs 0.01 to 0.20**, in steps of 0.01 - twice as far as
  Meta's own interface offers. :data:`RATIOS` stops at the tenth, because
  a value Ads Manager will not show is a value nobody can check the result
  of anywhere.
* **``retention_days`` does not apply here at all.** Meta documents it as
  being for customer files only. The rule audiences omit it because it is
  capped below what their windows need; this omits it because there is
  nothing for it to mean.

``allow_international_seeds`` is not sent either, and that is a decision
rather than an omission. Its documented default is false, which means Meta
refuses when the seed holds fewer than a hundred people in the chosen
country. Sending true would instead build the audience out of whoever it
could find somewhere else - an audience for one country modelled on
another's customers, which nobody asked for and no screen could explain.
"""

from typing import Final

from adskit.dto import LookalikeSpecDTO
from adskit.refs import AudienceBreadth

# Meta's word for an audience built to resemble another. Sent, and required.
SUBTYPE_LOOKALIKE: Final = "LOOKALIKE"

# What each domain word is worth as a share of the country's population.
#
# The right-hand side is Meta's vocabulary and stops here. Three rungs out
# of the twenty the API accepts, and the three are not arbitrary: 0.01 and
# 0.05 are the two Meta names in its own interface (``similarity`` and
# ``reach``), and 0.10 is where its slider stops.
#
# Sent as ``ratio`` rather than as ``type``, even for the two that have a
# name. Two ways of saying the same thing would mean two code paths, and
# the third rung has no name to be said with - so one path, and the one
# that can express all three.
RATIOS: Final[dict[AudienceBreadth, float]] = {
    "closest": 0.01,
    "balanced": 0.05,
    "broad": 0.10,
}


def ratio_of(spec: LookalikeSpecDTO) -> str:
    """Meta's own number for this breadth, as text.

    Text, and the type is the point. Nothing in this project computes with
    this figure - it is the provider's spelling of a choice, kept beside
    the domain's word so an operator comparing against Ads Manager has the
    string Meta shows. The same split every status column here makes, and
    storing it as a float would invite arithmetic on somebody else's unit.

    Two decimal places always, so ``0.1`` and ``0.10`` cannot both appear
    for the same choice in a column somebody is scanning by eye.
    """
    return f"{RATIOS[spec.breadth]:.2f}"


def lookalike_spec(spec: LookalikeSpecDTO) -> dict[str, object]:
    """The spec as Meta reads it. Two keys, and the seed is not one of them.

    ``origin_audience_id`` belongs beside ``name`` in the request rather
    than in here - see :func:`metaads.audiences.create_lookalike_audience`,
    which is the only caller and sends both.

    ``country`` is upper-cased rather than trusted. Meta matches the code
    exactly and answers a lower-case one with a refusal that names the
    parameter and not the case, which is a confusing half-hour for whoever
    meets it.
    """
    return {
        "ratio": RATIOS[spec.breadth],
        "country": spec.country.strip().upper(),
    }


__all__ = ["RATIOS", "SUBTYPE_LOOKALIKE", "lookalike_spec", "ratio_of"]
