"""The same answer, in the small set of tags Telegram accepts."""

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
FACT: Final = re.compile(
    r"^\s*(?:[-*•]\s+)?\*{0,2}(«[^»\n]{1,80}»)\*{0,2}\s+—\s+(\S.*)$"
)

MESSAGE_LIMIT: Final = 3500

BULLET_MARK: Final = "• "


def render_messages(text: str, *, limit: int = MESSAGE_LIMIT) -> list[str]:
    """One answer as the messages it should be sent in, in order."""
    escaped = html.escape(text, quote=False)
    blocks = [
        rendered
        for block in BLANK_LINE.split(escaped)
        if block.strip()
        if (rendered := _block(block.strip("\n")))
    ]
    return _packed(blocks, limit=limit)


def _packed(blocks: list[str], *, limit: int) -> list[str]:
    """Blocks gathered into as few messages as fit, split between them."""
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
    """A table as lines, because Telegram has no table and no tab stop."""
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
    """A heading cell, bold once."""
    drawn = _inline(text)
    return drawn if "<b>" in drawn else f"<b>{drawn}</b>"


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _inline(text: str) -> str:
    """Bold and code, in that order, and nothing else."""
    with_code = CODE.sub(lambda match: f"<code>{match.group(1)}</code>", text)
    return BOLD.sub(lambda match: f"<b>{match.group(1)}</b>", with_code)


def _units(text: str) -> int:
    """How long Telegram thinks this is: UTF-16 code units."""
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
