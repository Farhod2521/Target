"""One test case: what the model is shown, and what its answer may not do."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CASES_DIR = Path(__file__).resolve().parent / "cases"


@dataclass(frozen=True, slots=True)
class Case:
    """One question, the account it is asked about, and what a good answer is."""

    id: str
    surface: str
    prompt: str
    question: str
    context: str = ""
    forbidden: tuple[str, ...] = ()
    required: tuple[str, ...] = ()
    language: str = "uz"
    note: str = ""
    variables: dict[str, str] = field(default_factory=dict)


def load_cases(*, surface: str = "", directory: Path | None = None) -> tuple[Case, ...]:
    """Every case on disk, or one surface's, in the order the files list them."""
    root = directory or CASES_DIR
    files = sorted(root.glob(f"{surface or '*'}.json"))
    found: list[Case] = []
    for path in files:
        rows: Any = json.loads(path.read_text(encoding="utf-8"))
        for row in rows:
            found.append(_case(row, surface=path.stem))
    return tuple(found)


def _case(row: dict[str, Any], *, surface: str) -> Case:
    return Case(
        id=str(row["id"]),
        surface=surface,
        prompt=str(row["prompt"]),
        question=str(row.get("question", "")),
        context=str(row.get("context", "")),
        forbidden=tuple(str(word) for word in row.get("forbidden", ())),
        required=tuple(str(word) for word in row.get("required", ())),
        language=str(row.get("language", "uz")),
        note=str(row.get("note", "")),
        variables={str(k): str(v) for k, v in (row.get("variables") or {}).items()},
    )


__all__ = ["CASES_DIR", "Case", "load_cases"]
