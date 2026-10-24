"""core/strategy/playbook: the seven strategies, argued one at a time.

Each test builds the smallest account that should or should not hear one
piece of advice. The composed scenarios at the bottom are the point of the
registry: what a whole account hears, in reading order.
"""

from typing import Any

from core.strategy import (
    BUILD_LOOKALIKE,
    CHOOSE_GOAL,
    CREATIVE_TEST,
    GO_BROAD,
    NEED_SEED_AUDIENCE,
    NEED_TRAFFIC_SOURCE,
    RETARGET,
    SCALE_UP,
    STRATEGIES,
    STRATEGY_CODES,
    WARM_START,
    AdSetPosture,
    AudienceAssets,
    SignalHistory,
    StrategyState,
    advise,
)

# Histories that land on each maturity - see test_maturity for the
# boundaries themselves; here they are only a lever.
NEW = SignalHistory(window_days=90, reported_results=0, days_with_spend=10)
GROWING = SignalHistory(window_days=90, reported_results=40, days_with_spend=30)
PROVEN = SignalHistory(
    window_days=90, reported_results=40, days_with_spend=30, has_proven_adset=True
)


def _posture(**overrides: Any) -> AdSetPosture:
    figures: dict[str, Any] = {
        "external_id": "adset-1",
        "stage": "optimizing",
        "delivery": "active",
        "counts_leads": True,
        "creatives": 2,
        "mode": None,
        "placement": None,
    }
    figures.update(overrides)
    return AdSetPosture(**figures)


def _state(**overrides: Any) -> StrategyState:
    figures: dict[str, Any] = {
        "history": GROWING,
        "assets": AudienceAssets(),
        "adsets": (_posture(),),
        "active_campaigns": 1,
    }
    figures.update(overrides)
    return StrategyState(**figures)


def _codes(state: StrategyState) -> list[str]:
    return [item.strategy for item in advise(state=state)]


# --- the registry itself --------------------------------------------------
def test_seven_strategies_seven_codes_reading_order() -> None:
    assert STRATEGY_CODES == (
        CHOOSE_GOAL,
        WARM_START,
        GO_BROAD,
        BUILD_LOOKALIKE,
        RETARGET,
        CREATIVE_TEST,
        SCALE_UP,
    )
    assert len({item.code for item in STRATEGIES}) == 7


# --- choose_goal ----------------------------------------------------------
def test_an_account_running_nothing_is_told_to_run_something() -> None:
    assert CHOOSE_GOAL in _codes(_state(active_campaigns=0))
    assert CHOOSE_GOAL not in _codes(_state(active_campaigns=1))


# --- warm_start -----------------------------------------------------------
def test_a_new_account_is_told_to_start_wide() -> None:
    assert WARM_START in _codes(_state(history=NEW))
    assert WARM_START not in _codes(_state(history=GROWING))


# --- go_broad -------------------------------------------------------------
def test_a_proven_account_still_narrowing_is_told_to_widen() -> None:
    narrowed = _state(history=PROVEN, adsets=(_posture(mode="interests"),))

    found = [item for item in advise(state=narrowed) if item.strategy == GO_BROAD]

    assert len(found) == 1
    assert found[0].evidence == {"interest_adsets": 1}


def test_an_unknown_mode_is_not_read_as_interests() -> None:
    """A hand-built ad set has no stored choice, and advice about a choice
    nobody recorded would be speaking beyond the data."""
    unknown = _state(history=PROVEN, adsets=(_posture(mode=None),))

    assert GO_BROAD not in _codes(unknown)


def test_a_growing_account_is_not_pushed_broad_yet() -> None:
    narrowed = _state(history=GROWING, adsets=(_posture(mode="interests"),))

    assert GO_BROAD not in _codes(narrowed)


# --- build_lookalike ------------------------------------------------------
def test_a_usable_seed_makes_the_lookalike_the_next_step() -> None:
    seeded = _state(history=NEW, assets=AudienceAssets(ready_seeds=2))

    found = [item for item in advise(state=seeded) if item.strategy == BUILD_LOOKALIKE]

    assert len(found) == 1
    assert found[0].ready
    assert found[0].evidence == {"ready_seeds": 2}


def test_an_existing_lookalike_closes_the_subject() -> None:
    built = _state(assets=AudienceAssets(ready_seeds=2, lookalikes=1))

    assert BUILD_LOOKALIKE not in _codes(built)


def test_no_seed_becomes_bring_the_list() -> None:
    empty_handed = _state(history=GROWING)

    found = [
        item for item in advise(state=empty_handed) if item.strategy == BUILD_LOOKALIKE
    ]

    assert len(found) == 1
    assert not found[0].ready
    assert found[0].needs == (NEED_SEED_AUDIENCE,)


def test_a_new_account_is_not_nagged_about_uploads() -> None:
    assert BUILD_LOOKALIKE not in _codes(_state(history=NEW))


# --- retarget -------------------------------------------------------------
def test_a_source_makes_retargeting_ready() -> None:
    sourced = _state(assets=AudienceAssets(has_traffic_source=True))

    found = [item for item in advise(state=sourced) if item.strategy == RETARGET]

    assert len(found) == 1
    assert found[0].ready


def test_an_existing_retargeting_audience_closes_the_subject() -> None:
    built = _state(assets=AudienceAssets(retargeting=1, has_traffic_source=True))

    assert RETARGET not in _codes(built)


def test_no_source_becomes_get_a_source_except_when_new() -> None:
    found = [
        item
        for item in advise(state=_state(history=GROWING))
        if item.strategy == RETARGET
    ]

    assert len(found) == 1
    assert not found[0].ready
    assert found[0].needs == (NEED_TRAFFIC_SOURCE,)
    assert RETARGET not in _codes(_state(history=NEW))


# --- creative_test --------------------------------------------------------
def test_one_ad_in_a_settled_adset_asks_for_variants() -> None:
    alone = _state(adsets=(_posture(creatives=1),))

    found = [item for item in advise(state=alone) if item.strategy == CREATIVE_TEST]

    assert len(found) == 1
    assert found[0].evidence == {"single_creative_adsets": 1}


def test_young_and_learning_adsets_are_not_counted() -> None:
    """Adding a creative resets the very learning being waited out."""
    early = _state(
        adsets=(
            _posture(creatives=1, stage="test"),
            _posture(external_id="adset-2", creatives=1, stage="learning"),
        )
    )

    assert CREATIVE_TEST not in _codes(early)


def test_an_adset_already_comparing_is_left_alone() -> None:
    assert CREATIVE_TEST not in _codes(_state(adsets=(_posture(creatives=2),)))


# --- scale_up -------------------------------------------------------------
def test_a_scaling_stage_adset_earns_the_growth_card() -> None:
    settled = _state(adsets=(_posture(stage="scaling", creatives=2),))

    found = [item for item in advise(state=settled) if item.strategy == SCALE_UP]

    assert len(found) == 1
    assert found[0].evidence == {"scaling_adsets": 1}


def test_nothing_scaling_means_no_growth_card() -> None:
    assert SCALE_UP not in _codes(_state())


# --- composed -------------------------------------------------------------
def test_a_fresh_empty_account_hears_exactly_two_things() -> None:
    """Run something, and keep it wide - in that order. No upload nagging,
    no retargeting plumbing: the account has nothing to build them from."""
    empty = _state(history=NEW, adsets=(), active_campaigns=0)

    assert _codes(empty) == [CHOOSE_GOAL, WARM_START]


def test_advice_arrives_in_reading_order() -> None:
    busy = _state(
        history=PROVEN,
        assets=AudienceAssets(ready_seeds=1, has_traffic_source=True),
        adsets=(
            _posture(mode="interests", creatives=1),
            _posture(external_id="adset-2", stage="scaling"),
        ),
    )

    assert _codes(busy) == [
        GO_BROAD,
        BUILD_LOOKALIKE,
        RETARGET,
        CREATIVE_TEST,
        SCALE_UP,
    ]
