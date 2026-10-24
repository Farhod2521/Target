"""Which parts of an account a question turns out to need.

The whole digest is seven hundred and sixty tokens on a full account, and
most of it answers nothing a given question asked.
What is asked here is not whether the saving is large but whether it is
ever paid for by the reader: a question that needs the campaigns and does
not get them produces a worse answer, and no number of tokens is worth
that.

No database and no Django. It is a decision about words, and it is tested
by handing it words.
"""

from core.chat.route import SECTIONS, route


def wants(question: str, *previous: str) -> set[str]:
    return set(route(question=question, previous=previous).wants)


# --- Each subject finds its own section -----------------------------------
def test_a_question_about_adverts_asks_for_the_campaigns() -> None:
    assert wants("Qaysi reklama yaxshi ishlayapti?") == {"campaigns"}


def test_a_question_about_who_sees_it_asks_for_the_audiences() -> None:
    assert wants("Menga qanday auditoriya kerak?") == {"audiences"}


def test_a_question_about_the_agent_asks_for_its_proposals() -> None:
    assert wants("Agent nima taklif qildi?") == {"suggestions"}


def test_a_question_about_price_asks_for_the_campaigns_and_the_groups() -> None:
    """The entry in this table most easily got wrong.

    "Nega murojaat qimmatlashdi?" reads like a question about the totals,
    which are always sent. It is not: the totals say a lead cost more, the
    campaigns say which one did, and only the groups carry the diagnosis
    that says why. A router that saved those tokens here would have bought
    them from the answer.
    """
    assert wants("Nega murojaat qimmatlashdi?") == {"campaigns", "adsets"}


def test_a_question_about_a_group_asks_for_the_groups() -> None:
    """ "guruh" is the word every screen prints, since this product does
    not say "adset" to anybody."""
    assert wants("Bu guruh nega qimmat?") == {"adsets", "campaigns"}


def test_a_question_about_something_broken_asks_for_the_groups() -> None:
    """A fault is a group question whether or not the reader knows it: a
    provider stops a *group* and the campaign above it goes on reporting
    itself as active."""
    assert wants("Reklamamda qanday muammo bor?") == {"adsets", "campaigns"}
    assert wants("Nega ogohlantirish chiqdi?") == {"adsets"}


def test_a_question_about_why_asks_for_the_groups() -> None:
    """The flagship question. A group line carries last night's cause, so
    "why" is answered from there - and without it the assistant would be
    left to guess at a cause the product has already found."""
    assert wants("Nega pul ketyapti-yu, natija yo'q?") == {"adsets"}
    assert wants("Why are my results so poor?") == {"adsets"}


def test_a_plain_question_about_adverts_does_not_pay_for_the_groups() -> None:
    """The rung under the campaigns is the dearest section in the digest -
    each line carries an audience, a cost, a provider verdict and a cause -
    so it travels only when the question was about a group, a fault or why."""
    assert wants("Qaysi reklama yaxshi ishlayapti?") == {"campaigns"}


def test_a_question_about_the_words_asks_for_the_adverts() -> None:
    """An advert's text travels only when the question is about what people
    see - it is the longest line in the digest."""
    assert wants("Matnim yaxshimi?") == {"ads"}
    assert wants("Nega hech kim bosmayapti?") == {"adsets", "ads"}


def test_a_question_about_the_form_asks_for_what_a_click_lands_on() -> None:
    assert wants("Formada savol ko'pmi?") == {"landing"}
    assert wants("Sayt ochilyaptimi?") == {"landing"}
    assert wants("Is my lead form too long?") == {"landing"}


def test_a_word_that_merely_contains_form_does_not_open_the_forms() -> None:
    """ "platform", "performance" and "информация" carry the bare stem, and
    every one of them would otherwise send the forms and pages."""
    assert wants("How does the platform perform?") == set()
    assert wants("Дайте информацию") == set()


def test_two_subjects_in_one_question_bring_both() -> None:
    assert wants("Qaysi reklama qaysi auditoriyaga ko'rsatilyapti?") == {
        "campaigns",
        "audiences",
    }


# --- Three languages ------------------------------------------------------
def test_russian_is_matched_on_the_stem() -> None:
    """The endings are the point: "аудитории" is "аудитор" plus two."""
    assert wants("Какая аудитория мне нужна?") == {"audiences"}
    assert wants("Почему реклама стала дороже?") == {"campaigns", "adsets"}
    assert wants("Почему никто не кликает?") == {"adsets", "ads"}


def test_english_is_matched_too() -> None:
    assert wants("Which campaign is spending the most?") == {"campaigns"}


def test_an_uzbek_ending_does_not_hide_the_word() -> None:
    """ "reklamalarimdagi" is one word with four endings on it, and a
    whole-word match would find none of them."""
    assert wants("Reklamalarimdagi byudjetni ko'rsating") == {"campaigns"}


def test_either_apostrophe_matches() -> None:
    """A keyboard produces one and a copy-paste produces another, and a
    stem written with the wrong one matches nothing at all."""
    # The curly one written as an escape: two glyphs that differ by a hair
    # are two glyphs nobody can tell apart in a diff.
    assert wants("O\u2018xshash auditoriya kerakmi?") == {"audiences"}
    assert wants("O'xshash auditoriya kerakmi?") == {"audiences"}


# --- Nothing matched ------------------------------------------------------
def test_a_greeting_asks_for_nothing_beyond_the_base() -> None:
    """Who is asking and what the account did over the window still travel
    - they are a hundred tokens and there is no question about an
    advertising account better answered without them."""
    assert wants("Salom") == set()


def test_what_was_left_out_is_named() -> None:
    """The half that keeps the saving honest. A model handed no campaigns
    and told nothing concludes the account has none."""
    plan = route(question="Salom")

    assert set(plan.omitted) == set(SECTIONS)
    # In the fixed order, because it is printed: a set that came out
    # differently every time would make two identical questions into two
    # different prompts.
    assert plan.omitted == SECTIONS


# --- The conversation it sits in ------------------------------------------
def test_a_follow_up_keeps_the_subject_of_the_question_before_it() -> None:
    """ "Bu-chi?" is about whatever was being discussed a moment ago, and a
    context that quietly dropped the audiences half way through would make
    the assistant contradict what it had just said."""
    assert wants("Bu-chi?", "Menga qanday auditoriya kerak?") == {"audiences"}


def test_only_the_last_question_is_inherited() -> None:
    """A subject nobody has mentioned for two turns has been left behind."""
    assert wants("Salom", "Menga qanday auditoriya kerak?", "Rahmat") == set()


def test_a_new_subject_does_not_lose_the_old_one_immediately() -> None:
    """One turn of overlap, which is what a conversation actually does:
    somebody who asks about audiences and then about adverts is comparing
    them."""
    assert wants("Qaysi reklama ishlayapti?", "Qaysi auditoriya kattaroq?") == {
        "campaigns",
        "audiences",
    }
