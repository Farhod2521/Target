"""The same answer, in the small set of tags Telegram accepts.

``core.chat.markdown`` renders for a chat bubble in a browser: paragraphs,
lists, a table. Telegram's parser knows none of those. It has about nine
tags and treats an unknown one as an error - and an error means the whole
message is refused, not that one tag is dropped. So this is a second
renderer over the same Markdown rather than a filter over the first one's
output: filtering HTML is a list of things to remove, and the list is
wrong the first time the other renderer learns a new tag.

**Escaped first, formatted second**, which is the security argument the
browser renderer makes and this one inherits: by the time any tag is
written here every ``<`` that came from the model is already ``&lt;``, so
the only tags in the output are the ones this module wrote.

**Split rather than cut.** Telegram refuses a message over 4096 units, and
``telegramkit`` shortens one that arrives too long - which is right for a
notification, whose last sentence is a repetition of its first. An answer
somebody asked for is not that: the part that gets cut is usually the part
that concludes. So a long answer comes back as several messages, split
between blocks, where the tags are already closed.
"""

import html
import re
from typing import Final

BOLD: Final = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
CODE: Final = re.compile(r"`([^`]+)`")
HEADING: Final = re.compile(r"^#{1,6}\s+(.*)$")
BULLET: Final = re.compile(r"^\s*[-*]\s+(.*)$")
NUMBERED: Final = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")
DIVIDER: Final = re.compile(r"^\|?[\s:|-]*-[\s:|-]*\|[\s:|-]*$")
BLANK_LINE: Final = re.compile(r"\n\s*\n")
# The shape the prompt asks for when two things are compared - see
# ``core.chat.markdown``, where the same line becomes a row of a table.
# Here it stays a line, because a phone has one column: the name is set in
# bold and the figures follow it, which is how every message this product
# sends already names a campaign.
FACT: Final = re.compile(
    r"^\s*(?:[-*•]\s+)?\*{0,2}(«[^»\n]{1,80}»)\*{0,2}\s+—\s+(\S.*)$"
)

# Telegram's ceiling is 4096; this is what one message is allowed to
# reach before the next block starts a new one. The gap is deliberate
# slack rather than arithmetic: what is measured here is the rendered
# HTML, and the reader is better served by a break at a paragraph than
# by a message that fits to the byte.
MESSAGE_LIMIT: Final = 3500

# What a bullet becomes. Telegram has no list, and a line starting with a
# dash reads as a subtraction in a message about money.
BULLET_MARK: Final = "• "


def render_messages(text: str, *, limit: int = MESSAGE_LIMIT) -> list[str]:
    """One answer as the messages it should be sent in, in order.

    Empty input gives an empty list rather than one empty message: a
    caller with nothing to say should send nothing, and Telegram refuses
    an empty body anyway.
    """
    escaped = html.escape(text, quote=False)
    blocks = [
        rendered
        for block in BLANK_LINE.split(escaped)
        if block.strip()
        if (rendered := _block(block.strip("\n")))
    ]
    return _packed(blocks, limit=limit)


def _packed(blocks: list[str], *, limit: int) -> list[str]:
    """Blocks gathered into as few messages as fit, split between them.

    A block longer than a whole message on its own is split by line, and
    a line longer than that by force. Neither is common - a paragraph of
    three thousand characters is not an answer anybody reads - but a
    renderer that returns something Telegram refuses has failed at the
    one thing it is for.
    """
    messages: list[str] = []
    current = ""
    for block in blocks:
        for piece in _within(block, limit=limit):
            joined = f"{current}\n\n{piece}" if current else piece
            if current and _units(joined) > limit:
                messages.append(current)
                current = piece
            else:
                current = joined
    if current:
        messages.append(current)
    return messages


def _within(block: str, *, limit: int) -> list[str]:
    """One block, in pieces that each fit on their own."""
    if _units(block) <= limit:
        return [block]

    pieces: list[str] = []
    current = ""
    for line in block.split("\n"):
        joined = f"{current}\n{line}" if current else line
        if current and _units(joined) > limit:
            pieces.append(current)
            current = line
        else:
            current = joined
        while _units(current) > limit:
            pieces.append(_prefix(current, limit))
            current = current[len(_prefix(current, limit)) :]
    if current:
        pieces.append(current)
    return pieces


def _block(block: str) -> str:
    """One paragraph-sized piece, as lines Telegram can draw."""
    lines = block.split("\n")
    if _is_table(lines):
        return _table(lines)
    return "\n".join(_line(line) for line in lines if line.strip())


def _line(line: str) -> str:
    if match := FACT.match(line):
        return f"{_bold(match.group(1))} — {_inline(match.group(2))}"
    if match := HEADING.match(line):
        # Bold rather than a heading. Telegram has no heading, and a line
        # of capitals would be shouting rather than structure.
        return _bold(match.group(1))
    if match := BULLET.match(line):
        return BULLET_MARK + _inline(match.group(1))
    if match := NUMBERED.match(line):
        return f"{match.group(1)}. {_inline(match.group(2))}"
    return _inline(line)


def _is_table(lines: list[str]) -> bool:
    return (
        len(lines) >= 2
        and lines[0].lstrip().startswith("|")
        and bool(DIVIDER.match(lines[1].strip()))
    )


def _table(lines: list[str]) -> str:
    """A table as lines, because Telegram has no table and no tab stop.

    Two columns become "name — value", which is what most of these
    actually are: a figure and its label. Anything wider is joined with a
    separator rather than aligned - a monospace block would align it and
    would also be unreadable at a phone's width.
    """
    head = _cells(lines[0])
    rows = [_cells(line) for line in lines[2:] if line.strip().startswith("|")]
    if len(head) == 2:
        drawn = [f"{_bold(head[0])} — {_bold(head[1])}"]
        drawn += [
            f"{_inline(row[0])} — {_inline(row[1])}" for row in rows if len(row) == 2
        ]
        return "\n".join(drawn)

    drawn = [" · ".join(_bold(cell) for cell in head)]
    drawn += [" · ".join(_inline(cell) for cell in row) for row in rows]
    return "\n".join(drawn)


def _bold(text: str) -> str:
    """A heading cell, bold once.

    A header the model wrote as ``**Narx**`` is already bold by the time
    this is reached, and wrapping it again would nest one ``<b>`` inside
    another. Telegram's parser is documented as accepting nested
    entities and refuses the *whole message* when it does not - which is
    a bad thing to find out about on somebody's phone.
    """
    drawn = _inline(text)
    return drawn if "<b>" in drawn else f"<b>{drawn}</b>"


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _inline(text: str) -> str:
    """Bold and code, in that order, and nothing else.

    ``<b>`` and not ``<strong>``: both are documented, and one of them is
    what every example in Telegram's own reference uses.
    """
    with_code = CODE.sub(lambda match: f"<code>{match.group(1)}</code>", text)
    return BOLD.sub(lambda match: f"<b>{match.group(1)}</b>", with_code)


def _units(text: str) -> int:
    """How long Telegram thinks this is: UTF-16 code units.

    An emoji is one character to Python and two to the API, and an answer
    about a campaign called "🚀 Yangi" is not a rare case.
    """
    return len(text.encode("utf-16-le")) // 2


def _prefix(text: str, units: int) -> str:
    """The longest prefix inside ``units``, never splitting a pair."""
    used = 0
    for index, char in enumerate(text):
        cost = 2 if char > "￿" else 1
        if used + cost > units:
            return text[:index]
        used += cost
    return text


__all__ = ["MESSAGE_LIMIT", "render_messages"]
