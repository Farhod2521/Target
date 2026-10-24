"""How an object on a provider is named.

A bare string is not enough. ``"120210000000000"`` alone cannot say which
provider issued it or what level it sits at, and both facts are needed to
route a call. Every id that crosses a boundary is wrapped.
"""

from dataclasses import dataclass
from typing import Final, Literal, NewType

# The registry key, not a display name. "meta", "google" - lowercase, stable,
# and written down in exactly one place per provider.
ProviderName = NewType("ProviderName", str)

# Money is an integer count of the currency's smallest unit, paired with a
# currency code wherever it is stored. Floats never touch a budget.
MinorUnits = NewType("MinorUnits", int)

# The object hierarchy every ad platform has some version of. Deliberately a
# closed set: a typo in a level string would otherwise route a call into
# nowhere and surface as a confusing 404 much later.
#
# "interest" and "location" are the odd two: they name rows in the
# provider's own catalogue rather than something an advertiser created. They
# belong here anyway - each has a provider, an id, and the same failure mode
# as everything else here, which is a bare string reaching a call that
# expected a different platform.
#
# "interest" is the whole detailed-targeting rung and not only the rows a
# platform files under that word. A behaviour and a life event are the same
# kind of thing at the same level - a catalogue row, with an id, that goes
# into a targeting spec - and which of the three a given row is, is carried
# by :data:`TraitKind` on the DTO rather than by a level of its own. Levels
# exist to stop an id reaching the wrong *call*, and all three reach the
# same one.
#
# "audience" is a saved list of people the advertiser owns, held by the
# provider and referred to from a targeting spec. Not part of the hierarchy
# above it and not under an ad set: several ad sets point at one, it
# outlives all of them, and it belongs to the account.
#
# "pixel" is the tag on the advertiser's own website. Here for the same
# reason "page" is: an audience can be built out of what people did at one,
# so its id crosses a boundary and must say which provider issued it.
#
# "lead" is one person the provider handed over. It is the odd one in a
# different way from "interest": the object was created by somebody filling
# in a form rather than by an advertiser, and this product refers to it
# afterwards for exactly one purpose - to tell the provider how that person
# turned out. See :class:`~adskit.dto.LeadEventDTO`.
#
# "dataset" is where those answers are sent. Every platform has one - Meta
# calls it a dataset, the object advertisers still call a pixel, and Google
# files the same thing under a conversion action - and it is not the same
# object as the "pixel" above even where a provider issues one id for both:
# that one is read as a *source* an audience can be built from, and this one
# is written to. Two levels because a ref carries what a call may do with it.
Level = Literal[
    "account",
    "campaign",
    "adset",
    "ad",
    "creative",
    "form",
    "page",
    "interest",
    "location",
    "audience",
    "pixel",
    "lead",
    "dataset",
]

# How far one lead got, in the domain's own words.
#
# Not a provider's vocabulary and deliberately not shaped like one. Meta
# takes an event name of the advertiser's choosing on a dataset; Google
# takes a conversion action name. Both are strings somebody invented, which
# is the strongest possible argument for naming the *meaning* here and
# letting each adapter spell it.
#
# Three, and the set is deliberately not "every stage a sales funnel has".
# What may be sent is bounded by what this product actually knows, and it
# knows exactly what somebody pressed a button to say:
#
#   qualified    the owner answered the phone and it was a real customer
#   unqualified  they answered and it was not
#   converted    money changed hands. Carries an amount; the other two
#                never do
#
# **"Received" is absent on purpose and its absence is the point.** The
# provider handed the lead over, so it already knows that one happened, and
# reporting it back would be telling a platform a fact it is the source of
# - which trains its optimiser on its own output. The only news this
# product has is the judgement.
LeadStage = Literal["qualified", "unqualified", "converted"]

# What sort of catalogue row a piece of detailed targeting is.
#
# Three, and the split is the provider's own rather than a taxonomy
# invented here - every platform draws the same line and for the same
# reason, which is that the three are *found* differently:
#
#   interest    searched by free text. An advertiser types a word and the
#               platform answers what it recognises, fuzzily, or nothing
#   behaviour   browsed from a closed list. What somebody has done -
#               travelled, shopped online, changed their telephone
#   life_event  browsed from a much shorter closed list. What has happened
#               to them - moved house, got engaged, started a new job
#
# The last one is the reason this vocabulary exists at all. A wedding hall,
# a removals firm and a mortgage broker have no interest worth targeting -
# nobody is "interested in" moving house - and their entire audience is one
# row in a list of about a dozen.
#
# **Browsed, not searched, and that is a better guarantee rather than a
# worse one.** A life event either is in the platform's fixed list or is
# not, so a name matched against it is matched exactly; an interest search
# is a ranked guess that has to be confirmed and can quietly return the
# wrong row.
TraitKind = Literal["interest", "behaviour", "life_event"]

# The two that are browsed. Named as a set so a caller can ask "is this one
# of the closed lists" without repeating the pair, and so the day a fourth
# class is offered the question has one place to change.
BROWSED_TRAITS: Final[frozenset[str]] = frozenset({"behaviour", "life_event"})

# How a provider files one place in its geography catalogue.
#
# The distinction that matters is not administrative, it is whether a radius
# may be drawn around the thing. A city is a point with a name, so "within
# 5 km of Tashkent" means something; a region is an outline, and a radius
# around it means nothing on any platform. "other" carries the entries a
# provider offers that this product does not model - a zip code, a media
# market - so that an unexpected row is visible rather than silently
# reclassified as a city.
GeoKind = Literal["city", "region", "country", "other"]

# Whether an object is actually delivering, in words the product can show.
#
# Providers answer this with a vocabulary of their own - Meta alone has a
# dozen effective statuses, and half of them describe the parent rather than
# the object. Translating that vocabulary is the adapter's job, because the
# adapter is the one place allowed to know it: a screen that branches on
# "CAMPAIGN_PAUSED" has hard-coded Meta into a template.
#
#   paused       - this object's own switch is off
#   paused_above - this object's own switch is **on** and something above it
#                  is off, so nothing is shown. A separate word because the
#                  two need opposite answers to every question that matters:
#                  which button to offer, what an undo would put back, and
#                  whether switching this one on would change anything at
#                  all. Providers already draw the distinction - Meta sends
#                  CAMPAIGN_PAUSED and ADSET_PAUSED, Google reports the
#                  parent's status on the child - and collapsing it into
#                  "paused" throws away the one fact a screen needs to stop
#                  offering a switch that is already in the position it
#                  would be moved to.
#   pending      - submitted and not yet delivering: under review, awaiting
#                  billing details, or scheduled to start later
#   rejected     - refused by the provider; needs the advertiser to act
#   finished     - ran and stopped on its own, by end date or budget
#
# A campaign is never "paused_above": nothing sits above it.
Delivery = Literal[
    "active",
    "paused",
    "paused_above",
    "pending",
    "rejected",
    "finished",
    "unknown",
]

# What a provider thinks of one ad against the ads it competes with.
#
# Three separate verdicts on Meta - the creative, the engagement it earns
# and the conversions it produces - and Google reports the same idea under
# its own names. The scale is comparative and not absolute: "average" means
# average among ads shown to the same audience, so the same ad can move
# without changing.
#
# The four "below average" steps are Meta's own granularity and are kept.
# Collapsing them into one "bad" would throw away the distinction that
# decides what to do: an ad in the bottom 35 percent is worth improving and
# one in the bottom 10 percent is worth replacing.
#
# Two values mean "no verdict" and they are not the same thing:
#
#   ""        - the provider was not asked. These fields exist only at the
#               ad level, so every campaign and ad set row carries this.
#   "unknown" - the provider was asked and has not seen enough impressions
#               to say. The normal answer for a new ad, and not an error.
Ranking = Literal[
    "",
    "above_average",
    "average",
    "below_average_10",
    "below_average_20",
    "below_average_35",
    "unknown",
]

# What an audience can be built out of, in the domain's own words.
#
# Not the provider's vocabulary and deliberately not shaped like it. Meta
# spells these ``pixel``, ``page`` and ``lead`` inside a rule document;
# Google would name a tag, a channel and a lead form. Naming the *thing the
# advertiser recognises* is what keeps a picker from being Meta's parameter
# list with a translation layer on top.
#
# Three, and each is a row this product already stores: a pixel, a Facebook
# page, a lead form. What is missing is missing for a reason rather than by
# oversight - see :class:`~adskit.dto.AudienceRuleDTO`.
AudienceSource = Literal["pixel", "page", "lead_form"]

# What the person did, in the domain's own words.
#
# One flat set rather than one per source, because the pairs that make
# sense are decided by the adapter that has to spell them - and a caller
# asking for a combination no provider offers gets a refusal naming both
# halves, which is more useful than a type error naming neither.
#
#   visited      - arrived, and nothing more is claimed. A page view on the
#                  website, a visit to the page's profile
#   viewed_item  - looked at one specific thing being sold
#   added_to_cart, purchased - the two steps that follow it
#   engaged      - did anything at all with the page: a reaction, a
#                  comment, a share, a click on the call to action
#   messaged     - started a conversation, which is the strongest signal a
#                  page produces and the one this product's customers live on
#   opened       - the lead form appeared on their screen
#   submitted    - they sent it. The people who became leads
#   abandoned    - they opened it and did not send it, which is the one
#                  retargeting audience that pays for itself immediately
#
# The last three are **one action each, not two.** Each names a group and
# the group taken back out of it - the people who came and did not buy - and
# a provider that expresses that as two blocks in one document is expressing
# it, not being asked for two things. Naming them here rather than letting a
# caller combine any pair is what keeps the vocabulary finite: a picker over
# nine actions squared is a picker of eighty-one mostly meaningless
# audiences, and the three below are the ones a business actually asks for.
#
#   visited_not_purchased        - came to the site and did not buy
#   added_to_cart_not_purchased  - got as far as the cart and did not buy
#   engaged_not_messaged         - dealt with the page some other way and
#                                  never wrote, for a business whose
#                                  customers arrive by message
AudienceAction = Literal[
    "visited",
    "viewed_item",
    "added_to_cart",
    "purchased",
    "engaged",
    "messaged",
    "opened",
    "submitted",
    "abandoned",
    "visited_not_purchased",
    "added_to_cart_not_purchased",
    "engaged_not_messaged",
]

# How wide a net to cast when building an audience out of another one.
#
# Three words rather than a number, and the number is the reason. Meta takes
# a ratio between 0.01 and 0.20; Google takes an enum of NARROW, BALANCED and
# BROAD and has no percentage anywhere. A domain that stored "five per cent"
# would be storing a figure the second platform cannot be told, and the first
# thing a Google adapter would have to do is invent a mapping back out of it.
#
# Naming the intent instead is the same bargain :data:`AudienceAction` makes,
# and it happens to be the better product answer as well: nobody running a
# shop knows what the top 5% of a country means, and everybody knows the
# difference between "the people most like my customers" and "more of them,
# less alike".
#
#   closest   - the tightest match a provider offers. Smallest, and the one
#               to start from when the seed is good
#   balanced  - the ordinary choice
#   broad     - more people, less like the seed. For an advertiser who has
#               already exhausted the closest one
#
# Three rungs and not twenty, for the reason :data:`WINDOWS` has five: a
# person choosing between 13% and 14% is choosing between two things nobody
# can describe the difference between.
AudienceBreadth = Literal["closest", "balanced", "broad"]

# Which way a day's figures were cut up when they were asked for.
#
# Not a provider's word. Meta cuts by ``age`` and ``gender`` as two separate
# breakdowns and Google reports the same pair as one age-range-and-gender
# view; naming the *question* rather than either spelling is what keeps the
# port from being Meta's request parameter with a different name on it.
#
# The first two were chosen because they answer the two questions a media
# buyer asks about a group that is spending badly: **who** was reached and
# **where** the ad appeared. Each addition is a line here plus a line in the
# adapter that knows how to ask for it.
#
# ``region`` is the third and answers **where** from the provider rather
# than from the city somebody typed into a form: an account whose form asks
# only a name and a telephone number has no answer of its own.
BreakdownKind = Literal["age_gender", "platform_position", "region"]


@dataclass(frozen=True, slots=True)
class ExternalRef:
    """One object on one provider.

    Frozen and slotted: these are created per object per sync, compared,
    and used as dict keys. Mutating one after it crossed a layer boundary
    would silently retarget whatever call is holding it.
    """

    provider: ProviderName
    level: Level
    id: str

    def __str__(self) -> str:
        """Compact form for logs and idempotency keys: ``meta:adset:123``."""
        return f"{self.provider}:{self.level}:{self.id}"
