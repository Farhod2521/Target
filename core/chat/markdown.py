"""Claude's Markdown, turned into the small set of tags a chat bubble needs.

**Everything is escaped first, and only then formatted.** That order is the
whole security argument, and it is stronger than filtering the model's HTML
afterwards would be: by the time any tag is written here, every ``<`` that
came from the model is already ``&lt;``. The model cannot emit a tag,
because what it emits is no longer markup - it is text. The only tags in
the output are the ones this module wrote itself.

That is what lets a chat answer be rendered at all in a codebase with no
``|safe`` anywhere: the one value marked safe is the one built here, out of
a closed set of tags, from input that was neutralised before it was read.

The subset is small on purpose - bold, lists, a table, inline code. It is
what the prompt asks for and what an answer to "why did leads get dearer"
actually needs. Anything outside it stays as literal text, which is the
safe direction for a renderer to fail in.
"""

import html
import re
from typing import Final

BOLD: Final = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
CODE: Final = re.compile(r"`([^`]+)`")
HEADING: Final = re.compile(r"^#{1,6}\s+(.*)$")
BULLET: Final = re.compile(r"^\s*[-*]\s+(.*)$")
NUMBERED: Final = re.compile(r"^\s*\d+[.)]\s+(.*)$")
# The row of dashes under a table's header. Without one, a line of pipes is
# just a line with pipes in it.
DIVIDER: Final = re.compile(r"^\|?[\s:|-]*-[\s:|-]*\|[\s:|-]*$")
BLANK_LINE: Final = re.compile(r"\n\s*\n")
# A name and what it did, on one line: «Bahor» — 45 USD · natija yo'q.
#
# **The shape is the instruction.** The prompt asks for it wherever two
# things are compared, and a run of such lines is drawn as rows: the names
# line up in one column and their figures in the other, which is what the
# eye needs to compare them and what a paragraph cannot give. A sentence
# about the same two campaigns is drawn as a sentence - so the model picks
# between the two by writing one or the other, and cannot ask for a layout
# the product has not built.
#
# The bullet and the asterisks are tolerated rather than expected: a model
# that has been told to write a list writes the marks of one, and a row
# that lost its layout over a stray "-" would be a rule nobody could see
# they had broken.
FACT: Final = re.compile(
    r"^\s*(?:[-*•]\s+)?\*{0,2}(«[^»\n]{1,80}»)\*{0,2}\s+—\s+(\S.*)$"
)


def render(text: str) -> str:
    """The answer as HTML, safe to mark safe.

    Called on the whole answer so far, once per streamed frame. Re-rendering
    beats patching: a frame that arrives mid-``**`` renders the asterisks as
    themselves and the next frame corrects it, where a patch would have to
    guess what the half-written markup was going to be.
    """
    escaped = html.escape(text, quote=False)
    return "".join(
        _block(block.strip("\n"))
        for block in BLANK_LINE.split(escaped)
        if block.strip()
    )


def _block(block: str) -> str:
    """One paragraph-sized piece: a table, or runs of like-shaped lines."""
    lines = block.split("\n")
    if _is_table(lines):
        return _table(lines)

    out: list[str] = []
    run: list[str] = []
    kind = ""
    for line in lines:
        shape, content = _classify(line)
        if run and shape != kind:
            out.append(_emit(kind, run))
            run = []
        kind = shape
        run.append(content)
    if run:
        out.append(_emit(kind, run))
    return "".join(out)


def _classify(line: str) -> tuple[str, str]:
    if match := HEADING.match(line):
        return "heading", match.group(1)
    # Before the bullet: a row written as a list item is a row, and the
    # dash in front of it is the model's habit rather than its meaning.
    if FACT.match(line):
        return "fact", line
    if match := BULLET.match(line):
        return "bullet", match.group(1)
    if match := NUMBERED.match(line):
        return "numbered", match.group(1)
    return "text", line


def _emit(kind: str, items: list[str]) -> str:
    if kind == "fact":
        # A name and its figures, as the one pairing HTML already has. No
        # class and no attribute: the renderer writes none anywhere, and a
        # <dl> appears nowhere else in an answer, so the stylesheet can
        # reach these rows by the tag alone.
        pairs = [match.groups() for item in items if (match := FACT.match(item))]
        return (
            "<dl>"
            + "".join(
                f"<dt>{_inline(name)}</dt><dd>{_inline(said)}</dd>"
                for name, said in pairs
            )
            + "</dl>"
        )
    if kind == "bullet":
        return "<ul>" + "".join(f"<li>{_inline(item)}</li>" for item in items) + "</ul>"
    if kind == "numbered":
        return "<ol>" + "".join(f"<li>{_inline(item)}</li>" for item in items) + "</ol>"
    if kind == "heading":
        # Not an <h*>. These sit inside a chat bubble, and a heading level
        # there would claim a place in the page's outline that it has not
        # got - a screen reader would announce it as document structure.
        return "".join(f"<p><strong>{_inline(item)}</strong></p>" for item in items)

    body = "<br>".join(_inline(item) for item in items if item.strip())
    return f"<p>{body}</p>" if body else ""


def _is_table(lines: list[str]) -> bool:
    return (
        len(lines) >= 2
        and lines[0].lstrip().startswith("|")
        and bool(DIVIDER.match(lines[1].strip()))
    )


def _table(lines: list[str]) -> str:
    head = "".join(f"<th>{_inline(cell)}</th>" for cell in _cells(lines[0]))
    body = "".join(
        "<tr>" + "".join(f"<td>{_inline(cell)}</td>" for cell in _cells(line)) + "</tr>"
        for line in lines[2:]
        if line.strip().startswith("|")
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _inline(text: str) -> str:
    """Bold and code, in that order.

    Code first so that asterisks inside a code span stay asterisks - which
    is the whole point of writing them in one.
    """
    with_code = CODE.sub(lambda match: f"<code>{match.group(1)}</code>", text)
    return BOLD.sub(lambda match: f"<strong>{match.group(1)}</strong>", with_code)
