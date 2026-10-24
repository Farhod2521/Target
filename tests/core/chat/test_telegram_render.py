"""The same answer, in the tags Telegram accepts.

Telegram's parser knows about nine tags and treats an unknown one as an
error - and an error refuses the whole message rather than dropping the
tag. So the questions here are: does anything the browser renderer writes
survive into this one, and does a long answer come back as messages
Telegram will actually accept.
"""

from core.chat.markdown import render as render_html
from core.chat.telegram import MESSAGE_LIMIT, render_messages


def one(text: str) -> str:
    """The single message this renders to. Fails loudly if it is not one."""
    parts = render_messages(text)
    assert len(parts) == 1, parts
    return parts[0]


# --- What survives --------------------------------------------------------


def test_bold_is_the_tag_telegram_documents() -> None:
    assert one("**Sabab**: raqobat") == "<b>Sabab</b>: raqobat"


def test_a_heading_becomes_bold_rather_than_a_heading() -> None:
    """Telegram has no heading, and a line of capitals is shouting."""
    assert one("## Natija") == "<b>Natija</b>"


def test_a_list_becomes_lines_with_a_bullet() -> None:
    """A leading dash reads as a subtraction in a message about money."""
    assert one("- Birinchi\n- Ikkinchi") == "• Birinchi\n• Ikkinchi"


def test_a_numbered_list_keeps_its_numbers() -> None:
    assert one("1. Byudjet\n2. Auditoriya") == "1. Byudjet\n2. Auditoriya"


def test_a_two_column_table_becomes_a_figure_and_its_label() -> None:
    """Which is what most of them are. A monospace block would align it
    and would also be unreadable at a phone's width."""
    drawn = one("| Kampaniya | Narx |\n| --- | --- |\n| Yozgi | 20 000 |")

    assert drawn == "<b>Kampaniya</b> — <b>Narx</b>\nYozgi — 20 000"


def test_a_wider_table_is_joined_rather_than_aligned() -> None:
    drawn = one("| A | B | C |\n| --- | --- | --- |\n| 1 | 2 | 3 |")

    assert drawn.endswith("1 · 2 · 3")


def test_a_heading_the_model_already_made_bold_is_bold_once() -> None:
    """Telegram refuses the *whole message* when it cannot parse the
    entities, so a ``<b>`` wrapped around a ``<b>`` is not a cosmetic
    problem - it is an answer nobody receives."""
    assert "<b><b>" not in one("## **Natija**")
    assert one("## **Natija**") == "<b>Natija</b>"


def test_a_table_header_the_model_already_made_bold_is_bold_once() -> None:
    drawn = one("| **Kampaniya** | **Narx** |\n| --- | --- |\n| Yozgi | 20 000 |")

    assert "<b><b>" not in drawn
    assert drawn.startswith("<b>Kampaniya</b> — <b>Narx</b>")


def test_no_browser_tag_reaches_telegram() -> None:
    """The whole reason this is a second renderer rather than a filter.

    A filter is a list of tags to remove, and the list is wrong the first
    time the other renderer learns a new one.
    """
    drawn = one("## Sarlavha\n\n- bir\n- ikki")

    for tag in ("<p>", "<ul>", "<li>", "<br>", "<table>", "<strong>"):
        assert tag not in drawn


# --- What cannot get out --------------------------------------------------


def test_the_model_cannot_write_a_tag() -> None:
    """Escaped first and formatted second, which is the security argument.

    By the time any tag is written, every ``<`` that came from the model
    is already ``&lt;`` - so the only tags in the output are this
    module's own.
    """
    drawn = one("<script>alert(1)</script> va 5 < 7")

    assert "<script>" not in drawn
    assert "&lt;script&gt;" in drawn
    assert "5 &lt; 7" in drawn


# --- Length ---------------------------------------------------------------


def test_a_long_answer_is_split_rather_than_cut() -> None:
    """The part a cut removes is usually the part that concludes."""
    parts = render_messages(
        "\n\n".join(f"Xat {n}. " + "so'z " * 200 for n in range(10))
    )

    assert len(parts) > 1
    assert all(len(part) <= MESSAGE_LIMIT for part in parts)
    assert "Xat 9." in parts[-1]


def test_a_single_paragraph_too_long_for_one_message_still_fits() -> None:
    """Not common - nobody reads a three-thousand-character paragraph -
    but a renderer that returns something Telegram refuses has failed at
    the one thing it is for."""
    parts = render_messages("so'z " * 3000)

    assert len(parts) > 1
    assert all(len(part) <= MESSAGE_LIMIT for part in parts)


def test_the_limit_is_measured_the_way_telegram_measures_it() -> None:
    """An emoji is one character to Python and two to the API."""
    parts = render_messages("🚀" * 2000)

    assert all(len(part.encode("utf-16-le")) // 2 <= MESSAGE_LIMIT for part in parts)


def test_nothing_to_say_sends_nothing() -> None:
    """Telegram refuses an empty body anyway."""
    assert render_messages("   \n\n  ") == []


# --- Rows -----------------------------------------------------------------


def test_a_named_line_keeps_its_name_in_bold() -> None:
    """A phone has one column, so the row stays a line.

    The same line the browser draws as a row of a table, set the way every
    other message this product sends names a campaign - which is what makes
    an answer read here as coming from the same place as the morning's
    report.
    """
    assert one("«Bahor» — 45 USD · natija yo'q") == (
        "<b>«Bahor»</b> — 45 USD · natija yo'q"
    )


def test_a_name_the_model_made_bold_is_bold_once() -> None:
    """Telegram refuses a whole message over a nested entity."""
    assert one("**«Bahor»** — 45 USD") == "<b>«Bahor»</b> — 45 USD"


def test_both_surfaces_read_the_same_line_as_a_row() -> None:
    """The shape is a product rule, and two renderers know it separately.

    They are deliberately not one renderer - Telegram's nine tags and a
    browser's markup are different problems - so the thing to hold is that
    a line drawn as a row on one surface is drawn as a row on the other.
    A reader with the cabinet open on a desk and the bot open on a phone
    is looking at one answer.
    """
    rows = ("«Bahor» — 45 USD", "- «Bahor» — 45 USD", "**«Bahor»** — 45 USD")
    prose = ("«Bahor» kampaniyasi 45 USD sarfladi", "«Bahor» - 45 USD", "«Bahor» —")

    for line in rows:
        assert "<dl>" in render_html(line), line
        assert one(line).startswith("<b>«Bahor»</b> — "), line
    for line in prose:
        assert "<dl>" not in render_html(line), line
        assert not one(line).startswith("<b>«Bahor»</b> — "), line
