"""The daily report as the model reads it."""

from datetime import date

from core.chat.daily import (
    ATTENTION_ROWS,
    BURNING,
    FINE,
    NO_FIGURE,
    WATCH,
    DailyReport,
    DayCampaign,
    census,
    settled,
    standing,
    worth_naming,
)


def a_campaign(**overrides: object) -> DayCampaign:
    values: dict[str, object] = {
        "name": "Osh markazi",
        "kind": "lead",
        "state": "active",
        "state_label": "Ishlayapti",
        "learning": False,
        "spend": "12 USD",
        "results": 2,
        "result_label": "Murojaatlar",
        "cost": "6 USD",
        "cost_label": "Murojaat narxi",
        "usual_cost": "8 USD",
    }
    values.update(overrides)
    return DayCampaign(**values)  # type: ignore[arg-type]


def a_report(*campaigns: DayCampaign, spend_minor: int = 1_200) -> DailyReport:
    return DailyReport(
        day=date(2026, 9, 15),
        day_text="15.09",
        currency="USD",
        spend="12 USD",
        spend_minor=spend_minor,
        campaigns=campaigns,
    )


def test_each_campaign_is_numbered_and_named_in_its_own_result() -> None:
    text = a_report(a_campaign()).render()

    assert '### 0. "Osh markazi"' in text
    assert "- Leads: 2" in text
    assert "- Cost per lead over the 7 days before: 8 USD" in text


def test_the_model_is_told_the_day_is_over() -> None:
    """The prompt's verdicts lean on it: an afternoon is not a failure, a
    finished day can be."""
    text = a_report(a_campaign()).render()

    assert "## The day (15.09, finished)" in text
    assert "today" not in text.lower()


def test_the_platforms_larger_count_is_said_beside_ours() -> None:
    text = a_report(a_campaign(reported=3)).render()

    assert "(the platform counted 3)" in text


def test_a_campaign_whose_result_cannot_be_counted_gets_no_count() -> None:
    text = a_report(a_campaign(kind="none", cost=NO_FIGURE)).render()
    campaign = text.split("## Campaigns")[1]

    assert [line for line in campaign.splitlines() if line.startswith("- ")] == [
        "- State right now, not on the reported day: running",
        "- Spend: 12 USD",
    ]


def test_the_gate_may_quote_the_days_figures() -> None:
    assert "12" in " ".join(a_report(a_campaign()).figures())


def test_the_diagnosis_reaches_the_model_in_its_own_language() -> None:
    """The figures say a campaign did badly; only this says what is wrong."""
    text = a_report(
        a_campaign(
            cause="weak_creative",
            cause_label="Reklama e'tibor tortmaydi",
            cause_line="1000 kishidan 4 tasi bosyapti, hisobingizda o'rtacha 12 tasi.",
        )
    ).render()

    assert (
        "- Diagnosis over the last few days: people are shown the advert and "
        "hardly any of them click it" in text
    )
    assert "- The figure behind it: 1000 kishidan 4 tasi" in text


def test_the_figure_behind_the_cause_may_be_quoted_back() -> None:
    """It is supplied, so the gate must not strip it out of the reading."""
    figures = a_report(
        a_campaign(cause="weak_creative", cause_line="1000 kishidan 4 tasi bosyapti.")
    ).figures()

    assert {"1000", "4"} <= figures


def test_a_campaign_found_well_carries_no_cause_line() -> None:
    text = a_report(a_campaign()).render()

    assert "Diagnosis" not in text


def test_a_day_nothing_was_spent_is_quiet() -> None:
    assert a_report(spend_minor=0).is_quiet


# --- the model's word, held to the figures --------------------------------
def judged(**figures: object) -> DayCampaign:
    fields: dict[str, object] = {
        "name": "Osh",
        "kind": "lead",
        "state": "active",
        "state_label": "Ishlayapti",
        "learning": False,
        "spend": "12 USD",
        "results": 2,
        "result_label": "Murojaat",
        "cost": "6 USD",
        "cost_label": "Bitta murojaat narxi",
        "usual_cost": "8 USD",
        "spend_minor": 1_200,
        "cost_minor": 600,
        "usual_cost_minor": 800,
    }
    return DayCampaign(**(fields | figures))  # type: ignore[arg-type]


def test_money_spent_for_nothing_is_never_good() -> None:
    idle = judged(results=0, cost_minor=None)

    assert settled("good", campaign=idle) == "watch"


def test_a_campaign_still_learning_is_at_most_watch() -> None:
    learning = judged(learning=True)

    assert settled("good", campaign=learning) == "watch"
    assert settled("bad", campaign=learning) == "watch"


def test_cheaper_than_usual_is_never_bad() -> None:
    assert settled("bad", campaign=judged()) == "good"


def test_a_word_the_figures_agree_with_stands() -> None:
    dear = judged(cost_minor=1_600)

    assert settled("bad", campaign=dear) == "bad"
    assert settled("good", campaign=judged()) == "good"


# --- The census: what a day says when there are too many campaigns to read ---
def spender(name: str, minor: int, **overrides: object) -> DayCampaign:
    """One campaign that spent, with the figures the census reads."""
    return a_campaign(
        name=name,
        spend=f"{minor // 100} USD",
        spend_minor=minor,
        cost_minor=overrides.pop("cost_minor", 600),
        usual_cost_minor=overrides.pop("usual_cost_minor", 800),
        **overrides,
    )


def test_a_campaign_that_spent_and_brought_nothing_is_burning() -> None:
    row = spender("Bahor", 4_500, results=0, cost_minor=None)

    assert standing(row) == BURNING


def test_a_young_campaign_is_never_worse_than_watch() -> None:
    """Its price today is the platform still searching, whatever it spent -
    the same rule the reading's verdict is held to."""
    row = spender("Yangi", 4_500, results=0, cost_minor=None, learning=True)

    assert standing(row) == WATCH


def test_a_result_dearer_than_usual_is_watched_rather_than_burning() -> None:
    assert standing(spender("Qimmat", 900, cost_minor=900)) == WATCH
    assert standing(spender("Arzon", 900, cost_minor=400)) == FINE


def test_the_census_counts_every_campaign_that_spent() -> None:
    """Not the handful a message lists. A reader with twenty campaigns is
    told how many are fine, not shown eight of them."""
    rows = (
        spender("Bahor", 4_500, results=0, cost_minor=None),
        spender("Qimmat", 900, cost_minor=900),
        *(spender(f"Oddiy {index}", 600) for index in range(12)),
    )

    counted = census(rows)

    assert counted.spenders == 14
    assert (counted.fine, counted.watch, counted.burning) == (12, 1, 1)


def test_a_day_of_two_kinds_of_result_counts_neither() -> None:
    """Eight kinds are counted on eight scales, and adding a conversation
    to an enquiry is the one sum this product never does."""
    mixed = census((spender("Lid", 600), spender("Suhbat", 600, kind="chat")))
    alone = census((spender("Lid", 600), spender("Yana", 600)))

    assert (mixed.results, mixed.result_label) == (0, "")
    assert (alone.results, alone.result_label) == (4, "Murojaatlar")


def test_money_burnt_in_ninth_place_is_still_named() -> None:
    """The list a message could print is sorted by spend; this is not, or
    the one campaign worth acting on would sit below the fold."""
    rows = (
        *(spender(f"Katta {index}", 5_000) for index in range(8)),
        spender("Kichik", 300, results=0, cost_minor=None),
    )

    [named] = worth_naming(rows, limit=ATTENTION_ROWS)

    assert named.name == "Kichik"


def test_a_campaign_with_a_diagnosis_is_named_although_its_day_was_ordinary() -> None:
    """A cause reads several days, and it is the one line on the report
    that says what to fix."""
    rows = (spender("Tushlik", 900, cause="weak_creative", cause_label="Zaif reklama"),)

    assert worth_naming(rows, limit=ATTENTION_ROWS)[0].name == "Tushlik"


def test_a_day_where_nothing_is_wrong_names_nobody() -> None:
    rows = tuple(spender(f"Oddiy {index}", 600) for index in range(5))

    assert worth_naming(rows, limit=ATTENTION_ROWS) == ()
    assert census(rows).all_fine


def test_a_campaign_whose_result_is_not_counted_here_is_never_burning() -> None:
    """A sale on somebody else's website is a result this product cannot see.

    Read as "spent money and brought nothing", it makes the evening message
    call a working campaign a fire every day it runs - and this product
    launches that goal itself, from a dozen of its own categories. The
    figures screen says so in words; a census has no room to, so the
    campaign stays out of the verdict.
    """
    sales = a_campaign(kind="none", results=0, spend_minor=4_500, result_label="")

    assert standing(sales) == FINE
    assert census((sales,)).burning == 0


def test_a_campaign_with_nothing_counted_does_not_hide_a_real_fire() -> None:
    """The guard is about the kind, not about the day."""
    sales = a_campaign(kind="none", results=0, spend_minor=4_500, result_label="")
    burning = a_campaign(results=0, spend_minor=4_500)

    assert census((sales, burning)).burning == 1


def test_a_few_coins_for_nothing_are_watched_not_burning() -> None:
    """Under one usual result's worth, a morning with nothing is not a fire."""
    quiet = a_campaign(results=0, spend_minor=300, usual_cost_minor=800)

    assert standing(quiet) == "watch"


def test_a_usual_result_s_worth_for_nothing_is_burning() -> None:
    gone = a_campaign(results=0, spend_minor=800, usual_cost_minor=800)

    assert standing(gone) == "bad"


def test_a_lead_meta_counted_is_a_result_even_before_it_arrives() -> None:
    counted = a_campaign(results=0, reported=1, spend_minor=4_500)

    assert standing(counted) != "bad"


def test_a_refused_campaign_is_not_called_stopped() -> None:
    """The state covers an advert still delivering with a fault, so a model
    told "stopped" explained a running campaign's day by a stop."""
    text = a_report(a_campaign(state="rejected")).render()

    assert "the platform reported a problem" in text
    assert "stopped by the platform" not in text
