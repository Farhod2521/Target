"""A proposal's evidence is read on every center: a count must not break it."""

from app.common.money import THOUSANDS
from app.modules.agent.figures import readable


def test_a_whole_count_in_the_evidence_is_grouped() -> None:
    lines = readable({"impressions": 12000}, currency="USD")

    assert [value for _label, value in lines] == [f"12{THOUSANDS}000"]
