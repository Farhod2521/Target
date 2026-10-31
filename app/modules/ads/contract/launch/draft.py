"""The wizard's one draft, from the launch's state, its plan and, past the plan, its review.

What the browser assembled in ``live/launch-map.ts`` from three answers and
its own tab; the taps the screen has not sent yet show over what is saved.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from app.common.contract import Money
from app.modules.ads.contract.launch import review as review_words
from app.modules.ads.contract.launch.failures import failure
from app.modules.ads.contract.launch.words import (
    STEPS,
    goal_key,
    goal_keys,
    goal_of,
    kind_of,
    method_of,
    minor_money,
    prep_error_of,
    shown,
    status_of,
    whole_money,
    whole_of,
)
from app.modules.ads.inputs.media import MediaTextIn
from app.modules.ads.inputs.plan import PlanIn

GOAL_READINGS = frozenset({"found", "two", "sale", "unclear"})


def _option_key(option: Any) -> str:
    if isinstance(option, str):
        return option
    if isinstance(option, dict):
        return str(option.get("goal") or option.get("key") or "")
    return ""


def flat_reading(envelope: dict[str, Any]) -> dict[str, Any]:
    """The goal reading as the rest reads it: flat, goals as keys."""
    if "reading" not in envelope:
        return envelope
    found = envelope.get("reading") or {}
    options = [
        key
        for key in map(
            _option_key, found.get("options") or found.get("alternatives") or []
        )
        if key
    ]
    settled = str(found.get("state") or "").lower() == "found"
    goal = found.get("goal") or (
        (_option_key(found.get("row")) or (options[0] if options else ""))
        if settled
        else ""
    )
    return {
        "state": found.get("state") or "",
        "by": found.get("by"),
        "quote": found.get("quote"),
        "goal": goal,
        "options": options,
        "tries": envelope.get("tries"),
        "keep_polling": envelope.get("keep_polling"),
    }


def flat_plan(raw: dict[str, Any]) -> dict[str, Any]:
    """``GET /plan`` nests the answers under ``initial``, the floor under
    ``frame`` and the form under ``form_choice``; read here flat."""
    initial = raw.get("initial") or {}
    frame = raw.get("frame") or {}
    form = raw.get("form_choice")
    picker = raw.get("picker") or {}
    places = frame.get("places", 2)
    floor = frame.get("min_daily_minor")
    phrases = picker.get("goal_phrases")
    reading = picker.get("reading")
    return {
        **initial,
        **raw,
        "goals": [
            {"key": str(row.get("goal") or ""), "label": row.get("label")}
            if isinstance(row, dict) and "goal" in row
            else row
            for row in raw.get("goals") or []
        ],
        "currency": raw.get("currency") or frame.get("currency") or "",
        "min_budget": raw.get("min_budget")
        if raw.get("min_budget") is not None
        else (Decimal(floor) / 10**places if floor is not None else None),
        "region": raw.get("region") or frame.get("region") or "",
        "goal_mode": raw.get("goal_mode") or picker.get("goal_mode"),
        "phrases": raw.get("phrases")
        or [
            row
            for row in (phrases if isinstance(phrases, list) else [])
            if isinstance(row, dict) and "goal" in row and "phrase" in row
        ],
        "reading": raw.get("reading")
        or (flat_reading({"reading": reading}) if reading else None),
        "lead_form": raw.get("lead_form")
        or (
            {
                "by": "me" if form.get("by_owner") else "ai",
                "depth": form.get("depth"),
                "lead_form": form.get("external_id") or None,
                "name": form.get("name"),
                "questions": form.get("questions"),
                "ending": form["ending"]
                if form.get("ending") and form["ending"].get("words")
                else None,
                "missing": form.get("is_missing"),
            }
            if form
            else None
        ),
    }


def lead_form_choice(found: dict[str, Any] | None) -> dict[str, Any] | None:
    if not found:
        return None
    return {
        "by": "me" if found.get("by") in ("me", "owner", "user") else "ai",
        "depth": "deep" if found.get("depth") == "deep" else "short",
        "form_id": found.get("lead_form") or None,
        "name": found.get("name") or "",
        "questions": found.get("questions") or [],
        "ending": found.get("ending") or None,
        "missing": bool(found.get("missing")),
    }


def goal_reading(found: dict[str, Any] | None) -> dict[str, Any] | None:
    if not found or not found.get("state"):
        return None
    state = str(found["state"]).lower()
    if state not in GOAL_READINGS:
        state = "unclear" if state in ("pending", "reading") else "failed"
    return {
        "state": state,
        "by": found.get("by") if found.get("by") in ("phrase", "pick") else "ai",
        "goal": goal_of(found.get("goal")),
        "quote": found.get("quote") or "",
        "options": [goal for goal in map(goal_of, found.get("options") or []) if goal],
    }


def _distinct[T](items: list[T]) -> list[T]:
    return list(dict.fromkeys(items))


def draft(
    *,
    head: dict[str, Any],
    plan: dict[str, Any],
    review: dict[str, Any] | None,
    taps: dict[str, Any],
    extras: dict[str, Any],
    today: date,
) -> dict[str, Any]:
    """The draft as the screens hold it. ``extras`` is what only the launch
    knows: its campaign, its first-ever flag, its texts, its ticked tiles."""
    state = (review or {}).get("state")
    status = (
        review_words.review_status(state) if state else status_of(head.get("status"))
    )
    currency = (
        plan.get("currency")
        or ((review or {}).get("launch") or {}).get("currency")
        or taps.get("currency")
        or "USD"
    )
    mine = taps.get("plan") or {}
    tapped_budget = mine.get("daily_budget")
    daily_budget = (
        Money.model_validate(tapped_budget)
        if tapped_budget
        else whole_money(plan.get("daily_budget"), currency)
    )
    min_budget = whole_money(plan.get("min_budget"), currency)
    drawn = review if review and review.get("proposal") else None
    saved_goal = str(
        (drawn or {}).get("proposal", {}).get("goal") or plan.get("goal") or ""
    )
    line: dict[str, Any] = {"kind": kind_of(saved_goal)}
    if goal_of(saved_goal) == "lead":
        line["method"] = method_of(saved_goal) or "instant_form"
    shows = drawn is not None and status not in ("draft", "building", "prep_failed")
    proposal = (
        review_words.proposal(
            drawn,
            goal=line,
            to_money=lambda minor: minor_money(minor, currency),
            today=today,
        )
        if shows and drawn is not None
        else None
    )
    adverts = len(proposal["ads"]) if proposal else len(taps.get("media") or [])
    texts = extras.get("text") or {}
    page = plan.get("page") or {}
    pixel = plan.get("pixel") or {}

    def answer(key: str, saved: Any) -> Any:
        return mine.get(key, saved)

    return {
        "id": head.get("id") or extras["id"],
        "flow": "campaigns",
        "network_id": "meta",
        "status": status,
        "step": STEPS.get(str(head.get("resume") or head.get("step") or ""))
        or taps.get("step")
        or "plan",
        "goal_mode": answer(
            "goal_mode", "list" if plan.get("goal_mode") == "list" else "words"
        ),
        "goal_words": answer("goal_words", plan.get("goal_text") or ""),
        "goal": answer("goal", goal_of(plan.get("goal"))),
        "ai_goal": goal_of(plan.get("ai_goal")),
        "offered_goals": _distinct(
            [goal for goal in map(goal_of, goal_keys(plan)) if goal]
        ),
        "method": answer(
            "method", method_of(plan.get("goal")) or taps.get("method") or None
        ),
        "daily_budget": daily_budget,
        "min_budget": min_budget,
        "budget_presets": [
            whole_money(value, currency) for value in plan.get("budget_presets") or []
        ],
        "start": answer(
            "start", "tomorrow" if plan.get("start_day") == "tomorrow" else "today"
        ),
        "media_source": taps.get("media_source")
        or ("lib" if plan.get("has_instagram") is False else "ig"),
        "media": taps["media"] if "media" in taps else extras.get("asset_ids") or [],
        "text_mode": taps.get("text_mode")
        or ("each" if texts.get("mode") == "each" else "one"),
        "offer": taps["offer"] if "offer" in taps else texts.get("shared") or "",
        "offers": taps["offers"]
        if "offers" in taps
        else texts.get("asset_briefs") or {},
        "building": review_words.building(state, adverts)
        if status == "building" and state
        else None,
        "proposal": proposal,
        "creation": review_words.creation(state, adverts) if state else None,
        "failure": failure(
            state,
            ads_total=adverts,
            page=str(page.get("name") or ""),
            budget=shown(daily_budget),
            minimum=shown(min_budget),
        )
        if status == "failed" and state
        else None,
        "first_launch": bool(extras.get("first_launch")),
        "campaign_id": extras.get("campaign_id"),
        "review_eta": "hour",
        "google": None,
        "link_url": answer("link_url", plan.get("link_url") or ""),
        "phone": answer("phone", plan.get("phone_number") or ""),
        "chat_channel": answer(
            "chat_channel",
            "messenger" if plan.get("chat_channel") == "messenger" else "instagram",
        ),
        "welcome_text": answer("welcome_text", plan.get("welcome_text") or ""),
        "chat_questions": answer("chat_questions", plan.get("chat_questions") or []),
        "lead_form": lead_form_choice(plan.get("lead_form")),
        "areas": [],
        "page": {
            "has_instagram": bool(plan.get("has_instagram")),
            "pixel": pixel.get("name") or None,
            "region": plan.get("region") or "UZ",
        },
        "reading": goal_reading(plan.get("reading") or taps.get("reading")),
        "goal_phrases": [
            {"goal": goal, "phrase": row["phrase"]}
            for row in plan.get("phrases") or []
            if (goal := goal_of(row.get("goal")))
        ],
        "prep_error": prep_error_of((state or {}).get("error_code"))
        if status == "prep_failed"
        else None,
        "delivery": {"reason": (state or {}).get("delivery_note") or ""}
        if status == "created"
        else None,
        "created_ad_id": (state or {}).get("created_ad_id") or None,
        "regenerated": review_words.regenerated((drawn or {}).get("proposal")),
    }


def plan_in(plan: dict[str, Any], tapped: dict[str, Any], method: str | None) -> PlanIn:
    """PlanIn takes every answer together: the saved ones fill what the taps leave out."""
    goal = tapped["goal"] if "goal" in tapped else goal_of(plan.get("goal"))
    chosen = (
        tapped["method"]
        if "method" in tapped
        else (method_of(plan.get("goal")) or method)
    )
    budget = tapped.get("daily_budget")
    return PlanIn(
        goal=goal_key(goal, chosen, goal_keys(plan)),
        goal_mode=tapped.get("goal_mode") or plan.get("goal_mode") or "",
        goal_text=tapped.get("goal_words", plan.get("goal_text") or ""),
        daily_budget=whole_of(Money.model_validate(budget))
        if budget
        else plan.get("daily_budget"),
        link_url=tapped.get("link_url", plan.get("link_url") or ""),
        phone_number=tapped.get("phone", plan.get("phone_number") or ""),
        chat_channel=tapped.get("chat_channel", plan.get("chat_channel") or ""),
        welcome_text=tapped.get("welcome_text", plan.get("welcome_text") or ""),
        chat_questions=tapped.get("chat_questions", plan.get("chat_questions") or []),
        start_day=tapped.get("start", plan.get("start_day") or "today"),
    )


def text_in(taps: dict[str, Any]) -> MediaTextIn:
    """The offer typed on the pictures step: one for every advert, or one per tile."""
    return MediaTextIn(
        mode="each" if taps.get("text_mode") == "each" else "shared",
        shared=taps.get("offer") or "",
        briefs={},
        asset_briefs=taps.get("offers") or {},
    )


__all__ = [
    "draft",
    "flat_plan",
    "flat_reading",
    "goal_reading",
    "lead_form_choice",
    "plan_in",
    "text_in",
]
