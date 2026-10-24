"""The preparation sequence, without a database.

Every case here is a screen somebody has actually met: the profile saved
without a category, the connection that came back missing a permission, the
account with no pages behind it, the page whose lead terms nobody signed.
"""

from core.onboarding import (
    FINISH_GATES,
    GATES,
    ORDER,
    SetupFacts,
    blocking,
    can_finish,
    is_ready,
    paired_state,
    plan,
    progress,
)

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


def states(facts: SetupFacts) -> dict[str, str]:
    return {step.id: step.state for step in plan(facts)}


class TestOrder:
    def test_a_new_account_is_on_the_connection(self) -> None:
        """The first step is connecting, not describing.

        The profile describes one page - one trade, one town, one set of
        hours - so asking for it before a page exists is asking somebody to
        describe a business the cabinet cannot yet name.
        """
        assert states(SetupFacts())["connect"] == "current"
        assert states(SetupFacts())["profile"] == "waiting"

    def test_only_one_step_is_ever_open(self) -> None:
        for facts in (SetupFacts(), READY, SetupFacts(has_profile=True)):
            open_steps = [
                step for step in plan(facts) if step.state in {"current", "attention"}
            ]
            assert len(open_steps) <= 1

    def test_everything_after_the_open_step_waits(self) -> None:
        marks = states(SetupFacts(connected=True, pages_found=2))
        assert marks["connect"] == "done"
        assert marks["page"] == "current"
        assert marks["ad_account"] == "waiting"
        assert marks["profile"] == "waiting"
        assert marks["leads"] == "waiting"

    def test_an_expired_connection_does_not_unpick_the_page(self) -> None:
        """Work already done stays done, whatever reopened above it.

        A connection expires and the step above goes back to open; the page
        underneath it is still chosen, and drawing it as waiting would tell
        somebody to redo a choice that is still on the row. Only the state
        of the *open* step moves.
        """
        marks = states(_with(READY, connected=False))
        assert marks["connect"] == "current"
        assert marks["page"] == "done"
        assert marks["leads"] == "done"

    def test_finished_steps_stay_on_the_screen(self) -> None:
        assert [step.id for step in plan(READY)] == [*ORDER, "pixel"]


class TestProfile:
    def test_a_profile_without_a_category_is_not_finished(self) -> None:
        """The category is what selects a preset; the wizard refuses without
        one, so a profile saved without it is not a step somebody has done.

        Asked with everything above it done, because the profile is the
        fourth step rather than the first: a profile describes one page,
        and there is nothing to describe until a page is chosen.
        """
        facts = SetupFacts(
            connected=True,
            ad_account_chosen=True,
            page_chosen=True,
            has_profile=True,
        )
        assert states(facts)["profile"] == "current"


class TestConnection:
    def test_a_withheld_permission_is_not_a_connection(self) -> None:
        facts = SetupFacts(has_profile=True, has_category=True, connected=True)
        assert states(facts)["connect"] == "done"
        assert states(_with(facts, scopes_missing=True))["connect"] == "attention"


class TestEmptyLists:
    def test_no_ad_account_asks_for_one_to_be_opened(self) -> None:
        facts = _with(READY, ad_account_chosen=False, ad_accounts_found=0)
        assert states(facts)["ad_account"] == "attention"

    def test_one_unchosen_ad_account_is_an_ordinary_choice(self) -> None:
        facts = _with(READY, ad_account_chosen=False, ad_accounts_found=2)
        assert states(facts)["ad_account"] == "current"

    def test_no_pages_asks_for_one_to_be_made(self) -> None:
        facts = _with(READY, page_chosen=False, pages_found=0)
        assert states(facts)["page"] == "attention"


class TestLeads:
    def test_refused_terms_are_an_attention(self) -> None:
        facts = _with(READY, leads_subscribed=False, page_terms_accepted=False)
        assert states(facts)["leads"] == "attention"

    def test_terms_never_asked_are_not_a_refusal(self) -> None:
        """``None`` means Meta was never asked, which every row written
        before the column existed holds. It must read as permission.
        """
        facts = _with(READY, page_terms_accepted=None)
        assert states(facts)["leads"] == "done"

    def test_unsubscribed_is_the_open_step(self) -> None:
        facts = _with(READY, leads_subscribed=False)
        assert states(facts)["leads"] == "current"


class TestPixel:
    def test_it_is_never_the_next_thing_to_do(self) -> None:
        for facts in (SetupFacts(), READY, _with(READY, leads_subscribed=False)):
            assert states(facts)["pixel"] in {"done", "optional", "waiting"}

    def test_it_waits_until_there_is_an_account_to_list_one_from(self) -> None:
        assert states(SetupFacts())["pixel"] == "waiting"
        assert states(READY)["pixel"] == "optional"
        assert states(_with(READY, pixel_chosen=True))["pixel"] == "done"


class TestGate:
    def test_a_prepared_account_may_advertise(self) -> None:
        assert is_ready(READY)
        assert blocking(READY) == ""

    def test_leads_do_not_hold_the_button(self) -> None:
        """Connecting leads decides whether an enquiry *arrives*, not
        whether an advert can be made. A goal that sends people to a website
        creates no form at all.
        """
        facts = _with(READY, leads_subscribed=False, page_terms_accepted=False)
        assert is_ready(facts)
        assert blocking(facts) == ""

    def test_every_gate_refuses_on_its_own(self) -> None:
        holes = {
            "profile": {"has_category": False},
            "connect": {"connected": False},
            "ad_account": {"ad_account_chosen": False},
            "page": {"page_chosen": False},
        }
        for step_id, hole in holes.items():
            facts = _with(READY, **hole)
            assert not is_ready(facts), step_id
            assert blocking(facts) == step_id

    def test_the_earliest_gap_is_the_one_reported(self) -> None:
        facts = _with(READY, connected=False, page_chosen=False)
        assert blocking(facts) == "connect"

    def test_the_gates_are_a_prefix_of_the_order(self) -> None:
        assert ORDER[: len(GATES)] == GATES


class TestFinish:
    def test_the_profile_does_not_hold_the_finish_press(self) -> None:
        """The press fixes the account and the page. The profile is per page
        and stays editable afterwards, so an owner with several pages would
        otherwise lose the button every time they looked at an undescribed
        one - but it still holds the launch."""
        facts = _with(READY, has_profile=False, has_category=False)
        assert can_finish(facts)
        assert not is_ready(facts)
        assert blocking(facts) == "profile"

    def test_every_choice_the_press_fixes_holds_it(self) -> None:
        holes = {
            "connect": {"connected": False},
            "ad_account": {"ad_account_chosen": False},
            "page": {"page_chosen": False},
        }
        for step_id, hole in holes.items():
            facts = _with(READY, **hole)
            assert not can_finish(facts), step_id
            assert blocking(facts) == step_id

    def test_leads_do_not_hold_it_either(self) -> None:
        assert can_finish(_with(READY, leads_subscribed=False))

    def test_its_gates_are_a_prefix_of_the_launch_gates(self) -> None:
        """So while the press is refused, ``blocking`` names its step."""
        assert GATES[: len(FINISH_GATES)] == FINISH_GATES


class TestProgress:
    def test_it_counts_the_drawn_rows_and_not_the_gates(self) -> None:
        """Four rows on the screen: the page and its account are one."""
        assert progress(SetupFacts()) == (0, 4)
        assert progress(READY) == (4, 4)
        assert progress(_with(READY, leads_subscribed=False)) == (3, 4)

    def test_the_page_row_is_finished_only_with_its_account(self) -> None:
        assert progress(_with(READY, ad_account_chosen=False)) == (3, 4)
        assert progress(_with(READY, page_chosen=False)) == (3, 4)


class TestPairedRow:
    """The page and the account that pays for it, drawn as one row."""

    def test_it_follows_the_page_until_one_is_chosen(self) -> None:
        facts = SetupFacts(connected=True, pages_found=2, ad_accounts_found=1)
        assert paired_state(plan(facts)) == "current"

    def test_then_it_follows_the_account(self) -> None:
        facts = SetupFacts(connected=True, page_chosen=True, ad_accounts_found=0)
        assert paired_state(plan(facts)) == "attention"

    def test_it_is_done_when_both_are(self) -> None:
        assert paired_state(plan(READY)) == "done"


def _with(facts: SetupFacts, **changes: object) -> SetupFacts:
    """A copy with fields replaced. ``dataclasses.replace`` needs no slots."""
    fields = {
        name: getattr(facts, name) for name in SetupFacts.__dataclass_fields__
    } | changes
    return SetupFacts(**fields)  # type: ignore[arg-type]
