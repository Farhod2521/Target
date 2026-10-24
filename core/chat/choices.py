"""The choice an answer may end with, split off before anybody reads it."""

import re
from dataclasses import dataclass, field
from typing import Final

from core.chat.verify import FigureGate

MARK: Final = "%%CHOICE%%"

KEY: Final = re.compile(r"\b([A-Z]\d{1,2})\b")

MAX_CHOICES: Final = 2

REPLY_MARK: Final = "%%REPLY%%"

REPLY_SEPARATOR: Final = "|"

MAX_REPLIES: Final = 5

REPLY_MAX_CHARS: Final = 48

_QUOTES: Final = "\"'«»“”„`"

_MARKS: Final = (MARK, REPLY_MARK)


def _held(text: str) -> str:
    """The trailing part of ``text`` that could still become the marker."""
    longest = max(len(mark) for mark in _MARKS) - 1
    for size in range(min(longest, len(text)), 0, -1):
        if any(mark.startswith(text[-size:]) for mark in _MARKS):
            return text[-size:]
    return ""


def _first_mark(buffer: str) -> tuple[int, str]:
    """Where the earliest marker starts in ``buffer``, and which one it is."""
    found = [(at, mark) for mark in _MARKS if (at := buffer.find(mark)) >= 0]
    return min(found) if found else (-1, "")


@dataclass(slots=True)
class ChoiceGate:
    """Passes an answer through, keeping the choice line to itself."""

    keys: tuple[str, ...] = ()
    replies: tuple[str, ...] = ()
    _tail: str = field(default="", repr=False)
    _marked: str = field(default="", repr=False)

    def feed(self, text: str) -> str:
        """The part of ``text`` that is prose, with any choice line removed."""
        out: list[str] = []
        buffer = self._tail + text
        self._tail = ""

        while buffer:
            if self._marked:
                line, newline, rest = buffer.partition("\n")
                if not newline:
                    self._tail = line
                    break
                self._take(line)
                self._marked = ""
                buffer = rest
                continue

            at, mark = _first_mark(buffer)
            if at >= 0:
                out.append(buffer[:at])
                self._marked = mark
                buffer = buffer[at + len(mark) :]
                continue

            held = _held(buffer)
            out.append(buffer[: len(buffer) - len(held)] if held else buffer)
            self._tail = held
            break

        return "".join(out)

    def flush(self) -> str:
        """Whatever was held back and turned out not to be a marker."""
        held, self._tail = self._tail, ""
        if self._marked:
            self._take(held)
            self._marked = ""
            return ""
        return held

    def _take(self, line: str) -> None:
        if self._marked == REPLY_MARK:
            self._take_replies(line)
        else:
            self._take_keys(line)

    def _take_replies(self, line: str) -> None:
        """Read the offered answers out of a reply line, in the order written."""
        found = list(self.replies)
        seen = {reply.casefold() for reply in found}
        for part in line.split(REPLY_SEPARATOR):
            reply = " ".join(part.split()).strip(_QUOTES).strip()
            if not reply or len(reply) > REPLY_MAX_CHARS:
                continue
            if reply.casefold() in seen:
                continue
            seen.add(reply.casefold())
            found.append(reply)
        self.replies = tuple(found[:MAX_REPLIES])

    def _take_keys(self, line: str) -> None:
        """Read keys out of the choice line, in the order they were written."""
        found = list(self.keys)
        for key in KEY.findall(line):
            if key not in found:
                found.append(key)
        self.keys = tuple(found[:MAX_CHOICES])


def vetted_replies(
    replies: tuple[str, ...], *, allowed: frozenset[str], quoted: frozenset[str]
) -> tuple[str, ...]:
    """The replies whose figures the answer's own gate would have let through."""
    kept: list[str] = []
    for reply in replies:
        gate = FigureGate(allowed=allowed, quoted=quoted)
        gate.feed(reply)
        gate.flush()
        if not gate.masked:
            kept.append(reply)
    return tuple(kept)


__all__ = [
    "MARK",
    "MAX_CHOICES",
    "MAX_REPLIES",
    "REPLY_MARK",
    "REPLY_MAX_CHARS",
    "REPLY_SEPARATOR",
    "ChoiceGate",
    "vetted_replies",
]
