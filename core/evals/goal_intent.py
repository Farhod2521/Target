"""Marking the first step's reading: did the words land on the right row."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from core.agent import ChoiceReading
from core.targeting import offer

CASES_FILE = Path(__file__).resolve().parent / "goal_intent_cases.json"

Mark = Literal["exact", "accepted", "outcome", "wrong"]


@dataclass(frozen=True, slots=True)
class GoalCase:
    """One sentence and the row a person reading it would choose."""

    id: str
    text: str
    category: str
    expect: str
    lang: str = "uz"
    accept: tuple[str, ...] = ()
    closed: tuple[str, ...] = ()
    sale: bool = False
    note: str = ""


def load_goal_cases(path: Path | None = None) -> tuple[GoalCase, ...]:
    rows = json.loads((path or CASES_FILE).read_text(encoding="utf-8"))
    return tuple(
        GoalCase(
            id=str(row["id"]),
            text=str(row["text"]),
            category=str(row["category"]),
            expect=str(row["expect"]),
            lang=str(row.get("lang", "uz")),
            accept=tuple(row.get("accept", ())),
            closed=tuple(row.get("closed", ())),
            sale=bool(row.get("sale", False)),
            note=str(row.get("note", "")),
        )
        for row in rows
    )


def mark(case: GoalCase, reading: ChoiceReading, *, provider: str) -> Mark:
    """How close the reading came to what the case expects."""
    if not case.expect:
        if case.sale:
            return "exact" if reading.state == "sale" else _loose(case, reading)
        return "exact" if reading.state == "unclear" else "wrong"
    if reading.state != "found":
        return "wrong"
    if reading.row == case.expect:
        return "exact"
    return _loose(case, reading, provider=provider)


def _loose(case: GoalCase, reading: ChoiceReading, *, provider: str = "") -> Mark:
    if reading.row in case.accept:
        return "accepted"
    wanted = offer(provider=provider, key=case.expect) if case.expect else None
    got = offer(provider=provider, key=reading.row) if reading.row else None
    if wanted is not None and got is not None and wanted.outcome == got.outcome:
        return "outcome"
    return "wrong"


__all__ = ["CASES_FILE", "GoalCase", "Mark", "load_goal_cases", "mark"]
