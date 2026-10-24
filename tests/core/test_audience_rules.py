"""Choosing what an audience is built from, before a provider is involved.

The domain half of the split: this module knows what a person may be
offered and nothing at all about how a provider spells it. Which is why
these tests pass a hand-built ``RuleSupportDTO`` rather than reaching for
Meta's - the point of the layer is that it works for a provider that does
not exist yet.

No Django, no network, and - unlike its neighbour ``test_audience_hashing``
- no personal data anywhere. A rule describes people the provider already
knows about; nothing about any of them is collected here.
"""

import pytest
from adskit import ExternalRef
from adskit.dto import RuleSupportDTO

from core.audiences import (
    WINDOWS,
    ActionNotSupported,
    RetentionNotOffered,
    RetentionTooLong,
    SourceNotSupported,
    build_rule,
    windows_for,
)

FORM = ExternalRef(provider="meta", level="form", id="777")

LEAD = RuleSupportDTO(
    kind="lead_form", actions=("opened", "submitted"), max_retention_days=90
)
SITE = RuleSupportDTO(kind="pixel", actions=("visited",), max_retention_days=365)


# --- The ladder ----------------------------------------------------------
def test_the_ladder_is_cut_to_what_the_provider_looks_back() -> None:
    """Offering a year on something that stops at ninety days is offering a
    refusal."""
    assert windows_for(support=LEAD) == (7, 30, 90)
    assert windows_for(support=SITE) == WINDOWS


def test_a_source_that_looks_back_nowhere_offers_nothing() -> None:
    """Returned rather than defended against: a source with no window is one
    this product should stop offering, not one to invent a rung for."""
    nothing = RuleSupportDTO(kind="page", actions=("engaged",), max_retention_days=0)

    assert windows_for(support=nothing) == ()


# --- Building ------------------------------------------------------------
def test_a_valid_choice_becomes_a_rule_in_the_domains_own_words() -> None:
    built = build_rule(
        kind="lead_form",
        action="submitted",
        source=FORM,
        retention_days=30,
        support=[LEAD, SITE],
    )

    assert built.kind == "lead_form"
    assert built.action == "submitted"
    assert built.source == FORM
    assert built.retention_days == 30


def test_a_source_the_provider_does_not_build_from_is_refused() -> None:
    """Absent from the provider's answer and offering nothing are one case
    here, which is the one a picker means."""
    with pytest.raises(SourceNotSupported) as caught:
        build_rule(
            kind="page",
            action="engaged",
            source=FORM,
            retention_days=30,
            support=[LEAD],
        )

    assert caught.value.kind == "page"


def test_an_action_the_source_does_not_report_is_refused_by_both_halves() -> None:
    """A lead form does not report a purchase and a pixel does not report a
    message; "unsupported action" without the source names nothing."""
    with pytest.raises(ActionNotSupported) as caught:
        build_rule(
            kind="lead_form",
            action="purchased",
            source=FORM,
            retention_days=30,
            support=[LEAD],
        )

    assert caught.value.kind == "lead_form"
    assert caught.value.action == "purchased"


def test_too_long_a_window_carries_the_number_that_would_have_worked() -> None:
    """The only useful thing a screen can say here."""
    with pytest.raises(RetentionTooLong) as caught:
        build_rule(
            kind="lead_form",
            action="submitted",
            source=FORM,
            retention_days=365,
            support=[LEAD],
        )

    assert caught.value.maximum == 90
    assert caught.value.days == 365


def test_a_window_nobody_was_offered_is_a_different_refusal() -> None:
    """Not the provider's limit - a value that never appeared in the picker,
    which means a hand-edited form rather than a person choosing badly."""
    with pytest.raises(RetentionNotOffered) as caught:
        build_rule(
            kind="lead_form",
            action="submitted",
            source=FORM,
            retention_days=45,
            support=[LEAD],
        )

    assert caught.value.days == 45


def test_the_shortest_and_longest_rungs_both_build() -> None:
    for days in windows_for(support=SITE):
        built = build_rule(
            kind="pixel",
            action="visited",
            source=ExternalRef(provider="meta", level="pixel", id="1"),
            retention_days=days,
            support=[SITE],
        )
        assert built.retention_days == days


# --- Actions that subtract -----------------------------------------------
def test_an_action_that_subtracts_is_an_action_like_any_other() -> None:
    """**The point of the shape.** "Came and did not buy" arrives here as
    one word, is checked like one word, and leaves as one word. Nothing in
    this module knows that a provider spells it with two blocks - which is
    what keeps the subtraction out of every screen that renders a rule.
    """
    offering = RuleSupportDTO(
        kind="pixel",
        actions=("visited", "visited_not_purchased"),
        max_retention_days=365,
    )

    built = build_rule(
        kind="pixel",
        action="visited_not_purchased",
        source=ExternalRef(provider="meta", level="pixel", id="px-1"),
        retention_days=30,
        support=[offering],
    )

    assert built.action == "visited_not_purchased"
    assert built.retention_days == 30


def test_a_subtraction_the_provider_does_not_offer_is_refused_by_name() -> None:
    """A provider that gathers but does not subtract is a provider whose
    answer simply lacks the pair - and the refusal names both halves rather
    than saying "unsupported"."""
    with pytest.raises(ActionNotSupported):
        build_rule(
            kind="pixel",
            action="visited_not_purchased",
            source=ExternalRef(provider="meta", level="pixel", id="px-1"),
            retention_days=30,
            support=[SITE],
        )
