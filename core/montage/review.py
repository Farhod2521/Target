"""Looking at the finished video: which frames, and what Claude answers."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field
from videokit import ComponentUse
from videokit.components import component

FEWEST: Final = 6
MOST: Final = 8
MIN_APART: Final = 0.6
END_BEFORE: Final = 0.6
AFTER_BEAT: Final = 0.6
BEFORE_EXIT: Final = 0.4
LINE_SETTLES: Final = 0.2
_LINE_EARLY: Final = 0.05
MAX_ISSUES: Final = 20

IssueType = Literal[
    "text_cut_off",
    "text_unreadable",
    "text_over_face",
    "empty_panel",
    "logo_colors",
    "overlap",
    "black_frame",
    "off_brand",
    "other",
]
Severity = Literal["low", "medium", "high"]

_SHOWS: Final[dict[str, str]] = {
    "hook_title": "the opening headline",
    "chips_list": "a panel over the top half with a title and chips",
    "lower_third": "the name bar with the business's name or logo",
    "cta_button": "the call-to-action button with contacts",
    "end_card": "the closing card with the logo and name",
    "end_cta": "the closing button with the handle and phone under it",
    "hook_counter": "an opening number counting up, with a label and stars",
    "headline_slam": "a headline with a bold label slammed under it",
    "stamp_badge": "a stamp-like seal with a short line under it",
    "price_tag": "a price, the old one struck through, with a discount badge",
    "checklist": "a panel over the top half with a title and ticked rows",
    "phone_mockup": "a panel over the top half with a phone showing a post",
    "reach_globe": "a panel over the top half with a globe and arcs",
    "sticker_fly": "a large sticker flying across the top",
}


class ReviewIssue(BaseModel):
    """One thing wrong on one frame."""

    model_config = ConfigDict(extra="forbid")

    t: float = Field(ge=0, description="Seconds into the video of the frame.")
    type: IssueType
    severity: Severity
    note: str = Field(min_length=1, max_length=200)


class Review(BaseModel):
    """Everything wrong on the frames; empty when nothing is."""

    model_config = ConfigDict(extra="forbid")

    issues: list[ReviewIssue] = Field(default_factory=list, max_length=MAX_ISSUES)

    @property
    def needs_a_person(self) -> bool:
        return any(issue.severity == "high" for issue in self.issues)


@dataclass(frozen=True, slots=True)
class Keyframe:
    """A moment to look at, and what should be on screen then."""

    at: float
    shows: str


def keyframes(
    components: Sequence[ComponentUse],
    *,
    length: float,
    line_starts: Sequence[float] = (),
) -> list[Keyframe]:
    """The moments to look at, in order. See the module's docstring."""
    wanted: list[Keyframe] = []
    for use in components:
        if use.name not in _SHOWS:
            continue
        if use.name == "end_card":
            at = max(use.start, use.start + use.length - END_BEFORE)
        else:
            at = _settled_in(use)
        wanted.append(Keyframe(at=round(at, 2), shows=_SHOWS[use.name]))
    picked = _apart(sorted(wanted, key=lambda k: k.at))
    if len(picked) > MOST:
        picked = _thinned(picked)
    return [
        Keyframe(at=_settled(k.at, line_starts, length=length), shows=k.shows)
        for k in _filled(picked, length=length)
    ]


def _settled_in(use: ComponentUse) -> float:
    """The middle of a component - or, when a moment inside it lands later
    (a label slamming down, the last row ticked), just after that, while
    it is still up: before it, a frame shows the component unfinished."""
    middle = use.start + use.length / 2
    beats = component(use.name).beats_at(use.start, use.beats)
    moments = [at for v in beats.values() for at in (v if isinstance(v, list) else [v])]
    if not moments:
        return float(middle)
    after = float(max(moments)) + AFTER_BEAT
    return float(max(middle, min(after, use.start + use.length - BEFORE_EXIT)))


def _settled(at: float, line_starts: Sequence[float], *, length: float) -> float:
    """``at``, or just after the subtitle line coming in around it."""
    for start in line_starts:
        if start - _LINE_EARLY <= at < start + LINE_SETTLES:
            return round(min(start + LINE_SETTLES, max(length - 0.05, 0.0)), 2)
    return at


def _apart(moments: list[Keyframe]) -> list[Keyframe]:
    out: list[Keyframe] = []
    for moment in moments:
        if out and moment.at - out[-1].at < MIN_APART:
            out[-1] = Keyframe(at=out[-1].at, shows=f"{out[-1].shows}; {moment.shows}")
        else:
            out.append(moment)
    return out


def _thinned(moments: list[Keyframe]) -> list[Keyframe]:
    """:data:`MOST` of ``moments``, evenly, the first and the last kept."""
    step = (len(moments) - 1) / (MOST - 1)
    return [moments[round(n * step)] for n in range(MOST)]


def _filled(moments: list[Keyframe], *, length: float) -> list[Keyframe]:
    """Plain footage between the moments, until there are :data:`FEWEST`."""
    out = list(moments)
    candidates = [length * n / (FEWEST + 1) for n in range(1, FEWEST + 1)]
    for at in sorted(candidates, key=lambda a: -_distance(a, out)):
        if len(out) >= FEWEST:
            break
        if _distance(at, out) >= MIN_APART:
            out.append(Keyframe(at=round(at, 2), shows="the footage with subtitles"))
    return sorted(out, key=lambda k: k.at)


def _distance(at: float, moments: Sequence[Keyframe]) -> float:
    return min((abs(at - m.at) for m in moments), default=float("inf"))
