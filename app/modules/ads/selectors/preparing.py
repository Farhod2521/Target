"""What the waiting cards say while a proposal is written or a campaign is created."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

from app.modules.ads.constants import (
    BUILD_NOTE_SECONDS,
    BUILD_NOTES,
    BUILD_PROGRESS,
    BUILD_STAGE_FALLBACK,
    BUILD_STAGE_SECONDS,
    BUILD_STAGES,
    BUILD_STAGES_DONE,
    CREATE_STAGES,
    LaunchStep,
)
from app.modules.ads.models import CampaignLaunch

NO_NOTE: Final = -1
SEPARATOR: Final = "."
StageState = Literal["done", "now", "next"]
BUILD_ORDER: tuple[str, ...] = (LaunchStep.ANSWERS, LaunchStep.ASKING, LaunchStep.LLM)
CREATE_MAKING: frozenset[str] = frozenset(
    {
        LaunchStep.IMAGE,
        LaunchStep.CAMPAIGN,
        LaunchStep.ADSET,
        LaunchStep.FORM,
        LaunchStep.CREATIVE,
        LaunchStep.AD,
        LaunchStep.VERIFY,
    }
)


@dataclass(frozen=True, slots=True)
class WaitStage:
    label: str
    state: StageState


def build_stages(*, step: str) -> tuple[WaitStage, ...]:
    current = BUILD_ORDER.index(step) if step in BUILD_ORDER else 1
    return _lines(
        now=[BUILD_STAGES[key] for key in BUILD_ORDER],
        done=[BUILD_STAGES_DONE[key] for key in BUILD_ORDER],
        current=current,
    )


def creating_stages(
    *, launch: CampaignLaunch, delivering: bool
) -> tuple[WaitStage, ...]:
    if delivering:
        current = 2
    elif str(launch.step) in CREATE_MAKING:
        current = 1
    else:
        current = 0
    return _lines(
        now=[pair[0] for pair in CREATE_STAGES],
        done=[pair[1] for pair in CREATE_STAGES],
        current=current,
    )


def _lines(
    *, now: Sequence[Any], done: Sequence[Any], current: int
) -> tuple[WaitStage, ...]:
    return tuple(
        WaitStage(
            label=str(done[index] if index < current else now[index]),
            state="done" if index < current else "now" if index == current else "next",
        )
        for index in range(len(now))
    )


@dataclass(frozen=True, slots=True)
class Preparing:
    headline: str
    stages: tuple[WaitStage, ...]
    note: str
    percent: int
    headline_changed: bool
    note_changed: bool
    token: str


def preparing(
    *, launch: CampaignLaunch, now: datetime, shown: str | None = None
) -> Preparing:
    """What to draw, given the row and the moment it is being drawn at."""
    step = str(launch.step)
    headline = str(BUILD_STAGES.get(step, BUILD_STAGE_FALLBACK))
    floor, ceiling = BUILD_PROGRESS.get(step, (launch.progress, launch.progress))
    if launch.started_at is None:
        return _card(
            step=step, headline=headline, index=NO_NOTE, percent=floor, shown=shown
        )
    elapsed = max(0.0, (now - launch.started_at).total_seconds())
    return _card(
        step=step,
        headline=headline,
        index=_note_index(step=step, elapsed=elapsed),
        percent=_percent(floor=floor, ceiling=ceiling, elapsed=elapsed),
        shown=shown,
    )


def _card(
    *, step: str, headline: str, index: int, percent: int, shown: str | None
) -> Preparing:
    was_step, _sep, was_index = (shown or "").partition(SEPARATOR)
    return Preparing(
        headline=headline,
        stages=build_stages(step=step),
        note="" if index == NO_NOTE else str(BUILD_NOTES[index]),
        percent=percent,
        headline_changed=bool(shown) and was_step != step,
        note_changed=bool(shown) and index != NO_NOTE and was_index != str(index),
        token=f"{step}{SEPARATOR}{index}",
    )


def _note_index(*, step: str, elapsed: float) -> int:
    if step != LaunchStep.ASKING:
        return NO_NOTE
    return int(elapsed // BUILD_NOTE_SECONDS) % len(BUILD_NOTES)


def _percent(*, floor: int, ceiling: int, elapsed: float) -> int:
    if ceiling <= floor:
        return floor
    share = min(1.0, elapsed / BUILD_STAGE_SECONDS)
    return floor + int((ceiling - floor) * share)
