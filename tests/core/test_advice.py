"""What the review screen recommends, and the order the rules answer in.

No Django and no database, which is the whole reason the rules were put in
``core`` rather than in the selector that feeds them: every case below is a
handful of numbers, and a suite that had to build a launch, a draft, an
account and a page to ask "what would you advise here" would test the
fixtures more thoroughly than the advice.

The reason codes are asserted rather than the sentences. A sentence is
Uzbek, lives in the translation catalogue and gets reworded; the code is
which rule fired, and that is the thing worth pinning.
"""

from core.advice import (
    BUILD_A_NEW_ONE,
    NOTHING_MATCHES,
    PROVIDER_DEFAULT,
    PROVIDER_EXPANDS,
    SAME_QUESTIONS,
    FormOffer,
    audience_advice,
    form_advice,
    placement_advice,
)
from core.leads import form_signature


# --- Who chooses the audience --------------------------------------------
def test_every_launch_is_advised_towards_the_provider_expanding() -> None:
    """One answer for every launch, and no ladder under it.

    A rung sending too few interests or too small a reach somewhere else
    would argue against the mode from a premise the mode already answers:
    a thin pool is what expanding past it is *for*, and ``broad`` widens by
    throwing the interests away instead.
    """
    advice = audience_advice()

    assert (advice.value, advice.reason) == ("automatic", PROVIDER_EXPANDS)


def test_the_audience_rule_reads_nothing() -> None:
    """No confirmation count, no reach, no account history. A parameter
    still being passed would read as a fact the answer turns on, and the
    next person would go looking for the branch."""
    assert audience_advice.__code__.co_argcount == 0


def test_the_two_withdrawn_rules_do_not_share_a_reason_code() -> None:
    """Both point at the provider's recommendation, but the sentences
    differ - one is about who the ad is shown to and the other about where.
    One code for both would put the wrong sentence under one of the two
    badges."""
    assert audience_advice().reason != placement_advice().reason


# --- Where the ad may appear --------------------------------------------
def test_every_goal_is_advised_towards_the_provider_default() -> None:
    """One answer for every goal, and no split between them.

    Keeping lead, chat and call campaigns on Facebook and Instagram would
    be protecting a quality signal that does not exist - a lead carries the
    ad it came from and never the placement it was seen in. All it does is
    keep the goals this product exists for out of the cheaper inventory, on
    no evidence, against the provider's own published recommendation.
    """
    advice = placement_advice()

    assert (advice.value, advice.reason) == ("automatic", PROVIDER_DEFAULT)


def test_the_rule_reads_nothing() -> None:
    """Takes no arguments at all, which is the honest shape for a rule with
    no inputs: a goal still being passed in would read as a fact the answer
    turns on, and the next person would go looking for the branch."""
    assert placement_advice.__code__.co_argcount == 0


# --- Which form ----------------------------------------------------------
def an_offer(*types: str, leads: int | None = 0, form_id: str = "1") -> FormOffer:
    return FormOffer(
        external_id=form_id,
        signature=form_signature({"type": kind} for kind in types),
        leads_count=leads,
    )


def test_a_form_asking_exactly_this_is_recommended() -> None:
    """Meta refuses to delete a lead form, so building one to ask what a
    form on the page already asks leaves an undeletable duplicate."""
    asked = form_signature([{"type": "FULL_NAME"}, {"type": "PHONE"}])

    advice = form_advice(asked=asked, offers=(an_offer("FULL_NAME", "PHONE"),))

    assert advice is not None
    assert (advice.value, advice.reason) == ("1", SAME_QUESTIONS)


def test_almost_the_same_is_not_the_same() -> None:
    """A form asking one question more is a different form to the person
    filling it in, and a recommendation that blurred that would quietly
    change what this campaign collects."""
    asked = form_signature([{"type": "FULL_NAME"}, {"type": "PHONE"}])

    advice = form_advice(asked=asked, offers=(an_offer("FULL_NAME", "PHONE", "EMAIL"),))

    assert advice is not None
    assert (advice.value, advice.reason) == (BUILD_A_NEW_ONE, NOTHING_MATCHES)


def test_the_same_questions_in_another_order_are_another_form() -> None:
    """Order is what somebody answers on a phone. Being strict costs a
    badge that does not appear; being loose reorders their questions."""
    asked = form_signature([{"type": "FULL_NAME"}, {"type": "PHONE"}])

    advice = form_advice(asked=asked, offers=(an_offer("PHONE", "FULL_NAME"),))

    assert advice is not None
    assert advice.value == BUILD_A_NEW_ONE


def test_a_custom_question_is_matched_by_what_it_asks() -> None:
    """A standard question is prefilled and titled by the provider, so its
    type identifies it. A custom one is identified only by its wording -
    compared without case, because two capitalisations are one question."""
    asked = form_signature(
        [{"type": "PHONE"}, {"type": "CUSTOM", "label": "Qaysi filial?"}]
    )
    offer = FormOffer(
        external_id="7",
        signature=form_signature(
            [{"type": "PHONE"}, {"type": "CUSTOM", "label": "qaysi filial?"}]
        ),
        leads_count=3,
    )

    advice = form_advice(asked=asked, offers=(offer,))

    assert advice is not None
    assert advice.value == "7"


def test_a_different_custom_wording_is_a_different_form() -> None:
    asked = form_signature([{"type": "CUSTOM", "label": "Qaysi filial?"}])
    offer = FormOffer(
        external_id="7",
        signature=form_signature([{"type": "CUSTOM", "label": "Qaysi model?"}]),
        leads_count=3,
    )

    advice = form_advice(asked=asked, offers=(offer,))

    assert advice is not None
    assert advice.value == BUILD_A_NEW_ONE


def test_the_duplicate_with_leads_in_it_wins() -> None:
    """Two forms asking the identical thing is a duplicate somebody
    already made, and the useful one is the one whose id is wired into
    whatever else they have connected."""
    asked = form_signature([{"type": "PHONE"}])

    advice = form_advice(
        asked=asked,
        offers=(
            an_offer("PHONE", leads=0, form_id="empty"),
            an_offer("PHONE", leads=48, form_id="used"),
            an_offer("PHONE", leads=None, form_id="unasked"),
        ),
    )

    assert advice is not None
    assert advice.value == "used"


def test_a_page_with_no_forms_is_advised_nothing() -> None:
    """ "Build a new one" is the only thing on screen and needs no badge
    pointing at it."""
    asked = form_signature([{"type": "PHONE"}])

    assert form_advice(asked=asked, offers=()) is None


def test_a_launch_asking_nothing_yet_is_advised_nothing() -> None:
    """Nothing to match on. A badge here would be a recommendation made
    before the question it answers exists."""
    assert form_advice(asked=(), offers=(an_offer("PHONE"),)) is None
