"""Subtitles for the finished video, from the words of the source."""

from dataclasses import dataclass

from videokit import Cut

from core.montage.fillers import is_filler

MAX_WORDS_PER_LINE = 5
MAX_LINE_SECONDS = 2.6
PAUSE_SECONDS = 0.6


@dataclass(frozen=True, slots=True)
class SpokenWord:
    """A word and when it was said, by the source's clock."""

    text: str
    start: float
    end: float


@dataclass(frozen=True, slots=True)
class Line:
    """One subtitle, by the finished video's clock, word by word."""

    text: str
    start: float
    end: float
    words: tuple[SpokenWord, ...] = ()


def lines_for(*, words: tuple[SpokenWord, ...], cuts: tuple[Cut, ...]) -> list[Line]:
    """The subtitles of the finished video, in playing order."""
    kept = _without_fillers(words)
    lines: list[Line] = []
    cursor = 0.0
    for cut in cuts:
        offset = cursor - cut.start
        placed = [
            SpokenWord(
                text=word.text,
                start=round(word.start + offset, 3),
                end=round(min(word.end, cut.end) + offset, 3),
            )
            for word in kept
            if word.start >= cut.start and word.end <= cut.end + 0.05
        ]
        lines.extend(_grouped(placed))
        cursor += cut.end - cut.start
    return lines


def srt(lines: list[Line]) -> str:
    """The lines as an SRT file."""
    blocks = [
        f"{number}\n{_stamp(line.start)} --> {_stamp(line.end)}\n{line.text}\n"
        for number, line in enumerate(lines, start=1)
    ]
    return "\n".join(blocks)


def _grouped(words: list[SpokenWord]) -> list[Line]:
    lines: list[Line] = []
    current: list[SpokenWord] = []
    for word in words:
        if current and (
            len(current) >= MAX_WORDS_PER_LINE
            or word.end - current[0].start > MAX_LINE_SECONDS
            or word.start - current[-1].end > PAUSE_SECONDS
        ):
            lines.append(_line(current))
            current = []
        current.append(word)
    if current:
        lines.append(_line(current))
    return lines


def _without_fillers(words: tuple[SpokenWord, ...]) -> list[SpokenWord]:
    """The words a reader needs; a filler is judged by what follows it."""
    kept: list[SpokenWord] = []
    for index, word in enumerate(words):
        following = words[index + 1] if index + 1 < len(words) else None
        pause = following.start - word.end if following else float("inf")
        if not is_filler(
            word.text,
            pause_after=pause,
            next_text=following.text if following else "",
        ):
            kept.append(word)
    return kept


def _line(words: list[SpokenWord]) -> Line:
    return Line(
        text=" ".join(word.text for word in words),
        start=words[0].start,
        end=max(words[-1].end, words[0].start + 0.3),
        words=tuple(words),
    )


def _stamp(seconds: float) -> str:
    millis = max(round(seconds * 1000), 0)
    hours, rest = divmod(millis, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"
