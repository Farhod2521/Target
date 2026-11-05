"""Every metric's formula is in ``core.metrics.formulas`` and nowhere else.

A cost per something, a per-thousand price or a rate per impression written
again in a selector is a second copy that will disagree with the first the
day one of them is adjusted. This reads the source and names the copy.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HOME = {
    ROOT / "core" / "metrics" / "arithmetic.py",
    ROOT / "core" / "metrics" / "formulas.py",
}
COPIES = re.compile(
    r"\bcost_per\("
    r"|\*\s*1_?000\s*//?"
    r"|\*\s*10_?000\s*/"
    r"|/\s*[\w.]*\b(impressions|reach|link_clicks|clicks|results|leads)\b(?![\"'/])"
)


def test_no_metric_is_computed_outside_its_one_place() -> None:
    found = [
        f"{path.relative_to(ROOT)}:{number}: {line.strip()}"
        for folder in ("app", "core")
        for path in sorted((ROOT / folder).rglob("*.py"))
        if path not in HOME
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if COPIES.search(line.split("#", 1)[0])
        and not line.lstrip().startswith(('"', "'", "@"))
        and "description=" not in line
    ]

    assert found == []
