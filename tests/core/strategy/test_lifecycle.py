"""core/strategy/lifecycle: where one ad set is in its life.

The stages are read from values, never from a clock: age arrives as hours
somebody else computed, which is what lets a boundary be tested to the
hour.
"""

from typing import Any

from core.strategy import cooldown_hours, may_adjust, may_scale, stage

# The thresholds every test reads against, spelled once. The same figures
# as ``core.agent.Policy`` defaults, passed rather than imported: the
# stage function takes them as arguments precisely so the two packages
# never depend on each other.
TEST_HOURS = 72
MIN_DAYS = 3


def _stage(**overrides: Any) -> str:
    figures: dict[str, Any] = {
        "age_hours": 200,
        "is_learning": False,
        "learning_status": "",
        "days_with_spend": 7,
        "test_hours": TEST_HOURS,
        "min_days": MIN_DAYS,
    }
    figures.update(overrides)
    return stage(**figures)


# --- the test window ------------------------------------------------------
def test_younger_than_the_grace_period_is_test() -> None:
    assert _stage(age_hours=71) == "test"
    assert _stage(age_hours=0) == "test"


def test_the_grace_period_ends_at_its_boundary() -> None:
    assert _stage(age_hours=72) != "test"


def test_test_wins_over_learning() -> None:
    """A day-old ad set is always learning too, and "too young to judge"
    is the stricter and more truthful sentence."""
    assert _stage(age_hours=10, is_learning=True) == "test"


def test_unknown_age_is_not_held_in_test_forever() -> None:
    """A hand-built ad set the provider never dated would otherwise be
    silenced for good; a genuinely fresh one is caught by learning."""
    assert _stage(age_hours=None) == "optimizing"
    assert _stage(age_hours=None, is_learning=True) == "learning"


# --- learning and past it -------------------------------------------------
def test_still_learning_is_learning() -> None:
    assert _stage(is_learning=True) == "learning"


def test_success_with_evidence_is_scaling() -> None:
    assert _stage(learning_status="SUCCESS") == "scaling"


def test_success_without_evidence_days_is_only_optimizing() -> None:
    """The verdict says the ad set *can* be scaled; the spend days are the
    evidence a decision would be made on. One without the other is not
    enough."""
    assert _stage(learning_status="SUCCESS", days_with_spend=2) == "optimizing"


def test_no_verdict_is_optimizing() -> None:
    assert _stage() == "optimizing"
    assert _stage(learning_status="FAIL") == "optimizing"


# --- what each stage permits ----------------------------------------------
def test_only_the_two_settled_stages_may_be_adjusted() -> None:
    assert not may_adjust("test")
    assert not may_adjust("learning")
    assert may_adjust("optimizing")
    assert may_adjust("scaling")


def test_only_scaling_is_stable_footing_for_growth() -> None:
    assert may_scale("scaling")
    assert not may_scale("optimizing")
    assert not may_scale("test")
    assert not may_scale("learning")


# --- the stage's own pace -------------------------------------------------
def test_scaling_waits_longer_than_optimizing() -> None:
    assert cooldown_hours(stage="optimizing", floor_hours=48) == 48
    assert cooldown_hours(stage="scaling", floor_hours=48) == 72


def test_the_owners_setting_can_lengthen_but_never_shorten() -> None:
    assert cooldown_hours(stage="optimizing", floor_hours=60) == 60
    assert cooldown_hours(stage="scaling", floor_hours=100) == 100
    assert cooldown_hours(stage="scaling", floor_hours=12) == 72


def test_the_untouchable_stages_fall_back_to_the_floor() -> None:
    """Nothing is changed in them at all, so the figure is for completeness
    rather than for use."""
    assert cooldown_hours(stage="test", floor_hours=48) == 48
    assert cooldown_hours(stage="learning", floor_hours=48) == 48
