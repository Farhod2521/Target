"""Live cases for the one chat's assistant.

Each case is a question, the Context the model is shown, and what each tool
answers when it is called (canned, so the case does not need a database).
A case passes when the answer passes the chat's own marks
(``core/evals/grade.py``) and the model called the tools it had to and none
it must not. ``python -m tools.assistant_eval`` runs them against the real
model; the tests here run them against a scripted one.
"""

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.evals.cases import Case
from core.evals.grade import Mark, grade

CASES = Path(__file__).resolve().parent / "cases.json"
NOT_CANNED = "nothing found."


@dataclass(frozen=True, slots=True)
class AssistantCase:
    id: str
    question: str
    context: str
    tools: dict[str, str]
    must_call: tuple[str, ...] = ()
    must_not_call: tuple[str, ...] = ()
    required: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    language: str = "uz"
    note: str = ""

    def as_case(self) -> Case:
        """The shape the chat's grader reads. Figures in the canned tool
        results count as shown to the model."""
        shown = "\n".join([self.context, *self.tools.values()])
        return Case(
            id=self.id,
            surface="chat",
            prompt="assistant",
            question=self.question,
            context=shown,
            forbidden=self.forbidden,
            required=self.required,
            language=self.language,
            note=self.note,
        )


@dataclass(slots=True)
class Run:
    """What one case's answer did."""

    answer: str
    called: list[str] = field(default_factory=list)
    cost_micros: int = 0


def load(path: Path | None = None) -> tuple[AssistantCase, ...]:
    rows: Any = json.loads((path or CASES).read_text(encoding="utf-8"))
    return tuple(
        AssistantCase(
            id=str(row["id"]),
            question=str(row["question"]),
            context=str(row.get("context", "")),
            tools={str(k): str(v) for k, v in (row.get("tools") or {}).items()},
            must_call=tuple(row.get("must_call", ())),
            must_not_call=tuple(row.get("must_not_call", ())),
            required=tuple(row.get("required", ())),
            forbidden=tuple(row.get("forbidden", ())),
            language=str(row.get("language", "uz")),
            note=str(row.get("note", "")),
        )
        for row in rows
    )


def canned(
    case: AssistantCase, *, reading: Callable[[str, str], str]
) -> Callable[[str], str]:
    """What a tool answers in this case. A ticket is always prepared."""

    def answer(name: str) -> str:
        if name == "create_ticket":
            return (
                "Prepared. The person now sees a «Mutaxassisga yuborish» button "
                "under your answer; nothing has been sent and nothing will be "
                "until they press it. Say in one or two sentences what you found "
                "and that they can send it to a specialist with the button. "
                "Never say it was sent."
            )
        return reading(name, case.tools.get(name, NOT_CANNED))

    return answer


def marks(case: AssistantCase, run: Run) -> tuple[Mark, ...]:
    """The chat's marks, and the two about tools."""
    called = set(run.called)
    missing = [name for name in case.must_call if name not in called]
    wrong = [name for name in case.must_not_call if name in called]
    return (
        *grade(case=case.as_case(), answer=run.answer),
        Mark("called_what_it_must", not missing, ", ".join(missing)),
        Mark("called_nothing_it_must_not", not wrong, ", ".join(wrong)),
    )


def summary(
    results: Iterable[tuple[AssistantCase, tuple[Mark, ...]]],
) -> tuple[int, int, list[str]]:
    """``(passed, total, lines)`` for the console."""
    lines: list[str] = []
    passed = total = 0
    for case, found in results:
        total += 1
        ok = all(mark.passed for mark in found)
        passed += ok
        lines.append(f"{'PASS' if ok else 'FAIL'}  {case.id}")
        lines += [
            f"      {mark.check}: {mark.detail}" for mark in found if not mark.passed
        ]
    return passed, total, lines


__all__ = ["CASES", "AssistantCase", "Run", "canned", "load", "marks", "summary"]
