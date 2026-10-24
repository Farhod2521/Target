"""Turning the domain's intent into the rule document Meta wants.

The third use of the split ``META_CURRENCY_PLACES`` established: the shape
belongs to ``adskit``, the provider's own table belongs here. What crosses
the boundary is four domain words - which thing, what people did with it,
how far back - and everything Meta-shaped is assembled in this file and
nowhere else.

Four things about that document would each have been wrong if guessed at,
and all four follow the v26.0 guides:

* **``subtype`` is not sent.** Meta stopped supporting it for website and
  engagement audiences in September 2018. The rule alone decides what the
  audience is, and Meta *derives* the subtype it reports back. Sending one
  is at best ignored.
* **The source type for a lead form is ``lead``.** Not ``lead_gen_form``,
  which is the name the product's own vocabulary would suggest and which
  Meta does not know.
* **An event is matched with ``eq``, on every source.** The audience-rules
  reference is explicit - *"if ``field`` set to ``event``, must use
  ``=``"* - and lists ``eq`` as its spelling. The website guide's
  ``i_contains`` examples are not a second rule for pixels: their values
  are ``SignUp`` and ``ViewProduct``, which are *custom* event names, and
  partial matching is the point of them. On a standard event it is only a
  way to catch more than was asked for.
* **The window lives inside the rule, as seconds.** The top-level
  ``retention_days`` parameter is capped at 180 days and is *not sent* -
  Meta's own guide says it is taken from ``retention_seconds`` when
  absent, and the per-source maxima below run past 180.

``prefill`` is also not sent, and that is a decision rather than an
omission. It exists for website audiences only, its documented default is
``true`` - which is what a retargeting audience wants, since the whole
point is the history - and the two sentences describing its default
contradict each other. Sending nothing takes the documented default and
leaves nothing to be wrong about.

**Subtraction is one action, spelled as two blocks.** Meta's format puts
``exclusions`` beside ``inclusions`` with exactly the same shape, and
:data:`EXCLUDED_EVENTS` says which actions produce one. Both blocks always
name the *same source* and carry the *same window*: no documented example
mixes source types, and a document whose two halves looked back different
distances would answer a question nobody asked - "visited in the last
month and did not buy in the last year" is not a sentence a picker can put
on a screen honestly.
"""

from typing import Any, Final

from adskit.dto import AudienceRuleDTO, RuleSupportDTO
from adskit.refs import AudienceAction, AudienceSource

# Meta's own word for each source the domain names.
#
# Two of the three happen to match and the third does not, which is exactly
# why the table exists rather than a ``.lower()`` call: ``lead_form`` is the
# obvious spelling, it is the one this product uses everywhere else, and
# Meta calls it ``lead``.
SOURCE_TYPES: Final[dict[AudienceSource, str]] = {
    "pixel": "pixel",
    "page": "page",
    "lead_form": "lead",
}

# What Meta gathers, per (source, action). The right-hand side is Meta's
# vocabulary and stops here.
#
# The pixel rows are the standard-event names its own snippet fires; the
# other two sources use Meta's documented engagement events. A pair absent
# from this table is a pair Meta does not offer, and :func:`supported_rules`
# is built from the keys so the two can never disagree.
#
# Ordered the way the picker shows it: each subtracting action sits directly
# under the action it narrows, so "Kirganlar" and "Kirgan, xarid qilmagan"
# are neighbours rather than opposite ends of a list.
EVENTS: Final[dict[tuple[AudienceSource, AudienceAction], str]] = {
    ("pixel", "visited"): "PageView",
    ("pixel", "visited_not_purchased"): "PageView",
    ("pixel", "viewed_item"): "ViewContent",
    ("pixel", "added_to_cart"): "AddToCart",
    ("pixel", "added_to_cart_not_purchased"): "AddToCart",
    ("pixel", "purchased"): "Purchase",
    ("page", "engaged"): "page_engaged",
    ("page", "engaged_not_messaged"): "page_engaged",
    ("page", "visited"): "page_visited",
    ("page", "messaged"): "page_messaged",
    ("lead_form", "opened"): "lead_generation_opened",
    ("lead_form", "submitted"): "lead_generation_submitted",
    ("lead_form", "abandoned"): "lead_generation_dropoff",
}

# What Meta takes back out again, for the actions that subtract. Absent
# means the audience only ever grows, which is every other action here.
#
# Three, and each one is the second half of a sentence a business says out
# loud. ``page_engaged`` is documented as *"the most inclusive engagement
# type"* which *"includes all other types of engagement"* - so subtracting
# ``page_messaged`` from it leaves the people who dealt with the page and
# never wrote, which is the audience a business that lives on messages
# wants to reach.
#
# **No lead-form row, and that is a finding rather than a gap.** "Opened it
# and did not send it" is not built here because Meta already ships it as
# one event - ``lead_generation_dropoff`` - and building it out of two
# blocks would be the same audience by a longer road.
#
# Every key must also be a key of :data:`EVENTS`: the entry above says who
# goes in, this one says who comes back out, and a subtraction with nothing
# to subtract from is an audience of nobody.
EXCLUDED_EVENTS: Final[dict[tuple[AudienceSource, AudienceAction], str]] = {
    ("pixel", "visited_not_purchased"): "Purchase",
    ("pixel", "added_to_cart_not_purchased"): "Purchase",
    ("page", "engaged_not_messaged"): "page_messaged",
}

# How Meta compares the event. One value for every source, and it is the
# one the reference requires when the field is ``event``.
#
# A constant rather than a per-source table. One value repeated three times
# would be a worse lie than a wrong value: it promises the comparison
# varies by source when nothing in the documentation says it does. And
# ``i_contains`` - the spelling the website guide's custom-event examples
# suggest - matches more than was asked for: ``i_contains "Purchase"`` also
# matches a custom ``SubscriptionPurchase``, which on the subtracting side
# silently removes people who never bought anything.
EVENT_OPERATOR: Final = "eq"

# What Meta calls the field being matched. One value for every source here,
# named rather than inlined because the website guide documents a second
# one - ``url`` - that this product does not offer: a URL fragment is a
# media buyer's tool, and the standard events say the same thing in words a
# business owner already uses.
EVENT_FIELD: Final = "event"

# How far back Meta will look, per source, in days. Three different numbers
# and the differences are large - a single figure would be wrong for two of
# them, in the direction that produces a refusal after somebody has filled
# in a form.
#
# One cap covers both halves of a subtracting rule, which is what makes the
# single window honest: the two blocks name the same source, so whatever
# limits one limits the other.
MAX_RETENTION_DAYS: Final[dict[AudienceSource, int]] = {
    "pixel": 365,
    "page": 730,
    "lead_form": 90,
}

SECONDS_PER_DAY: Final = 86_400


def supported_rules() -> list[RuleSupportDTO]:
    """What Meta will build, derived from the table rather than repeated.

    Built by walking :data:`EVENTS` so a pair that exists in one place and
    not the other is impossible. A hand-written second list is the shape of
    bug that offers somebody a choice the create call then refuses.

    Ordered, and the order is the one the picker shows: sources in the
    order a business meets them, actions from weakest signal to strongest.
    Python keeps insertion order, so the table above is the sort key.

    The subtracting actions are in here beside the rest and are not marked
    as different. They are not different to a caller: one value, one
    source, one window.
    """
    actions: dict[AudienceSource, list[AudienceAction]] = {}
    for kind, action in EVENTS:
        actions.setdefault(kind, []).append(action)

    return [
        RuleSupportDTO(
            kind=kind,
            actions=tuple(found),
            max_retention_days=MAX_RETENTION_DAYS[kind],
        )
        for kind, found in actions.items()
    ]


def event_of(rule: AudienceRuleDTO) -> str:
    """Meta's own word for what this rule gathers on.

    Carried back to the caller beside the domain's words so the mirror can
    keep both, which is the split every status column in this package
    makes: a screen needs a word nobody has to look up, and an operator
    comparing against Ads Manager needs Meta's.

    Empty for a pair Meta does not build. Empty rather than a refusal
    because this is only ever asked *after* the rule was accepted - the
    refusal belongs to :func:`rule_document`, which is the function that
    would have to send it.
    """
    return EVENTS.get((rule.kind, rule.action), "")


def excluded_event_of(rule: AudienceRuleDTO) -> str:
    """Meta's own word for who this rule takes back out. Empty for most.

    Empty is an answer here, not a missing one: nearly every action only
    ever gathers, and a caller storing this beside :func:`event_of` is
    storing "nobody is excluded" rather than "not known". The two cases
    cannot be confused because there is no third state - a rule either
    subtracts or it does not, and this table is what decides.
    """
    return EXCLUDED_EVENTS.get((rule.kind, rule.action), "")


def rule_document(rule: AudienceRuleDTO) -> dict[str, Any]:
    """The rule as Meta reads it.

    One inclusion holding one rule, and beside it an ``exclusions`` block
    of the same shape when the action subtracts. Meta's format allows far
    more than this - several rules combined with ``or``, sources mixed
    inside one document, a different window on either side - and all of it
    is real work an advertiser does in Ads Manager. Offering it here would
    mean a screen with boolean algebra on it, which is the vocabulary this
    product exists to avoid. What is offered instead is a short list of
    finished sentences.

    ``operator: "or"`` on a single rule rather than ``and``, because the
    two are identical for one rule and ``or`` is what Meta's own examples
    show - a document that matches its documentation is one somebody can
    compare against a doc page when it is refused.
    """
    kind = rule.kind
    event = EVENTS.get((kind, rule.action))
    if event is None:
        # Unreachable through the domain, which checks against
        # :func:`supported_rules` before it builds one of these. A
        # programming error rather than a refusal, so it names both halves:
        # the pair is the only thing worth knowing here.
        raise ValueError(f"Meta builds no audience from {kind!r} + {rule.action!r}")

    document: dict[str, Any] = {"inclusions": _block(rule=rule, event=event)}

    excluded = EXCLUDED_EVENTS.get((kind, rule.action))
    if excluded is not None:
        # Same source, same window. The key is absent rather than empty for
        # every other action: Meta reads an ``exclusions`` block with no
        # rules in it as a malformed document, not as "exclude nobody".
        document["exclusions"] = _block(rule=rule, event=excluded)

    return document


def _block(*, rule: AudienceRuleDTO, event: str) -> dict[str, Any]:
    """One side of the document. Both sides have this shape exactly."""
    return {
        "operator": "or",
        "rules": [
            {
                "event_sources": [
                    {"id": rule.source.id, "type": SOURCE_TYPES[rule.kind]}
                ],
                "retention_seconds": rule.retention_days * SECONDS_PER_DAY,
                "filter": {
                    "operator": "and",
                    "filters": [
                        {
                            "field": EVENT_FIELD,
                            "operator": EVENT_OPERATOR,
                            "value": event,
                        }
                    ],
                },
            }
        ],
    }


__all__ = [
    "EVENTS",
    "EVENT_FIELD",
    "EVENT_OPERATOR",
    "EXCLUDED_EVENTS",
    "MAX_RETENTION_DAYS",
    "SECONDS_PER_DAY",
    "SOURCE_TYPES",
    "event_of",
    "excluded_event_of",
    "rule_document",
    "supported_rules",
]
