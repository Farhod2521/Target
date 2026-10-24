"""Which fields each level's fresh read asks Meta for.

A table rather than a string, and this file is the reason. Meta
refuses a field a node does not have - error 100, "Tried accessing
nonexisting field" - so it is not an empty answer that gets ignored: the
call fails. And this particular call is the read taken immediately before
every write, which means one field too many at a level breaks **every**
action at that level, every time.

No network. The fields are a constant, and asserting on a constant is the
only way to catch this without an ad account.
"""

from metaads.campaigns import (
    ADSET_STATUS_FIELDS,
    BASE_STATUS_FIELDS,
    STATUS_FIELDS,
)


def _asked(level: str) -> set[str]:
    return set(STATUS_FIELDS[level].split(","))


def test_every_level_asks_for_what_it_is_delivering() -> None:
    """The two fields every object in the hierarchy has, and the pair that
    tell an advertiser's switch from what is actually happening."""
    for level in STATUS_FIELDS:
        assert {"status", "effective_status"} <= _asked(level)


def test_an_advert_is_not_asked_for_a_budget_it_cannot_hold() -> None:
    """The bug this table was made to fix. An ad node has no
    ``daily_budget`` - the money is on the group above it - and asking
    anyway fails the read every advert-level action depends on."""
    assert "daily_budget" not in _asked("ad")


def test_an_advert_is_not_asked_for_a_learning_stage_either() -> None:
    """Learning belongs to the ad set. A caller that needs it goes and asks
    the parent - see ``apps.ads.services.apply_change``."""
    assert "learning_stage_info" not in _asked("ad")


def test_a_campaign_is_not_asked_for_a_learning_stage() -> None:
    """The other half of the same rule, kept as a test rather than as a
    comment."""
    assert "learning_stage_info" not in _asked("campaign")


def test_the_group_is_the_only_level_that_reads_learning() -> None:
    assert "learning_stage_info" in _asked("adset")
    assert STATUS_FIELDS["adset"] == ADSET_STATUS_FIELDS


def test_the_fallback_asks_for_nothing_a_node_might_not_have() -> None:
    """A level nobody listed falls back to this. Wrong in the direction that
    still works - the read succeeds and answers less, where a guessed extra
    field would fail every call."""
    assert set(BASE_STATUS_FIELDS.split(",")) == {"status", "effective_status"}
