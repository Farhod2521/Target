"""The first step's three questions, read off ``core.targeting.compat``."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.common.presets import goal_labels, offered_goals
from app.common.routes import reverse
from app.modules.ads.constants import (
    CAMPAIGN_TYPE,
    CAMPAIGN_TYPE_HINTS,
    CAMPAIGN_TYPE_LABELS,
    CLOSED_REASONS,
    GOAL_FAILED,
    GOAL_PENDING,
    GOAL_POLL_MS,
    GOAL_READING,
    GOAL_TEXT,
    GOAL_TEXT_MAX,
    GOAL_TEXT_MIN,
    MESSAGES_PHRASE_WITHOUT_INSTAGRAM,
    OUTCOME_HINTS,
    OUTCOME_LABELS,
    ROW_PHRASES,
)
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.selectors.campaign_type import effective_campaign_type, read_as
from app.modules.ads.selectors.goal_intent import (
    TEXT_MODE,
    abandoned,
    goal_example,
    goal_mode,
)
from app.modules.ads.selectors.goals import launch_category
from app.modules.ads.selectors.launch_page import launch_page
from app.modules.ads.selectors.pixel import launch_conversion_source
from app.modules.ads.selectors.quality import quality_offer
from core.targeting import (
    OUTCOMES,
    AccountFacts,
    Offer,
    Preset,
    closed_by,
    default_offer,
    listed_for,
    nearest_open,
    offer,
    outcome_default,
    outcome_of,
)
from core.targeting.quality import VOLUME_GOAL

FIX_ROUTES = {"pixel": "integrations:connections"}
FIX_EVENTS = {"instagram": "instagram-help-open"}
BY_AI = "ai"
BY_YOU = "you"
BY_DEFAULT = "default"


def account_facts(db: Session, *, launch: CampaignLaunch) -> AccountFacts:
    page = launch_page(db, launch=launch)
    return AccountFacts(
        has_pixel=launch_conversion_source(db, launch=launch) is not None,
        quality_ready=quality_offer(
            db, launch=launch, optimization_goal=VOLUME_GOAL
        ).is_offered,
        has_instagram=page is not None and page.can_open_profile,
    )


@dataclass(frozen=True, slots=True)
class RowOption:
    key: str
    outcome: str
    choice: str
    goal: str
    label: Any
    hint: Any
    outcome_label: Any
    meta_group: str
    meta_goal: str
    meta_choice: str
    reason: Any
    fix_url: str
    fix_event: str = ""
    instead: str = ""
    instead_label: Any = ""

    @property
    def is_open(self) -> bool:
        return not self.reason

    @property
    def meta(self) -> str:
        return f"{self.meta_group} · {self.meta_goal}"


@dataclass(frozen=True, slots=True)
class RowGroup:
    label: str
    rows: tuple[RowOption, ...]


@dataclass(frozen=True, slots=True)
class OutcomeOption:
    key: str
    label: Any
    hint: Any
    live: bool
    choices: tuple[RowOption, ...]
    groups: tuple[RowGroup, ...]
    recommended: str = ""
    closed: RowOption | None = None


def _row_option(row: Offer, facts: AccountFacts) -> RowOption:
    closed = closed_by(row, facts)
    reason = CLOSED_REASONS.get(closed[0], "") if closed else ""
    fix = FIX_ROUTES.get(closed[0], "") if closed else ""
    fix_event = FIX_EVENTS.get(closed[0], "") if closed else ""
    group = " · ".join(
        part
        for part in (row.kind.provider_label, row.provider_destination_label)
        if part
    )
    instead = nearest_open(row, facts) if closed else None
    return RowOption(
        key=row.key,
        outcome=row.outcome,
        choice=row.choice,
        goal=row.goal,
        label=row_label(row),
        outcome_label=OUTCOME_LABELS.get(row.outcome, row.outcome),
        hint=CAMPAIGN_TYPE_HINTS.get(row.key, ""),
        meta_group=group,
        meta_goal=row.kind.provider_goal_label,
        meta_choice=f"{group} · {row.kind.provider_goal_name}",
        reason=reason,
        fix_url=reverse(fix) if fix else "",
        fix_event=fix_event,
        instead=instead.key if instead is not None else "",
        instead_label=row_label(instead) if instead is not None else "",
    )


def row_label(row: Offer) -> Any:
    return CAMPAIGN_TYPE_LABELS.get(row.key, row.key)


def outcome_options(
    db: Session, *, launch: CampaignLaunch, facts: AccountFacts
) -> tuple[OutcomeOption, ...]:
    offered = _offered(db, launch)
    keep = effective_campaign_type(launch=launch)
    found: list[OutcomeOption] = []
    for spec in OUTCOMES:
        rows = tuple(
            _row_option(row, facts)
            for row in listed_for(provider=launch.provider, outcome=spec.key, keep=keep)
            if row.goal in offered
        )
        groups: dict[str, list[RowOption]] = {}
        for item in rows:
            groups.setdefault(item.meta_group, []).append(item)
        found.append(
            OutcomeOption(
                key=spec.key,
                label=OUTCOME_LABELS.get(spec.key, spec.key),
                hint=OUTCOME_HINTS.get(spec.key, ""),
                live=spec.live and bool(rows),
                choices=tuple(item for item in rows if item.choice == item.key),
                groups=tuple(
                    RowGroup(label=label, rows=tuple(items))
                    for label, items in groups.items()
                ),
                recommended=_default_key(launch, spec.key),
                closed=rows[0] if rows and not any(r.is_open for r in rows) else None,
            )
        )
    return tuple(found)


def picker_table(
    db: Session, *, launch: CampaignLaunch, outcomes: tuple[OutcomeOption, ...]
) -> dict[str, Any]:
    """What the page's script switches between, as plain data."""
    presets = _offered(db, launch)
    rows: dict[str, dict[str, Any]] = {}
    for option in outcomes:
        for group in option.groups:
            for item in group.rows:
                rows[item.key] = {
                    "outcome": item.outcome,
                    "choice": item.choice,
                    "goal": item.goal,
                    "open": item.is_open,
                    "meta": item.meta,
                    "label": str(item.label),
                    "outcome_label": str(item.outcome_label),
                    "reason": str(item.reason),
                    "fix_url": item.fix_url,
                    "fix_event": item.fix_event,
                    "instead": item.instead,
                    "instead_label": str(item.instead_label),
                }
    return {
        "outcomes": {
            option.key: {
                "live": option.live,
                "default": _default_key(launch, option.key),
                "choices": [item.key for item in option.choices],
            }
            for option in outcomes
        },
        "rows": rows,
        "goals": {goal: _asks(preset) for goal, preset in sorted(presets.items())},
    }


def _default_key(launch: CampaignLaunch, outcome: str) -> str:
    found = outcome_default(provider=launch.provider, outcome=outcome)
    return found.key if found is not None else ""


def _asks(preset: Preset) -> dict[str, bool]:
    return {
        "link": preset.needs_link,
        "phone": preset.needs_phone,
        "chat": preset.opens_chat,
        "form": preset.needs_lead_form,
        "pixel": preset.needs_conversion_source,
        "profile": preset.opens_profile,
    }


def _offered(db: Session, launch: CampaignLaunch) -> dict[str, Preset]:
    category = launch_category(db, launch=launch)
    return {
        preset.goal: preset
        for preset in offered_goals(provider=launch.provider, category=category)
    }


# -- the reading -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ShownRowReading:
    state: str = ""
    row: RowOption | None = None
    alternatives: tuple[RowOption, ...] = ()
    instead: RowOption | None = None
    quote: str = ""
    by: str = ""


def shown_row_reading(
    *,
    launch: CampaignLaunch,
    rows: dict[str, RowOption],
    facts: AccountFacts,
    now: datetime,
    gave_up: bool = False,
) -> ShownRowReading:
    raw = launch.answers.get(GOAL_READING)
    if (
        not isinstance(raw, dict)
        or not str(launch.answers.get(GOAL_TEXT) or "").strip()
    ):
        return ShownRowReading()
    state = str(raw.get("state") or "")
    if state == GOAL_PENDING and (gave_up or abandoned(raw, now=now)):
        return ShownRowReading(state=GOAL_FAILED)
    if state in {GOAL_PENDING, GOAL_FAILED, "unclear"}:
        return ShownRowReading(state=state)
    item = rows.get(reading_row(launch, raw))
    if item is None:
        return ShownRowReading()
    alternatives = tuple(
        rows[key] for key in raw.get("alternatives") or [] if key in rows
    )
    found = offer(provider=launch.provider, key=item.key)
    instead = (
        nearest_open(found, facts, preferred=tuple(a.key for a in alternatives))
        if found is not None and not item.is_open
        else None
    )
    return ShownRowReading(
        state=state,
        row=item,
        alternatives=alternatives,
        instead=rows.get(instead.key) if instead is not None else None,
        quote=str(raw.get("quote") or ""),
        by=str(raw.get("by") or ""),
    )


def row_phrases(
    *, rows: dict[str, RowOption], has_instagram: bool
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (
            key,
            str(
                MESSAGES_PHRASE_WITHOUT_INSTAGRAM
                if rows[key].outcome == "messages" and not has_instagram
                else phrase
            ),
        )
        for key, phrase in ROW_PHRASES
        if key in rows
    )


def words_for_row(*, launch: CampaignLaunch, row: Offer, words: str, mode: str) -> str:
    raw = launch.answers.get(GOAL_READING)
    if mode != TEXT_MODE or not isinstance(raw, dict):
        return ""
    if raw.get("state") not in {"found", "sale"}:
        return ""
    settled = offer(provider=launch.provider, key=reading_row(launch, raw))
    if settled is None or settled.outcome != row.outcome:
        return ""
    return words.strip()


def reading_row(launch: CampaignLaunch, raw: dict[str, Any]) -> str:
    if raw.get("row"):
        return str(raw["row"])
    goals = raw.get("goals") or []
    found = (
        default_offer(provider=launch.provider, goal=str(goals[0])) if goals else None
    )
    return found.key if found is not None else ""


# -- the state -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PickerState:
    outcome: str = ""
    choice: str = ""
    row: str = ""
    by_outcome: str = ""
    by_choice: str = ""
    by_row: str = ""
    legacy: Any = ""


def row_picker(
    db: Session,
    *,
    launch: CampaignLaunch,
    now: datetime,
    mode: str = "",
    posted: dict[str, str] | None = None,
    gave_up: bool = False,
) -> dict[str, Any]:
    """Everything the three questions draw, for the step and its fragment."""
    facts = account_facts(db, launch=launch)
    outcomes = outcome_options(db, launch=launch, facts=facts)
    rows = _rows(outcomes)
    page = launch_page(db, launch=launch)
    table = picker_table(db, launch=launch, outcomes=outcomes)
    reading = shown_row_reading(
        launch=launch, rows=rows, facts=facts, now=now, gave_up=gave_up
    )
    state = picker_state(launch=launch, outcomes=outcomes, posted=posted)
    if _unanswered(state, posted) and reading.state == "found" and reading.row:
        by = _by(reading.by)
        state = _chosen(reading.row, by, by)
    return {
        "outcomes": outcomes,
        "picker_table": table,
        "picker": state,
        "picker_now": opening_view(table=table, state=state),
        "picker_row": rows.get(state.row),
        "reading": reading,
        "card_row": rows.get(state.row) or reading.row,
        "card_by": state.by_row or _by(reading.by),
        "goal_phrases": row_phrases(
            rows=rows, has_instagram=page is not None and page.has_instagram
        ),
        "goal_example": goal_example(category=launch_category(db, launch=launch)),
        "goal_mode": goal_mode(launch=launch, posted=mode),
        "goal_text_min": GOAL_TEXT_MIN,
        "goal_text_max": GOAL_TEXT_MAX,
        "goal_poll_ms": GOAL_POLL_MS,
    }


def opening_view(*, table: dict[str, Any], state: PickerState) -> dict[str, Any]:
    row = table["rows"].get(state.row)
    if row is None:
        return {"asks": {}, "ready": False, "closed": False, "meta": ""}
    return {
        "asks": table["goals"].get(row["goal"], {}),
        "ready": row["open"],
        "closed": not row["open"],
        "meta": row["meta"],
    }


def picker_state(
    *,
    launch: CampaignLaunch,
    outcomes: tuple[OutcomeOption, ...],
    posted: dict[str, str] | None = None,
) -> PickerState:
    rows = _rows(outcomes)
    if posted is not None:
        key = str(posted.get(CAMPAIGN_TYPE) or "")
        if key in rows:
            return _chosen(rows[key], BY_YOU, BY_YOU)
        outcome = str(posted.get("outcome") or "")
        return PickerState(outcome=outcome, by_outcome=BY_YOU if outcome else "")
    goal = str(launch.answers.get("goal") or "")
    if not goal:
        return PickerState()
    spec = outcome_of(goal)
    if spec is None or not spec.live:
        return PickerState(legacy=goal_labels(provider=launch.provider).get(goal, goal))
    stored = str(launch.answers.get(CAMPAIGN_TYPE) or "")
    key = stored or effective_campaign_type(launch=launch)
    item = rows.get(key)
    if item is None or item.goal != goal:
        return PickerState(
            outcome=spec.key,
            by_outcome=BY_YOU,
            legacy=CAMPAIGN_TYPE_LABELS.get(key, key) if key else "",
        )
    if read_as(launch) == key:
        return _chosen(item, BY_AI, BY_AI)
    return _chosen(item, BY_YOU, BY_YOU if stored else BY_DEFAULT)


def _unanswered(state: PickerState, posted: dict[str, str] | None) -> bool:
    return posted is None and not (state.row or state.outcome or state.legacy)


def _by(reading_by: str) -> str:
    return BY_AI if reading_by == BY_AI else BY_YOU


def _chosen(item: RowOption, by_outcome: str, by_rest: str) -> PickerState:
    return PickerState(
        outcome=item.outcome,
        choice=item.choice,
        row=item.key,
        by_outcome=by_outcome,
        by_choice=by_rest if item.choice else "",
        by_row=by_rest,
    )


def _rows(outcomes: tuple[OutcomeOption, ...]) -> dict[str, RowOption]:
    return {
        item.key: item
        for option in outcomes
        for group in option.groups
        for item in group.rows
    }
