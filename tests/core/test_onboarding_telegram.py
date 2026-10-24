"""The phone as a sixth step, without a database.

What is pinned: it is drawn only where a bot exists, it never holds either
button, it is the open step only once everything above it is done - so the
screen keeps one "you are here" - and it is counted exactly where it is
drawn.
"""

from dataclasses import replace

from core.onboarding import SetupFacts, blocking, is_ready, plan, progress

READY = SetupFacts(
    has_profile=True,
    has_category=True,
    connected=True,
    ad_account_chosen=True,
    ad_accounts_found=1,
    page_chosen=True,
    pages_found=1,
    page_terms_accepted=True,
    leads_subscribed=True,
)
OFFERED = replace(READY, telegram_offered=True)


def states(facts: SetupFacts) -> dict[str, str]:
    return {step.id: step.state for step in plan(facts)}


def open_steps(facts: SetupFacts) -> list[str]:
    return [step.id for step in plan(facts) if step.state in {"current", "attention"}]


def test_a_deployment_with_no_bot_draws_no_step_and_counts_none() -> None:
    assert "telegram" not in states(READY)
    assert progress(READY) == (4, 4)


def test_with_everything_else_done_the_phone_is_the_open_step() -> None:
    assert states(OFFERED)["telegram"] == "current"
    assert open_steps(OFFERED) == ["telegram"]


def test_before_the_rest_is_done_it_is_offered_but_not_next() -> None:
    """Its button works at any moment - it depends on nothing above it - but
    two open steps is how somebody does the second one first."""
    facts = replace(OFFERED, leads_subscribed=False)

    assert states(facts)["telegram"] == "optional"
    assert open_steps(facts) == ["leads"]


def test_a_linked_phone_is_a_finished_step() -> None:
    assert states(replace(OFFERED, telegram_linked=True))["telegram"] == "done"


def test_it_never_holds_the_button() -> None:
    assert is_ready(OFFERED) is True
    assert blocking(OFFERED) == ""


def test_it_is_drawn_as_an_extra_and_never_counted() -> None:
    assert progress(OFFERED) == (4, 4)
    assert progress(replace(OFFERED, telegram_linked=True)) == (4, 4)


def test_only_one_step_is_ever_open_with_the_phone_offered() -> None:
    for facts in (
        replace(SetupFacts(), telegram_offered=True),
        OFFERED,
        replace(OFFERED, has_category=False),
    ):
        assert len(open_steps(facts)) == 1


def test_the_phone_comes_after_the_five_and_before_the_optional_pixel() -> None:
    order = [step.id for step in plan(OFFERED)]

    assert order[-2:] == ["telegram", "pixel"]
