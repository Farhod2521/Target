"""An account Meta has not opened to a goal gets the older goal for the same result."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from adskit.dto import ActionResult
from adskit.errors import GoalNotOpen
from adskit.refs import ExternalRef, ProviderName
from metaads.specs import AdSetSpec

from app.common.trace import NoTrace
from app.modules.ads.services import sequence
from app.modules.ads.services.creation import FAILURE_CODES

ACCOUNT = ExternalRef(provider=ProviderName("meta"), level="account", id="act_1")
MADE = ActionResult(
    ok=True, ref=ExternalRef(provider=ProviderName("meta"), level="adset", id="9")
)


def _spec(goal: str, destination: str = "INSTAGRAM_PROFILE") -> AdSetSpec:
    return AdSetSpec(
        name="Guruh",
        campaign_id="1",
        optimization_goal=goal,
        billing_event="IMPRESSIONS",
        destination_type=destination,
    )


class Launcher:
    """Refuses every goal named in ``closed``, keeps the rest."""

    def __init__(self, *closed: str) -> None:
        self.closed = closed
        self.sent: list[str] = []

    def create_adset(self, *, spec: AdSetSpec, **_: Any) -> ActionResult:
        self.sent.append(spec.optimization_goal)
        if spec.optimization_goal in self.closed:
            raise GoalNotOpen("Invalid parameter", code="2016153")
        return MADE


def _made(spec: AdSetSpec, launcher: Launcher) -> tuple[AdSetSpec, ActionResult]:
    return sequence._adset_made(
        MagicMock(),
        launch=MagicMock(),
        spec=spec,
        launcher=launcher,  # type: ignore[arg-type]
        provider=ProviderName("meta"),
        account_ref=ACCOUNT,
        token="t",
        dry_run=False,
        watch=NoTrace(),
    )


def test_a_closed_profile_visit_is_sent_once_more_with_the_older_goal() -> None:
    launcher = Launcher("PROFILE_VISIT")

    kept, made = _made(_spec("PROFILE_VISIT"), launcher)

    assert launcher.sent == ["PROFILE_VISIT", "VISIT_INSTAGRAM_PROFILE"]
    assert kept.optimization_goal == "VISIT_INSTAGRAM_PROFILE"
    assert made is MADE


def test_an_open_goal_is_sent_once() -> None:
    launcher = Launcher()

    kept, _ = _made(_spec("PROFILE_VISIT"), launcher)

    assert launcher.sent == ["PROFILE_VISIT"]
    assert kept.optimization_goal == "PROFILE_VISIT"


def test_the_older_goal_refused_too_is_not_tried_a_third_time() -> None:
    launcher = Launcher("PROFILE_VISIT", "VISIT_INSTAGRAM_PROFILE")

    with pytest.raises(GoalNotOpen):
        _made(_spec("PROFILE_VISIT"), launcher)
    assert launcher.sent == ["PROFILE_VISIT", "VISIT_INSTAGRAM_PROFILE"]


def test_a_goal_with_no_older_one_stays_refused() -> None:
    launcher = Launcher("QUALITY_CALL")

    with pytest.raises(GoalNotOpen):
        _made(_spec("QUALITY_CALL", destination="PHONE_CALL"), launcher)
    assert launcher.sent == ["QUALITY_CALL"]


def test_a_launch_that_still_fails_reads_as_refused() -> None:
    assert FAILURE_CODES["GoalNotOpen"] == "refused"
