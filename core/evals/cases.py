"""One test case: what the model is shown, and what its answer may not do.

**The context is the case.** Every surface here hands the model a digest of
one account - what it spent, what came back, what the campaigns are called -
and the answer is judged against exactly that text, the way the product
judges it: the figures the context supplied are the figures that may be
quoted. So a case carries the digest verbatim rather than a list of allowed
numbers, and the allow-set is derived from it by the same function
production uses. A hand-written list would be a second opinion about what
the context said, and the first disagreement would be scored as a fault of
the model.

The accounts are invented and so are the numbers. Nothing here is a real
advertiser, and the file is read by a command somebody runs by hand.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CASES_DIR = Path(__file__).resolve().parent / "cases"


@dataclass(frozen=True, slots=True)
class Case:
    """One question, the account it is asked about, and what a good answer is.

    ``forbidden`` and ``required`` are the rules that are specific to this
    question - "do not write advert copy", "say something about a picture".
    The rules that hold for every answer of a surface are not here; they
    are in :mod:`core.evals.grade`, so a new case cannot forget them.
    """

    id: str
    surface: str
    prompt: str
    question: str
    # What the model is shown about the account, verbatim.
    context: str = ""
    # Words no good answer contains, lower-cased and matched loosely.
    forbidden: tuple[str, ...] = ()
    # At least one of these has to appear, where a case names any.
    required: tuple[str, ...] = ()
    # What the answer should be written in. Only the script is checked -
    # see :func:`core.evals.grade.grade` - because anything finer is a
    # second language model.
    language: str = "uz"
    # Free text for whoever reads the results table. Never graded.
    note: str = ""
    variables: dict[str, str] = field(default_factory=dict)


def load_cases(*, surface: str = "", directory: Path | None = None) -> tuple[Case, ...]:
    """Every case on disk, or one surface's, in the order the files list them.

    A file per surface, named after it. Unknown keys are a mistake worth
    failing on rather than ignoring: a rule spelled ``forbid`` instead of
    ``forbidden`` would silently grade nothing.
    """
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
