"""The same audience is sized once: every save of a launch asked Meta again.

A launch asks for its reach after every section saved, every interest found
and every place resolved, and most of those leave the spec Meta sizes as it
was. The answer is kept under the spec's fingerprint for a few hours.
"""

from typing import Any

import pytest
from adskit.dto import ReachDTO
from adskit.refs import ExternalRef

from app.common.cache import cache
from app.modules.ads.services import interests

ACCOUNT = ExternalRef(provider="meta", level="account", id="act_1")
SPEC: dict[str, Any] = {
    "geo_locations": {"countries": ["UZ"]},
    "age_min": 25,
    "age_max": 45,
}


class FakeAudiences:
    def __init__(self, answer: ReachDTO) -> None:
        self.answer = answer
        self.asked = 0

    def estimate_reach(self, **_: Any) -> ReachDTO:
        self.asked += 1
        return self.answer


@pytest.fixture(autouse=True)
def _empty_cache() -> None:
    cache.clear()  # type: ignore[attr-defined]


def _size(port: FakeAudiences, spec: dict[str, Any], goal: str = "LEADS") -> ReachDTO:
    return interests.sized(
        port, account=ACCOUNT, targeting=spec, optimization_goal=goal, token="t"
    )


def test_the_same_audience_is_asked_about_once() -> None:
    port = FakeAudiences(ReachDTO(lower=1_000, upper=2_000))

    first = _size(port, SPEC)
    again = _size(port, dict(reversed(list(SPEC.items()))))

    assert first == again == ReachDTO(lower=1_000, upper=2_000)
    assert port.asked == 1


def test_a_changed_audience_or_goal_is_asked_again() -> None:
    port = FakeAudiences(ReachDTO(lower=1_000, upper=2_000))

    _size(port, SPEC)
    _size(port, SPEC | {"age_min": 30})
    _size(port, SPEC, goal="LINK_CLICKS")

    assert port.asked == 3


def test_an_answer_meta_has_not_finished_is_not_kept() -> None:
    port = FakeAudiences(ReachDTO(ready=False))

    _size(port, SPEC)
    _size(port, SPEC)

    assert port.asked == 2


def test_an_audience_that_cannot_be_sized_is_kept_as_such() -> None:
    port = FakeAudiences(ReachDTO(available=False))

    assert _size(port, SPEC).available is False
    assert _size(port, SPEC).available is False
    assert port.asked == 1
