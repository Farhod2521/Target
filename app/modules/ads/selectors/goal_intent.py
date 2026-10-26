"""What the first screen shows about the goal said in words."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.common.presets import goal_label
from app.modules.ads.constants import (
    GOAL_EXAMPLE_FALLBACK,
    GOAL_EXAMPLES,
    GOAL_FAILED,
    GOAL_HINTS,
    GOAL_PENDING,
    GOAL_PENDING_SECONDS,
    GOAL_PHRASES,
    GOAL_POLL_MS,
    GOAL_READING,
    GOAL_TEXT,
    GOAL_TEXT_MAX,
    GOAL_TEXT_MIN,
    MESSAGES_PHRASE_WITHOUT_INSTAGRAM,
)
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.selectors.goals import launch_category, legacy_plan_goals
from app.modules.ads.selectors.launch_page import launch_page
from core.targeting import Preset

TEXT_MODE = "text"
LIST_MODE = "list"
MODES = frozenset({TEXT_MODE, LIST_MODE})
WITHOUT_GOALS = frozenset({GOAL_PENDING, GOAL_FAILED, "unclear"})


@dataclass(frozen=True, slots=True)
class GoalOption:
    goal: str
    label: str
    hint: str


@dataclass(frozen=True, slots=True)
class GoalPhrase:
    goal: str
    phrase: str


@dataclass(frozen=True, slots=True)
class ShownReading:
    state: str = ""
    options: tuple[GoalOption, ...] = ()
    quote: str = ""
    by: str = ""

    @property
    def goal(self) -> str:
        if self.state == "found" and self.options:
            return self.options[0].goal
        return ""


def goal_options(*, offered: tuple[Preset, ...]) -> tuple[GoalOption, ...]:
    return tuple(
        GoalOption(
            goal=preset.goal,
            label=goal_label(preset=preset),
            hint=str(GOAL_HINTS.get(preset.goal, "")),
        )
        for preset in offered
    )


def goal_phrases(
    *, offered: tuple[Preset, ...], has_instagram: bool
) -> tuple[GoalPhrase, ...]:
    goals = {preset.goal for preset in offered}
    return tuple(
        GoalPhrase(
            goal=goal,
            phrase=str(
                MESSAGES_PHRASE_WITHOUT_INSTAGRAM
                if goal == "messages" and not has_instagram
                else phrase
            ),
        )
        for goal, phrase in GOAL_PHRASES
        if goal in goals
    )


def goal_example(*, category: str) -> str:
    return str(GOAL_EXAMPLES.get(category, GOAL_EXAMPLE_FALLBACK))


def goal_mode(*, launch: CampaignLaunch, posted: str = "") -> str:
    if posted in MODES:
        return posted
    if launch.answers.get("goal") and not launch.answers.get(GOAL_TEXT):
        return LIST_MODE
    return TEXT_MODE


def shown_reading(
    *,
    launch: CampaignLaunch,
    offered: tuple[Preset, ...],
    now: datetime,
    gave_up: bool = False,
) -> ShownReading:
    raw = launch.answers.get(GOAL_READING)
    if (
        not isinstance(raw, dict)
        or not str(launch.answers.get(GOAL_TEXT) or "").strip()
    ):
        return ShownReading()
    state = str(raw.get("state") or "")
    if state == GOAL_PENDING and (gave_up or abandoned(raw, now=now)):
        return ShownReading(state=GOAL_FAILED)
    if state in WITHOUT_GOALS:
        return ShownReading(state=state)
    named = {option.goal: option for option in goal_options(offered=offered)}
    options = tuple(named[goal] for goal in raw.get("goals") or [] if goal in named)
    if not options:
        return ShownReading()
    return ShownReading(
        state=state,
        options=options,
        quote=str(raw.get("quote") or ""),
        by=str(raw.get("by") or ""),
    )


def settled_goal(*, launch: CampaignLaunch) -> str:
    raw = launch.answers.get(GOAL_READING)
    if not isinstance(raw, dict) or raw.get("state") != "found":
        return ""
    goals = raw.get("goals") or []
    return str(goals[0]) if goals else ""


def words_for_goal(*, launch: CampaignLaunch, goal: str, words: str, mode: str) -> str:
    if mode == TEXT_MODE and goal and settled_goal(launch=launch) == goal:
        return words.strip()
    return ""


def abandoned(raw: dict[str, Any], *, now: datetime) -> bool:
    """Whether a pending reading has outlived any worker that could answer it."""
    try:
        asked = datetime.fromisoformat(str(raw.get("asked_at") or ""))
    except ValueError:
        return True
    return now - asked > timedelta(seconds=GOAL_PENDING_SECONDS)


def goal_picker(
    db: Session,
    *,
    launch: CampaignLaunch,
    now: datetime,
    mode: str = "",
    gave_up: bool = False,
) -> dict[str, Any]:
    """Everything the first question draws, for the step and for its fragment."""
    category = launch_category(db, launch=launch)
    offered = legacy_plan_goals(provider=launch.provider, category=category)
    page = launch_page(db, launch=launch)
    return {
        "goal_options": goal_options(offered=offered),
        "goal_phrases": goal_phrases(
            offered=offered, has_instagram=page is not None and page.has_instagram
        ),
        "goal_example": goal_example(category=category),
        "goal_mode": goal_mode(launch=launch, posted=mode),
        "reading": shown_reading(
            launch=launch, offered=offered, now=now, gave_up=gave_up
        ),
        "goal_text_min": GOAL_TEXT_MIN,
        "goal_text_max": GOAL_TEXT_MAX,
        "goal_poll_ms": GOAL_POLL_MS,
    }
