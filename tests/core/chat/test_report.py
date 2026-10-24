"""What a week is allowed to say about itself, and when it says nothing."""

from dataclasses import fields

from core.chat.daily import DayCampaign
from core.chat.headline import headline_for
from core.chat.report import CampaignLine, Change, WeekFigures, WeeklyReport
from core.metrics import Movement

# Words that would name a person rather than a measurement, as in
# ``tests/core/chat/test_context.py``. The report is a second thing handed
# to Claude, so it gets the same structural barrier.
PERSONAL = ("phone", "email", "full_name", "first_name", "last_name", "address")


def week(**kwargs: object) -> WeekFigures:
    return WeekFigures(
        **{
            "spend": "1 000 000 UZS",
            "qualified": 12,
            "cpql": "83 333 UZS",
            "active_days": 7,
            "kind": "lead",
            "results": 30,
            "result_cost": "33 333 UZS",
            "result_label": "Murojaatlar",
            "result_cost_label": "Murojaat narxi",
            **kwargs,
        }  # type: ignore[arg-type]
    )


def report(**kwargs: object) -> WeeklyReport:
    return WeeklyReport(
        **{
            "since": "12.08",
            "until": "18.08",
            "now": week(),
            "before": week(result_cost="50 000 UZS"),
            **kwargs,
        }  # type: ignore[arg-type]
    )


# --- The barrier ----------------------------------------------------------
def test_no_part_of_a_report_has_anywhere_to_put_a_person() -> None:
    """The same structural rule the chat context follows.

    A closed set of typed fields, so a lead's name cannot arrive by
    accident. Adding a field named after a person means editing this list
    and saying why in review.
    """
    for shape in (WeekFigures, CampaignLine, Change, WeeklyReport):
        for item in fields(shape):
            assert not any(word in item.name for word in PERSONAL), (
                f"{shape.__name__}.{item.name} could hold a person"
            )


def test_the_allow_set_is_read_back_out_of_the_rendered_text() -> None:
    """Not collected while building - derived from what was sent.

    ``ChatContext.figures`` follows the same rule, for the same reason: a
    set assembled separately is a second source of truth, and the day the
    two disagree the gate masks a real figure or passes an invented one.
    """
    written = report()
    figures = written.figures()

    assert "1000000" in figures
    assert "33333" in figures
    assert "30" in figures
    # The cost per qualified lead is carried on the shape and written
    # nowhere, so the model may not print it either - see ``_week``.
    assert "83333" not in figures
    # And nothing that was never in the text.
    assert "999999" not in figures


# --- The three silences ---------------------------------------------------
def test_a_week_with_no_leads_on_either_side_is_empty_not_quiet() -> None:
    empty = week(results=0, qualified=0)
    written = report(now=empty, before=empty)

    assert written.silence == "empty"
    assert not written.wants_sentence


def test_a_movement_that_did_not_clear_its_error_is_noise() -> None:
    """No headline means the arithmetic refused, and the report says so."""
    written = report(headline="", changes=(Change(kind="applied", what="Byudjet"),))

    assert written.silence == "noise"


def test_a_week_that_spent_is_read_whatever_its_movement() -> None:
    """The reading says how the week went and what to do this week.

    Every week with money in it has an answer to both; what a small
    movement or an empty list of changes withholds is only the cause, and
    the prompt holds that line rather than a gate in front of the call.
    """
    for written in (
        report(now=week(spend_minor=1_000_000), headline=""),
        report(now=week(spend_minor=1_000_000), headline="cpl", changes=()),
    ):
        assert written.wants_sentence


def test_a_week_that_spent_nothing_is_not_read() -> None:
    assert not report(now=week(spend_minor=0, results=3)).wants_sentence


def test_a_clear_movement_nobody_caused_gets_no_explanation() -> None:
    """The candidate list is empty, so there is nothing to choose from.

    This is the case that saves a call as well as a wrong sentence: with
    nothing on the list, anything written would be invention.
    """
    written = report(
        headline="cpl",
        move=Movement(percent=40, direction="down", is_good=True),
        changes=(),
    )

    assert written.silence == "no_change"


def test_a_movement_with_a_candidate_is_worth_a_sentence() -> None:
    written = report(
        now=week(spend_minor=1_000_000),
        headline="cpl",
        move=Movement(percent=40, direction="down", is_good=True),
        changes=(Change(kind="started", what="Yangi reklama ishga tushdi: Yoz"),),
    )

    assert written.silence == ""
    assert written.wants_sentence


# --- The short week -------------------------------------------------------
def test_two_weeks_of_different_lengths_are_not_comparable_by_count() -> None:
    written = report(now=week(active_days=3), before=week(active_days=7))

    assert not written.counts_comparable
    assert "not comparable" in written.render()


def test_two_full_weeks_are_comparable() -> None:
    assert report().counts_comparable


# --- Which figure the week is about --------------------------------------
def test_the_week_is_about_what_an_enquiry_cost() -> None:
    """One candidate while the quality marking is withdrawn.

    It was the second of two - see :data:`core.chat.report.HEADLINE_ORDER`,
    where the cost per qualified lead is kept - and the case below is what
    it was already doing on every week nobody had marked.
    """
    moves = {"cpl": Movement(percent=70, direction="down", is_good=True)}

    assert headline_for(moves=moves, now=week(), before=week()) == "cpl"


def test_a_withdrawn_figure_cannot_be_the_headline_even_when_it_moved() -> None:
    """A movement is offered for a key that is no longer preferred.

    It is not chosen, and the week is about the cost that is still drawn.
    Restoring the marking means putting the key back in ``HEADLINE_ORDER``,
    not hoping a movement finds its way in.
    """
    moves = {
        "cpql": Movement(percent=70, direction="down", is_good=True),
        "cpl": Movement(percent=70, direction="down", is_good=True),
    }

    assert headline_for(moves=moves, now=week(), before=week()) == "cpl"


def test_a_cost_built_on_too_few_leads_is_not_a_headline() -> None:
    """The figure is checked against the count it was divided by.

    A seventy percent move over four leads is noise wearing a percentage,
    and the week gets no headline rather than a confident sentence.
    """
    moves = {"cpl": Movement(percent=70, direction="down", is_good=True)}

    assert headline_for(moves=moves, now=week(results=2), before=week(results=2)) == ""


def test_a_week_that_does_not_clear_its_error_has_no_headline() -> None:
    moves = {"cpl": Movement(percent=20, direction="down", is_good=True)}

    assert headline_for(moves=moves, now=week(), before=week()) == ""


def test_a_flat_figure_is_never_the_headline() -> None:
    moves = {"cpl": Movement()}

    assert headline_for(moves=moves, now=week(), before=week()) == ""


# --- What the model is handed --------------------------------------------
def test_the_candidate_list_travels_with_the_report() -> None:
    written = report(changes=(Change(kind="applied", what="Byudjet oshirildi"),))

    assert "What changed this week" in written.render()
    assert "Byudjet oshirildi" in written.render()


def test_the_named_campaigns_are_in_the_text_the_model_reads() -> None:
    written = report(
        best=CampaignLine(
            name="Yozgi aksiya", spend="400 000 UZS", leads=20, qualified=8
        ),
        barren=CampaignLine(name="Test 2", spend="300 000 UZS", leads=4, qualified=0),
    )
    rendered = written.render()

    assert "Yozgi aksiya" in rendered
    assert "Test 2" in rendered
    # And their figures may be quoted back, because they were supplied.
    assert "400000" in written.figures()


def test_the_campaign_that_brought_nothing_says_whether_it_still_runs() -> None:
    """Without it the advice was to look at a campaign paused since."""
    paused = DayCampaign(
        name="Test 2",
        kind="lead",
        state="paused",
        state_label="",
        learning=False,
        spend="300 000 UZS",
        results=0,
        result_label="",
        cost="",
        cost_label="",
        usual_cost="",
    )
    written = report(
        barren=CampaignLine(name="Test 2", spend="300 000 UZS", leads=0, qualified=0),
        campaigns=(paused,),
    )

    assert "spend 300 000 UZS, state right now: paused" in written.render()
