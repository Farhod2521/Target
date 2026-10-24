"""One line each for the rungs under a campaign, as a model reads them.

No database. What is checked is the text: an empty half is left off rather
than printed as a blank, an advert's words are quoted after its figures, a
cause arrives on the line of the group it is about, and the totals carry
no qualified-lead figure.
"""

from dataclasses import replace

from core.chat.context import (
    AccountDigest,
    BusinessDigest,
    ChatContext,
    TotalsDigest,
)
from core.chat.rungs import (
    AdDigest,
    AdSetDigest,
    FormDigest,
    PageDigest,
    ResultDigest,
    ad_line,
    adset_line,
    form_line,
    page_line,
)

GROUP = AdSetDigest(
    name="Toshkent 25-45",
    campaign="Yozgi savdo",
    status="Faol",
    spend="900 USD",
    result="2 leads, cost each 450 USD",
)
ADVERT = AdDigest(
    name="Qish aksiyasi",
    group="Toshkent 25-45",
    status="Faol",
    spend="420 USD",
    result="2 leads, cost each 210 USD",
)


def account(**sections: object) -> ChatContext:
    return ChatContext(
        account=AccountDigest(
            business=BusinessDigest(
                name="Kafe", category="Restoran", offer="Tushlik", currency="USD"
            ),
            totals=TotalsDigest(
                window_days=30,
                spend="1 200 USD",
                results=(ResultDigest(kind="lead", count=42, cost="28 USD"),),
            ),
            maturity="",
            **sections,  # type: ignore[arg-type]
        )
    )


# --- A group --------------------------------------------------------------
def test_a_group_carries_the_cause_the_diagnosis_found() -> None:
    """Last on the line, after the evidence under it, so the model reads the
    figures before the verdict they add up to."""
    line = adset_line(
        replace(GROUP, cause="Reklama e'tibor tortmaydi - 1000 kishidan 4 tasi.")
    )

    assert line.endswith(", cause: Reklama e'tibor tortmaydi - 1000 kishidan 4 tasi.")


def test_a_rate_is_printed_beside_the_account_s() -> None:
    line = adset_line(replace(GROUP, click_rate="4 (account 14)"))

    assert "clicks per 1000 shown, last 7 days 4 (account 14)" in line


def test_an_empty_half_is_left_off_rather_than_printed_blank() -> None:
    """A blank label invites a model to explain a blank."""
    line = adset_line(GROUP)

    for label in ("cause", "clicks per", "still learning", "provider suggests"):
        assert label not in line


def test_a_group_still_learning_says_so() -> None:
    assert ", still learning" in adset_line(replace(GROUP, is_learning=True))


def test_a_switched_off_group_says_so_and_carries_no_cause() -> None:
    """The label is in the reader's language; the mark is what the prompt
    reads. A cause left from a night before the pause would read as a reason
    to fix something nobody runs."""
    line = adset_line(replace(GROUP, is_off=True, cause="Auditoriya tor."))

    assert ", switched off" in line
    assert "cause" not in line


def test_a_running_group_is_not_called_switched_off() -> None:
    assert "switched off" not in adset_line(GROUP)


# --- An advert, a form, a page -------------------------------------------
def test_a_switched_off_advert_says_so() -> None:
    assert ", switched off" in ad_line(replace(ADVERT, is_off=True))
    assert "switched off" not in ad_line(ADVERT)


def test_an_advert_s_words_are_quoted_after_its_figures() -> None:
    line = ad_line(replace(ADVERT, headline="Chegirma", words="Bugun keling"))

    assert line.index('headline "Chegirma"') > line.index("2 leads")
    assert line.endswith('words "Bugun keling"')


def test_a_form_line_lists_its_questions_in_order() -> None:
    line = form_line(FormDigest(name="Forma 1", questions=("Ism", "Telefon")))

    assert line == "- Forma 1: 2 questions - Ism; Telefon"


def test_a_form_never_read_back_is_not_a_form_with_no_questions() -> None:
    """ "0 questions" would be read as a very short form."""
    assert form_line(FormDigest(name="Forma 2")) == "- Forma 2: questions not read yet"


def test_a_page_says_whether_the_pixel_was_found() -> None:
    assert page_line(PageDigest(url="https://kafe.uz", state="Ochildi")) == (
        "- https://kafe.uz - Ochildi, no pixel found"
    )


# --- The digest around them ----------------------------------------------
def test_the_totals_carry_no_qualified_lead_figure() -> None:
    """The quality mark those figures rest on is switched off, and a nought
    in the context is a nought the answer would explain."""
    body = account().render()

    assert "ualified" not in body
    assert "- Results: 42 leads, cost each 28 USD" in body


def test_each_rung_renders_under_its_own_heading_in_order() -> None:
    body = account(
        adsets=(GROUP,),
        ads=(ADVERT,),
        forms=(FormDigest(name="Forma 1"),),
        pages=(PageDigest(url="https://kafe.uz", state="Ochildi"),),
    ).render()

    headings = ["## Ad groups", "## Adverts", "## Lead forms", "## Website pages"]
    assert [body.index(each) for each in headings] == sorted(
        body.index(each) for each in headings
    )
