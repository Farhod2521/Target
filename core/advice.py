"""What the review screen recommends, and why.

The person this product is for is not a media buyer. The screen shows them
three audience modes, two placement modes and a grid of lead forms, each
with an honest sentence about what it trades away - and an honest sentence
about a trade is still a trade somebody has to weigh. Most people weigh it
by leaving the default alone, which means the default is doing the advising
whether or not anybody meant it to. So the advising is written down.

**Rules and not the model**, for three reasons that point the same way:

* The facts arrive too late. Claude writes the whole proposal in one call
  before the review screen exists; whether the provider recognised the
  interests, how large the audience turned out and which forms are on the
  page are answered afterwards - and they are what these rules turn on.
* A recommendation has to be stable. The same launch asked twice must not
  be advised differently, or the badge becomes noise and takes the two
  beside it down with it.
* A recommendation has to be explainable. Every rule returns the *code* for
  its reason and Django turns that into one sentence, so what the screen
  says is what the rule did and cannot drift from it.

Its own module at the top of ``core`` rather than three functions spread
across ``targeting`` and ``leads``, because they are one feature: three
badges on one screen, read together, and credible only together. It
imports nothing from ``core`` at all: the form rule touches no lead, no
form row and no question, only opaque signatures the caller has already
built.

No Django, no clock, no configuration, and no parameters either.
"""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class Advice:
    """One recommendation: which option, and the code for why.

    ``reason`` is a code and never a sentence. The wording is Uzbek and
    reaches a screen, so it belongs in the translation catalogue - which is
    Django's, which this layer cannot see. The code is also what lets a
    test assert *which rule fired* rather than assert against a string
    somebody may reword next week.
    """

    value: str
    reason: str


@dataclass(frozen=True, slots=True)
class FormOffer:
    """One form a campaign could be pointed at, as :func:`form_advice` needs it.

    ``signature`` is what the form asks, already normalised by
    :func:`core.leads.form_signature` - the same function that normalises
    the questions this campaign would ask, so a difference is always a real
    difference and never a spelling of one.

    ``leads_count`` is the provider's own total, ``None`` when it has not
    said. Only ever used to break a tie between forms asking the identical
    thing.
    """

    external_id: str
    signature: tuple[str, ...]
    leads_count: int | None


# Why an audience mode is being recommended. One, for the reason the
# placement code below is one - see :func:`audience_advice`.
PROVIDER_EXPANDS: Final = "provider_expands"

# Why a placement mode is being recommended. One, because the rule does not
# branch - see :func:`placement_advice`.
PROVIDER_DEFAULT: Final = "provider_default"

# Why a form is being recommended, or why none is.
SAME_QUESTIONS: Final = "same_questions"
NOTHING_MATCHES: Final = "nothing_matches"

# Why a campaign should be bought on verdicts rather than on submissions.
# One code, because the picker is only drawn to an account that has already
# met every condition - there is no "not yet" to explain here, only on the
# screen that withholds the control.
SIGNAL_IS_READY: Final = "signal_is_ready"

# Why a kind of campaign is recommended for a goal: one code per goal, and
# one for a goal nobody wrote a sentence for.
CAMPAIGN_TYPE_REASONS: Final[dict[str, str]] = {
    "calls": "calls_cheapest",
    "leads": "form_leads_proven",
    "traffic": "site_visits_counted",
    "site_leads": "site_requests_counted",
    "views": "seen_most",
    "messages": "chat_proven",
}
PROVEN_DEFAULT: Final = "proven_default"

# Why an event on the advertiser's own site is recommended. Two codes,
# because the rule turns on one fact - has the tag been seen sending this -
# and the two answers are different sentences to read.
EVENT_ALREADY_ARRIVING: Final = "event_already_arriving"
EVENT_NOTHING_SEEN: Final = "event_nothing_seen"

# What the form recommendation is when nothing matches: the empty answer,
# which everywhere else in this flow means "build a new one". Named rather
# than written as ``""``, because an empty string returned by a function
# that otherwise returns identifiers reads like a failure and is the
# opposite of one.
BUILD_A_NEW_ONE: Final = ""


def audience_advice() -> Advice:
    """Which of the three audience modes this launch should use. Always one.

    ``automatic``, always. Every argument for one of the other two starts
    from a premise ``automatic`` already answers. Too few recognised
    interests and too small a pool are what the provider expanding past
    them is *for*, and ``broad`` answers both by throwing the interests
    away instead - strictly less signal for the same widening. An account
    with no campaigns behind it is no argument either: the switch does not
    run on this account's history, and the accounts that reading holds
    back are the new ones with the least of their own to go on.

    A pool the provider can barely deliver to is reported beside the reach
    figure, where it is a fact somebody reads rather than a mode chosen
    for them.

    Takes nothing, because it reads nothing - the same shape, and the same
    invitation to a real rule, as the placement advice below.
    """
    return Advice(value="automatic", reason=PROVIDER_EXPANDS)


def placement_advice() -> Advice:
    """Whether this ad should be allowed off Facebook and Instagram. Always.

    No branch on the goal, and no arm that keeps a lead campaign on
    Facebook and Instagram alone. The premise under "quality is already
    known there" is that this product can tell good delivery from bad *per
    placement*, and it cannot - a lead carries the ad it came from and
    never the placement it was seen in. Such an arm buys a signal that is
    never read, and pays for it in every advertiser with a lead goal being
    kept out of the cheaper inventory. An unmeasurable trade does not have
    a cautious side; it has a side the provider publishes a recommendation
    for, and a side that argues with that recommendation on no evidence.

    Takes nothing, because it reads nothing. The argument that would bring
    a parameter back is a real one - placement figures are collected
    nightly and read by nothing yet - and the day something reads them,
    this is where the rule goes.
    """
    return Advice(value="automatic", reason=PROVIDER_DEFAULT)


def buying_advice(*, is_offered: bool) -> Advice | None:
    """Whether to buy this campaign on the owner's own verdicts.

    The shortest rule of the four and the most confident, because the hard
    part has already happened elsewhere. Every condition that decides
    whether the quality goal is *usable* - verdicts going back to the
    provider, enough of them recently - is checked before the picker is
    drawn at all, so by the time there is anything to advise about, the
    answer is not in doubt: an account that has met them is buying blind if
    it does not use them.

    ``None`` when the option is not offered. There is no badge on a control
    that is not there, and no advice to give about one.

    What this deliberately does **not** weigh is how far past the threshold
    the account is. It could - more verdicts is a better signal - but the
    threshold is where the judgement was made, and a second, softer opinion
    about the same number on the same screen would be two rules disagreeing
    in public.
    """
    if not is_offered:
        return None
    return Advice(value="quality", reason=SIGNAL_IS_READY)


def campaign_type_advice(*, goal: str, kinds: tuple[str, ...]) -> Advice | None:
    """Which kind of campaign buys this goal, when the owner has not said.

    The first of ``kinds``, always: they arrive with the proven one first,
    and the proven one is the shape advertisers here have run and paid for
    most. The rest are alternatives the provider offers and nobody here has
    delivered against yet, which is exactly why none of them is
    recommended. Nothing else is weighed - the owner's words, the account's
    history - and the day something is, this is where the rule goes.

    ``None`` for a goal with no kinds: there is nothing to choose between
    and no badge to draw.
    """
    if not kinds:
        return None
    return Advice(
        value=kinds[0], reason=CAMPAIGN_TYPE_REASONS.get(goal, PROVEN_DEFAULT)
    )


def conversion_event_advice(
    *, offered: tuple[str, ...], fired: tuple[str, ...], requests: frozenset[str]
) -> Advice | None:
    """Which event on the advertiser's site this campaign should be bought on.

    **What the tag is actually sending decides**, and nothing else could:
    an event is a name somebody chose when they installed it, and a name
    nobody has ever sent is an ad set optimising towards silence. So the
    recommendation is the first event that has been seen arriving.

    Among several, a request wins over a look or a sale. A tag on an
    ordinary site sends a page view on every page and a request once a
    week, and the frequent one is exactly the wrong thing to buy: the
    provider would go and find more people who look.

    ``requests`` is handed in rather than known here, like every other fact
    these rules take. Which events mean "somebody asked" is the catalogue's
    business - see :data:`core.targeting.conversion_events.REQUEST_EVENTS`.

    With nothing seen, the first offered event stands: it is the preset's
    own and the commonest tag setup sends it. That is a weaker claim than
    the one above and says so through its own reason code, because the
    screen has to be able to tell somebody which of the two they are
    looking at.

    ``None`` when there is nothing to choose between.
    """
    if not offered:
        return None

    seen = [key for key in offered if key in fired]
    asked = [key for key in seen if key in requests]
    if asked:
        return Advice(value=asked[0], reason=EVENT_ALREADY_ARRIVING)
    if seen:
        return Advice(value=seen[0], reason=EVENT_ALREADY_ARRIVING)
    return Advice(value=offered[0], reason=EVENT_NOTHING_SEEN)


def form_advice(
    *, asked: tuple[str, ...], offers: tuple[FormOffer, ...]
) -> Advice | None:
    """The form that already asks exactly this, or the advice to build one.

    Worth asking because of what the provider will not do. Meta refuses to
    delete a lead form, so a campaign that builds one to ask the same four
    things as a form already on the page has left an undeletable duplicate
    behind - and an advertiser running a campaign a week ends up with a
    library nobody can read. Reusing costs nothing measurable: a lead is
    attributed by the ad set it arrived through and never by the form, so
    two campaigns sharing one form still have two costs.

    ``None`` - no advice at all - in the two cases where a badge would be
    noise. A page with no forms has nothing to choose between, and a
    campaign whose questions nobody has settled has nothing to match on; in
    both, "build a new one" is the only thing on screen and needs no
    pointing at.

    An exact match, and the exactness is the whole value. A form that asks
    almost the same things is a different form to the person filling it in,
    and blurring that would quietly change what this campaign collects -
    the one thing nobody would think to check, because they took the
    advice.

    Ties go to what the provider says each form has collected. Two forms
    asking the identical thing is a duplicate somebody already made, and
    the useful one of the pair is the one with leads in it: it is the one
    whose id is wired into whatever else the advertiser has connected.
    """
    if not offers or not asked:
        return None

    matches = [offer for offer in offers if offer.signature == asked]
    if not matches:
        return Advice(value=BUILD_A_NEW_ONE, reason=NOTHING_MATCHES)

    best = max(matches, key=lambda offer: offer.leads_count or 0)
    return Advice(value=best.external_id, reason=SAME_QUESTIONS)


__all__ = [
    "BUILD_A_NEW_ONE",
    "CAMPAIGN_TYPE_REASONS",
    "NOTHING_MATCHES",
    "PROVEN_DEFAULT",
    "PROVIDER_DEFAULT",
    "PROVIDER_EXPANDS",
    "SAME_QUESTIONS",
    "Advice",
    "FormOffer",
    "audience_advice",
    "campaign_type_advice",
    "conversion_event_advice",
    "form_advice",
    "placement_advice",
]
