"""Splitting the choice line off an answer, one chunk at a time."""

from core.chat.choices import (
    MARK,
    MAX_CHOICES,
    MAX_REPLIES,
    REPLY_MARK,
    REPLY_MAX_CHARS,
    ChoiceGate,
    vetted_replies,
)


def run(*pieces: str) -> tuple[str, tuple[str, ...]]:
    """Feed the gate in pieces, the way the worker does."""
    gate = ChoiceGate()
    out = [gate.feed(piece) for piece in pieces]
    out.append(gate.flush())
    return "".join(out), gate.keys


def test_an_answer_with_no_choice_passes_through_unchanged() -> None:
    text, keys = run("Murojaat qimmatlashdi, ", "chunki sarf oshgan.")

    assert text == "Murojaat qimmatlashdi, chunki sarf oshgan."
    assert keys == ()


def test_the_marker_and_its_line_never_reach_the_reader() -> None:
    text, keys = run(f"Bu reklamani to'xtatish kerak.\n{MARK} A1\n")

    assert MARK not in text
    assert "A1" not in text
    assert text.strip() == "Bu reklamani to'xtatish kerak."
    assert keys == ("A1",)


def test_a_marker_split_across_chunks_is_still_caught() -> None:
    """The case the whole design is for.

    Claude's pieces end mid-word as readily as mid-sentence, so the marker
    arrives in halves. A gate that judged each piece on its own would show
    "%%CHO" to somebody reading and take it away a moment later.
    """
    text, keys = run("Javob.\n%%CH", "OICE%% A2")

    assert text.strip() == "Javob."
    assert keys == ("A2",)


def test_a_chunk_that_only_looked_like_the_marker_is_released() -> None:
    text, keys = run("Sarf 100%", " oshdi.")

    assert text == "Sarf 100% oshdi."
    assert keys == ()


def test_text_held_at_the_end_of_a_stream_is_released_by_flush() -> None:
    text, keys = run("Tugadi %")

    assert text == "Tugadi %"
    assert keys == ()


def test_two_keys_on_one_line_are_both_read_in_the_order_written() -> None:
    text, keys = run(f"Ikki yo'l bor.\n{MARK} A2, A1\n")

    assert keys == ("A2", "A1")
    assert "A2" not in text


def test_no_more_keys_than_one_answer_may_offer() -> None:
    """Three buttons under a paragraph is a menu, and this is not one."""
    _, keys = run(f"{MARK} A1, A2, A3, A4")

    assert len(keys) == MAX_CHOICES


def test_a_key_written_twice_is_one_choice() -> None:
    _, keys = run(f"{MARK} A1, A1")

    assert keys == ("A1",)


def test_a_marker_mid_answer_costs_its_line_and_nothing_more() -> None:
    """A model that puts the line in the wrong place should not be censored.

    The prompt says the line goes last. If it does not, the honest failure
    is losing the line it was written on - not swallowing the rest of an
    answer somebody is waiting for.
    """
    text, keys = run(f"Birinchi.\n{MARK} A1\nIkkinchi jumla.")

    assert "Birinchi." in text
    assert "Ikkinchi jumla." in text
    assert "A1" not in text
    assert keys == ("A1",)


def test_a_line_with_no_recognisable_key_offers_nothing() -> None:
    text, keys = run(f"{MARK} hech narsa")

    assert keys == ()
    assert "hech narsa" not in text


def test_the_key_is_not_confused_with_a_figure_on_the_same_line() -> None:
    """The choice line is read for keys, never for numbers.

    The gate that masks invented figures runs *behind* this one, so
    anything left on the choice line is out of its reach by construction -
    which is the reason the order is what it is.
    """
    _, keys = run(f"{MARK} A1 15000")

    assert keys == ("A1",)


# --- Replies ----------------------------------------------------------------


def replies_of(*pieces: str) -> tuple[str, tuple[str, ...]]:
    gate = ChoiceGate()
    out = [gate.feed(piece) for piece in pieces]
    out.append(gate.flush())
    return "".join(out), gate.replies


def test_a_reply_line_becomes_buttons_and_never_reaches_the_reader() -> None:
    text, replies = replies_of(
        f"Mijoz qanday muammo bilan keladi?\n{REPLY_MARK} Navbat | Narx | Vaqt\n"
    )

    assert text.strip() == "Mijoz qanday muammo bilan keladi?"
    assert REPLY_MARK not in text
    assert replies == ("Navbat", "Narx", "Vaqt")


def test_a_reply_line_split_across_chunks_is_read_whole() -> None:
    """A reply cut at a chunk boundary must not become two half-replies."""
    text, replies = replies_of("Savol?\n%%REP", "LY%% Oldin va ke", "yin | Jarayon")

    assert text.strip() == "Savol?"
    assert replies == ("Oldin va keyin", "Jarayon")


def test_no_more_replies_than_five() -> None:
    _, replies = replies_of(f"{REPLY_MARK} a | b | c | d | e | f | g")

    assert len(replies) == MAX_REPLIES == 5


def test_an_answer_with_no_question_carries_no_replies() -> None:
    _, replies = replies_of("Murojaat qimmatlashdi, chunki sarf oshgan.")

    assert replies == ()


def test_a_reply_too_long_for_a_button_is_dropped_not_cut() -> None:
    long = "so'z " * 20
    _, replies = replies_of(f"{REPLY_MARK} Ha | {long}| Yo'q")

    assert replies == ("Ha", "Yo'q")
    assert all(len(reply) <= REPLY_MAX_CHARS for reply in replies)


def test_quotation_marks_and_repeats_are_taken_off() -> None:
    _, replies = replies_of(f'{REPLY_MARK} «Ha» | "ha" |  Yo\'q  | ')

    assert replies == ("Ha", "Yo'q")


def test_a_choice_and_replies_on_one_answer_are_read_apart() -> None:
    gate = ChoiceGate()
    text = gate.feed(f"Javob?\n{MARK} A1\n{REPLY_MARK} Ha | Yo'q") + gate.flush()

    assert text.strip() == "Javob?"
    assert gate.keys == ("A1",)
    assert gate.replies == ("Ha", "Yo'q")


def test_a_reply_with_an_invented_figure_loses_its_button() -> None:
    """A reply is sent in the owner's name, so its figures are checked like
    the answer's: a price nobody supplied would be the owner quoting one."""
    kept = vetted_replies(
        ("200 000 so'm", "Narx yo'q", "15 soniya", "150 000 so'm"),
        allowed=frozenset({"150000"}),
        quoted=frozenset(),
    )

    assert kept == ("Narx yo'q", "15 soniya", "150 000 so'm")
