"""The renderer, and the one thing it must never do."""

from html.parser import HTMLParser

import pytest

from core.chat.markdown import render

# Everything the renderer can emit. Asserting against this rather than
# against a blocklist is the point: the question is not "was the attack
# filtered out" but "could any tag at all arrive that we did not write".
ALLOWED = {
    "p",
    "dl",
    "dt",
    "dd",
    "br",
    "strong",
    "code",
    "ul",
    "ol",
    "li",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
}


class Tags(HTMLParser):
    """Every tag and attribute in the output."""

    def __init__(self) -> None:
        super().__init__()
        self.names: set[str] = set()
        self.attributes: list[tuple[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.names.add(tag)
        self.attributes += attrs


def tags_in(html: str) -> Tags:
    parser = Tags()
    parser.feed(html)
    return parser


@pytest.mark.parametrize(
    "attack",
    [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "<a href='javascript:alert(1)'>x</a>",
        "**<script>alert(1)</script>**",
        "| <script>a</script> | b |\n|---|---|\n| 1 | 2 |",
        "- <iframe src=evil></iframe>",
        "<style>body{display:none}</style>",
    ],
)
def test_no_markup_from_the_model_survives(attack: str) -> None:
    """Escaped first, formatted second, and that order is the whole argument.

    By the time any tag is written, every ``<`` the model sent is already
    ``&lt;``. So the assertion is not that a filter removed something - it
    is that nothing outside the renderer's own closed set exists at all,
    and that no element carries an attribute, because the renderer never
    writes one.
    """
    found = tags_in(render(attack))

    assert found.names <= ALLOWED
    assert found.attributes == []


def test_the_subset_renders() -> None:
    html = render("**Qalin** va `kod`\n\n- bir\n- ikki")

    assert "<strong>Qalin</strong>" in html
    assert "<code>kod</code>" in html
    assert "<ul><li>bir</li><li>ikki</li></ul>" in html


def test_a_table_renders() -> None:
    html = render("| a | b |\n|---|---|\n| 1 | 2 |")

    assert "<table>" in html
    assert "<th>a</th>" in html
    assert "<td>2</td>" in html


def test_half_written_markup_renders_as_itself() -> None:
    """Every frame re-renders the whole answer, so a chunk may cut a ``**``.

    Literal asterisks for one frame and correct bold on the next is the
    right failure: a renderer that guessed at the missing half would
    produce markup the model never asked for.
    """
    assert "<strong>" not in render("**yarim")


def test_nothing_outside_the_subset_becomes_a_tag() -> None:
    assert "<h1>" not in render("# Sarlavha")
    assert "<a " not in render("[matn](https://example.com)")


# --- Rows -----------------------------------------------------------------
#
# The one piece of layout the model can ask for, and it asks by writing a
# shape rather than by naming a component: a name in guillemets, a long
# dash, then what that name did. Everything else it writes is prose.


def test_a_run_of_named_lines_becomes_rows() -> None:
    """Two campaigns compared are two rows, not a paragraph.

    The names go in one column and the figures in the other, which is the
    whole reason the shape is worth recognising: a reader comparing two
    campaigns reads down, and prose can only be read along.
    """
    html = render("«Implant» — 38 USD · Murojaat: 1\n«Bahor» — 45 USD · natija yo'q")

    assert html == (
        "<dl><dt>«Implant»</dt><dd>38 USD · Murojaat: 1</dd>"
        "<dt>«Bahor»</dt><dd>45 USD · natija yo'q</dd></dl>"
    )


def test_a_row_written_as_a_list_item_is_still_a_row() -> None:
    """Told to write a list, a model writes the marks of one.

    The dash in front is its habit rather than its meaning, and a row that
    lost its layout over one would be a rule nobody could see they had
    broken.
    """
    assert "<dl>" in render("- «Bahor» — 45 USD")
    assert "<li>" not in render("- «Bahor» — 45 USD")


def test_a_name_the_model_also_made_bold_is_not_bold_twice() -> None:
    """The column is already set in the weight a name is read in.

    Asked for the name column and for bold in the same line, the model
    sometimes writes both. The asterisks go: a row where one name is
    heavier than the ones under it reads as a name that means more, which
    is a claim the model did not intend to make.
    """
    assert render("**«Bahor»** — 45 USD") == "<dl><dt>«Bahor»</dt><dd>45 USD</dd></dl>"


def test_a_sentence_about_the_same_campaign_stays_a_sentence() -> None:
    """The shape is the choice, so anything outside it is prose.

    A guess in the other direction - drawing every line that names a
    campaign as a row - would break a paragraph in half the moment somebody
    asked why one of their campaigns had stopped.
    """
    said = render("«Bahor» kampaniyasi kecha 45 USD sarfladi.")

    assert said.startswith("<p>")
    assert "<dl>" not in said


def test_a_hyphen_is_not_the_dash_the_rows_are_written_with() -> None:
    assert "<dl>" not in render("«Bahor» - 45 USD")


def test_half_a_row_renders_as_itself() -> None:
    """Every frame re-renders the whole answer, so a chunk cuts anywhere."""
    assert "<dl>" not in render("«Bahor")
    assert "<dl>" not in render("«Bahor» —")
