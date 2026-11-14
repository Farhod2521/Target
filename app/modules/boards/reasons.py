"""The reasons on a Support ticket and what became of each. A client has one
ticket for ever, so its reasons pile up: each is open until «Hal qilindi» is
pressed, which solves every open one together, with who solved them and how.
The client's «Yo'q», or the ticket reopened by hand, opens that last round
again."""

from datetime import datetime
from typing import Any

from app.modules.accounts.models import User
from app.modules.boards.models import BoardCard

Reason = dict[str, Any]

_SOLVED = ("solved_at", "solved_by", "solved_note")


def is_open(item: Reason) -> bool:
    return not item.get("solved_at")


def open_reasons(card: BoardCard) -> list[Reason]:
    return [item for item in card.reasons or [] if is_open(item)]


def last_round(card: BoardCard) -> list[Reason]:
    """The reasons solved by the latest «Hal qilindi»."""
    stamps = [
        str(item["solved_at"]) for item in card.reasons or [] if not is_open(item)
    ]
    if not stamps:
        return []
    latest = max(stamps)
    return [item for item in card.reasons if item.get("solved_at") == latest]


def shown(card: BoardCard) -> list[Reason]:
    """What the ticket is about now: its open reasons, or, once it is
    solved, the ones the last «Hal qilindi» closed."""
    return open_reasons(card) or last_round(card)


def solve_open(card: BoardCard, *, by: User, note: str, now: datetime) -> int:
    """«Hal qilindi»: every open reason is solved together. How many."""
    stamp = now.isoformat()
    who = by.full_name or by.email
    out: list[Reason] = []
    solved = 0
    for item in card.reasons or []:
        if is_open(item):
            item = {**item, "solved_at": stamp, "solved_by": who, "solved_note": note}
            item.pop("denied_at", None)
            solved += 1
        out.append(item)
    # A new list: the column is JSON, and a change inside it is not seen.
    card.reasons = out
    return solved


def reopen_last(card: BoardCard, *, denied_at: datetime | None = None) -> int:
    """The last round is open again: the client said it is not solved
    (``denied_at``), or somebody reopened the ticket by hand. How many."""
    again = {id(item) for item in last_round(card)}
    out: list[Reason] = []
    for item in card.reasons or []:
        if id(item) in again:
            item = {key: value for key, value in item.items() if key not in _SOLVED}
            if denied_at is not None:
                item["denied_at"] = denied_at.isoformat()
        out.append(item)
    card.reasons = out
    return len(again)
