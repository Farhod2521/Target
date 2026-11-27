"""The advert chat's engine, without a model or a database: what it asks
next, what a message may change, and what it says back."""

from core.launch_agent import (
    FORM_AUTO,
    FORM_OWN,
    Brief,
    FormOption,
    Frame,
    GoalAdvice,
    GoalFrame,
    Heard,
    is_ready,
    merge,
    missing,
    next_slot,
    reply,
)
from core.launch_agent.hear import (
    amount,
    budget_minor,
    phone_number,
    site_link,
    telegram_link,
)
from core.launch_agent.words import amount_words

LEADS = GoalFrame(
    key="leads", label="Ariza qoldirsin", min_daily_minor=200, needs_form=True
)
CHAT = GoalFrame(
    key="messages",
    label="Xabar yozsin",
    min_daily_minor=100,
    opens_chat=True,
    channels=(("instagram", "Instagram"), ("messenger", "Messenger")),
)
SITE = GoalFrame(
    key="traffic", label="Saytga o'tsin", min_daily_minor=100, needs_link=True
)
TELEGRAM = GoalFrame(
    key="telegram",
    label="Telegramga o'tsin",
    min_daily_minor=100,
    needs_link=True,
    telegram=True,
)
CALLS = GoalFrame(
    key="calls", label="Qo'ng'iroq qilsin", min_daily_minor=100, needs_phone=True
)
VIEWS = GoalFrame(key="views", label="Ko'proq ko'rilsin", min_daily_minor=100)
FRAME = Frame(
    goals=(LEADS, CHAT, SITE, TELEGRAM, CALLS, VIEWS),
    uzs_per_usd=12_500,
    forms=(FormOption(id="f1", name="Kursga yozilish"),),
)


def _said(brief: Brief, **heard: str) -> Brief:
    return merge(brief, Heard(**heard), FRAME).brief


# -- what is asked, and in what order ----------------------------------------


def test_an_empty_brief_starts_with_what_is_advertised() -> None:
    assert next_slot(Brief(), FRAME) == "offer"
    assert missing(Brief(), FRAME) == ("offer", "goal", "budget")


def test_a_business_nobody_described_is_asked_about_first() -> None:
    frame = Frame(goals=FRAME.goals, kind_known=False)

    assert next_slot(Brief(), frame) == "kind"
    told = merge(Brief(), Heard(kind="Ingliz tili kurslari"), frame).brief
    assert next_slot(told, frame) == "offer"


def test_a_kind_already_known_is_never_asked_or_overwritten() -> None:
    told = merge(Brief(), Heard(kind="Boshqa narsa"), FRAME)

    assert told.brief.kind_said == ""
    assert told.took == ()


def test_each_goal_asks_only_its_own_questions() -> None:
    base = Brief(offer="IELTS kursi")

    assert missing(base.with_(goal="leads"), FRAME) == ("form", "budget")
    assert missing(base.with_(goal="messages"), FRAME) == ("channel", "budget")
    assert missing(base.with_(goal="traffic"), FRAME) == ("link", "budget")
    assert missing(base.with_(goal="calls"), FRAME) == ("phone", "budget")
    assert missing(base.with_(goal="views"), FRAME) == ("budget",)


def test_one_chat_channel_is_not_a_question() -> None:
    only = GoalFrame(
        key="messages",
        label="Xabar",
        opens_chat=True,
        channels=(("instagram", "Instagram"),),
    )
    frame = Frame(goals=(only,))

    assert missing(Brief(offer="x", goal="messages"), frame) == ("budget",)


def test_everything_said_in_one_message_asks_nothing_more() -> None:
    done = merge(
        Brief(),
        Heard(offer="IELTS kursi", goal="traffic", link="zukko.uz", budget="5"),
        FRAME,
    )

    assert done.notes == ()
    assert done.took == ("offer", "goal", "link", "budget")
    assert is_ready(done.brief, FRAME)
    assert done.brief.link == "https://zukko.uz"
    assert done.brief.budget_minor == 500


# -- what a message may change -----------------------------------------------


def test_a_goal_the_account_does_not_offer_is_not_taken() -> None:
    out = merge(Brief(offer="x"), Heard(goal="purchases"), FRAME)

    assert out.brief.goal == ""
    assert [(note.slot, note.code) for note in out.notes] == [("goal", "unknown_goal")]


def test_another_goal_forgets_where_the_old_one_sent_people() -> None:
    brief = _said(Brief(offer="x"), goal="traffic", link="zukko.uz", budget="5")

    moved = _said(brief, goal="calls")

    assert (moved.goal, moved.link) == ("calls", "")
    assert moved.budget_minor == 500  # the money said stays said
    assert next_slot(moved, FRAME) == "phone"


def test_the_same_goal_said_again_changes_nothing() -> None:
    brief = _said(Brief(offer="x"), goal="traffic", link="zukko.uz")

    assert _said(brief, goal="traffic").link == "https://zukko.uz"


def test_a_budget_under_the_floor_is_refused_with_the_floor() -> None:
    out = merge(Brief(offer="x", goal="leads"), Heard(budget="1"), FRAME)

    assert out.brief.budget_minor == 0
    (note,) = out.notes
    assert (note.code, note.detail) == ("below_floor", "200")
    said = reply(out.brief, FRAME, notes=out.notes)
    assert said.lines[0] == "Bu maqsad uchun kunlik byudjet kamida $2 bo'lishi kerak."


def test_a_budget_said_before_a_dearer_goal_is_asked_again() -> None:
    brief = _said(Brief(offer="x"), budget="1")
    assert brief.budget_minor == 100

    out = merge(brief, Heard(goal="leads"), FRAME)

    assert out.brief.budget_minor == 0
    assert out.notes[-1].code == "below_floor"
    assert "budget" in missing(out.brief, FRAME)


def test_a_budget_in_som_is_turned_into_the_account_s_dollars() -> None:
    assert budget_minor("50 000", "UZS", FRAME) == (400, "")
    assert budget_minor("50 ming", "uzs", FRAME) == (400, "")
    assert budget_minor("5", "", FRAME) == (500, "")
    assert budget_minor("5", "EUR", FRAME) == (0, "other_currency")
    assert budget_minor("ko'p", "", FRAME) == (0, "not_a_sum")
    no_rate = Frame(goals=FRAME.goals)
    assert budget_minor("50000", "UZS", no_rate) == (0, "other_currency")


def test_sums_are_read_as_people_write_them() -> None:
    assert amount("5") == 5
    assert amount("5,5") == amount("5.5")
    assert amount("50 000") == 50_000
    assert amount("50.000") == 50_000
    assert amount("1 mln") == 1_000_000
    assert amount("$7") == 7
    assert amount("0") is None
    assert amount("") is None


def test_addresses_and_numbers_are_checked_before_they_are_kept() -> None:
    assert site_link("zukko.uz/kurs") == "https://zukko.uz/kurs"
    assert site_link("HTTPS://Zukko.uz") == "https://Zukko.uz"
    assert site_link("sayt yo'q") == ""
    assert telegram_link("@zukko_uz") == "https://t.me/zukko_uz"
    assert telegram_link("t.me/zukko_uz") == "https://t.me/zukko_uz"
    assert telegram_link("https://t.me/+AbCdEf") == "https://t.me/+AbCdEf"
    assert telegram_link("zukko.uz") == ""
    assert phone_number("90 123 45 67") == "+998901234567"
    assert phone_number("+998 (90) 123-45-67") == "+998901234567"
    assert phone_number("12345") == ""


def test_the_telegram_goal_takes_only_a_telegram_address() -> None:
    brief = Brief(offer="x", goal="telegram")

    wrong = merge(brief, Heard(link="zukko.uz"), FRAME)
    right = merge(brief, Heard(link="@zukko_uz"), FRAME)

    assert wrong.notes[0].code == "not_telegram"
    assert right.brief.link == "https://t.me/zukko_uz"


def test_a_link_for_a_goal_that_needs_none_is_said_to_be_left_out() -> None:
    out = merge(Brief(offer="x", goal="views"), Heard(link="zukko.uz"), FRAME)

    assert out.brief.link == ""
    assert out.notes[0].code == "not_asked"


def test_a_form_is_one_of_the_page_s_or_one_of_three_choices() -> None:
    brief = Brief(offer="x", goal="leads")

    assert _said(brief, form="f1").form == "f1"
    assert _said(brief, form=FORM_AUTO).form == FORM_AUTO
    assert merge(brief, Heard(form="f9"), FRAME).notes[0].code == "unknown_form"


# -- what is said back -------------------------------------------------------


def test_the_goals_are_listed_with_no_recommendation_until_the_office_writes_one() -> (
    None
):
    said = reply(Brief(offer="IELTS kursi"), FRAME)

    assert said.lines == ()
    assert said.ask is not None and said.ask.slot == "goal"
    assert [option.value for option in said.ask.options] == [
        "leads",
        "messages",
        "traffic",
        "telegram",
        "calls",
        "views",
    ]
    assert not any(option.recommended for option in said.ask.options)


def test_the_targetolog_s_advice_is_said_in_their_words_and_ranked_first() -> None:
    frame = Frame(
        goals=FRAME.goals,
        advice=GoalAdvice(
            first="messages",
            reason_first="mijoz avval narxni so'raydi",
            second="leads",
            when_second="kurs narxi aniq bo'lsa",
        ),
    )

    said = reply(Brief(offer="IELTS kursi"), frame)

    assert said.lines == (
        "Sizning yo'nalishingizga «Xabar yozsin» tavsiya etiladi: mijoz avval narxni so'raydi",
        "«Ariza qoldirsin» esa shunday holatda yaxshiroq: kurs narxi aniq bo'lsa",
    )
    assert said.ask is not None
    assert [option.value for option in said.ask.options][:2] == ["messages", "leads"]
    assert [option.recommended for option in said.ask.options][:2] == [True, False]


def test_the_budget_question_offers_sums_from_the_goal_s_floor() -> None:
    said = reply(Brief(offer="x", goal="views"), FRAME)

    assert said.ask is not None and said.ask.slot == "budget"
    assert [(option.label, option.value) for option in said.ask.options] == [
        ("$1", "1"),
        ("$2", "2"),
        ("$4", "4"),
    ]
    assert said.ask.hint == "Kamida $1"
    assert said.ask.input == "money"


def test_the_form_question_keeps_the_cabinet_s_own_dialog_as_a_way_out() -> None:
    said = reply(Brief(offer="x", goal="leads"), FRAME)

    assert said.ask is not None and said.ask.slot == "form"
    values = [option.value for option in said.ask.options]
    assert values == [FORM_AUTO, "f1", "new", FORM_OWN]
    assert said.ask.options[-1].opens == "form"


def test_a_ready_brief_says_so_and_shows_what_was_settled() -> None:
    brief = _said(
        Brief(), offer="IELTS kursi", goal="messages", channel="instagram", budget="3"
    )

    said = reply(brief, FRAME)

    assert said.ready and said.ask is None
    assert said.lines == (
        "Sozlamalar tayyor. Endi post tanlang yoki rasm, video yuklang.",
    )
    assert [(chip.label, chip.value) for chip in said.chips] == [
        ("Reklama", "IELTS kursi"),
        ("Maqsad", "Xabar yozsin"),
        ("Yozishma", "Instagram"),
        ("Kunlik byudjet", "$3"),
    ]


def test_words_nobody_understood_are_said_to_be_so() -> None:
    said = reply(Brief(), FRAME, understood=False)

    assert said.lines == ("Buni tushunmadim, qaytadan yozib bering.",)
    assert said.ask is not None and said.ask.slot == "offer"


def test_sums_are_shown_in_the_account_s_money() -> None:
    som = Frame(goals=(), currency="UZS", minor_per_unit=1)

    assert amount_words(550, FRAME) == "$5.50"
    assert amount_words(60_000, som) == "60 000 so'm"
