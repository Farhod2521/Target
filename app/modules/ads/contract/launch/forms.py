"""The plan's lead form layer and the AI's small answers, as the screens draw them.

As the browser read them in ``live/launch-map.ts`` - except the chat
questions, which it looked for at the answer's top and never found: they
are read here from the reading they come in.
"""

from typing import Any, Final

from app.modules.ads.contract.launch.edit import FIELD_OF, KIND_OF
from app.modules.ads.contract.launch.review import text
from app.modules.ads.inputs.lead_form import LeadFormPickIn

ENDING_KINDS: Final = frozenset({"none", "website", "telegram", "call"})
POLL: Final[dict[str, str]] = {
    "": "idle",
    "idle": "idle",
    "none": "idle",
    "pending": "pending",
    "running": "pending",
    "asked": "pending",
    "writing": "pending",
    "queued": "pending",
    "done": "done",
    "ready": "done",
    "written": "done",
    "failed": "failed",
    "error": "failed",
    "exhausted": "failed",
}


def _question(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return text(item.get("label") or item.get("key"))
    return ""


def chat_reading(answer: dict[str, Any]) -> dict[str, Any]:
    """The chat questions the AI writes: idle, pending, done or failed."""
    reading = answer.get("reading") or {}
    state = POLL.get(text(reading.get("state")).lower(), "failed")
    if answer.get("error") or (state == "pending" and answer.get("gave_up")):
        state = "failed"
    return {
        "state": state,
        "questions": [
            question
            for question in map(_question, reading.get("questions") or [])
            if question
        ],
    }


def form_variant(answer: dict[str, Any]) -> dict[str, Any]:
    """One depth's questions: ready once written, failed when the backend refused to ask."""
    block = answer["block"]
    questions = [
        {
            "id": text(row.get("kind") or f"d{index}"),
            "text": text(row.get("label")),
            "options": [text(option) for option in row["options"]]
            if isinstance(row.get("options"), list)
            else [],
        }
        for index, row in enumerate(block.get("questions") or [], start=1)
    ]
    if block.get("state") == "pending" and not answer.get("gave_up"):
        state = "pending"
    elif block.get("state") in ("ready", "current") and not (
        answer.get("refusal") and not questions
    ):
        state = "ready"
    else:
        state = "failed"
    return {"state": state, "questions": questions}


def _ending(found: dict[str, Any] | None) -> dict[str, str]:
    found = found or {}

    def field(key: str) -> str:
        return "" if found.get(key) is None else str(found[key])

    kind = field("kind")
    return {
        "kind": kind if kind in ENDING_KINDS else "none",
        "website": field("website"),
        "telegram": field("telegram"),
        "phone": field("phone"),
        "button": field("button"),
        "title": field("title"),
        "body": field("body"),
    }


def panel(picker: dict[str, Any]) -> dict[str, Any]:
    """The «Lid formasi» layer: the page's forms and the new-form builder."""
    return {
        "forms": [
            {
                "id": row["external_id"],
                "name": row["name"],
                "questions": row.get("questions") or [],
                # The form's own typed questions; the contact ones Meta refuses are not told apart.
                "typed_contacts": [],
                "ending": {
                    "words": text(row["ending"].get("words")),
                    "target": text(row["ending"].get("target")),
                }
                if row.get("ending")
                else None,
                "leads": row.get("leads_count"),
                "created": row.get("created_time"),
            }
            for row in picker.get("lead_forms") or []
        ],
        "chosen": picker.get("chosen_form") or "",
        "name": picker.get("form_name") or "",
        "standard": [
            {"kind": FIELD_OF[row["kind"]], "checked": bool(row.get("checked"))}
            for row in picker.get("standard_questions") or []
            if row.get("kind") in FIELD_OF
        ],
        "typed": [
            {"label": row.get("label") or "", "options": row.get("options") or []}
            for row in picker.get("typed_questions") or []
        ],
        "ending": _ending(picker.get("ending")),
        "synced_at": picker.get("forms_synced_at"),
        "max_questions": picker.get("max_questions") or 0,
        "max_options": picker.get("max_options") or 0,
    }


def pick_in(save: dict[str, Any], goal: str) -> LeadFormPickIn:
    """The layer's save. ``goal`` is the goal tapped on the plan, not saved yet."""
    return LeadFormPickIn.model_validate(
        {
            "goal": goal,
            "lead_form": save["form_id"],
            "name": save["name"].strip(),
            "kinds": [KIND_OF[kind] for kind in save["kinds"]],
            "typed": [
                {"label": row["label"].strip(), "options": row["options"]}
                for row in save["typed"]
                if row["label"].strip()
            ],
            "ending": dict(save["ending"]),
        }
    )


__all__ = ["chat_reading", "form_variant", "panel", "pick_in"]
