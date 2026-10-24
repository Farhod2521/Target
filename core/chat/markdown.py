"""Claude's Markdown, turned into the small set of tags a chat bubble needs."""

import html
import re
from typing import Final

BOLD: Final = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
CODE: Final = re.compile(r"`([^`]+)`")
HEADING: Final = re.compile(r"^#{1,6}\s+(.*)$")
BULLET: Final = re.compile(r"^\s*[-*]\s+(.*)$")
NUMBERED: Final = re.compile(r"^\s*\d+[.)]\s+(.*)$")
DIVIDER: Final = re.compile(r"^\|?[\s:|-]*-[\s:|-]*\|[\s:|-]*$")
BLANK_LINE: Final = re.compile(r"\n\s*\n")
FACT: Final = re.compile(
    r"^\s*(?:[-*•]\s+)?\*{0,2}(«[^»\n]{1,80}»)\*{0,2}\s+—\s+(\S.*)$"
)


def render(text: str) -> str:
    """The answer as HTML, safe to mark safe."""
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
    if FACT.match(line):
        return "fact", line
    if match := BULLET.match(line):
        return "bullet", match.group(1)
    if match := NUMBERED.match(line):
        return "numbered", match.group(1)
    return "text", line


def _emit(kind: str, items: list[str]) -> str:
    if kind == "fact":
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
    """Bold and code, in that order."""
    with_code = CODE.sub(lambda match: f"<code>{match.group(1)}</code>", text)
    return BOLD.sub(lambda match: f"<strong>{match.group(1)}</strong>", with_code)
