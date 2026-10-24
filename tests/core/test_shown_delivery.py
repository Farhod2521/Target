"""A campaign or group Meta calls active, drawn as its adverts show it."""

import pytest

from core.ads.delivery import shown_delivery


@pytest.mark.parametrize(
    ("ads", "shown"),
    [
        ({"pending"}, "pending"),
        ({"pending", "rejected"}, "pending"),
        ({"pending", "paused"}, "pending"),
        ({"active", "pending"}, "active"),
        ({"active", "rejected"}, "active"),
        ({"rejected"}, "rejected"),
        # Switched off in Ads Manager below a campaign that still says active.
        ({"paused"}, "paused"),
        ({"paused_above"}, "paused"),
        ({"rejected", "paused"}, "paused"),
        ({"active", "paused"}, "active"),
        (set(), "active"),
    ],
)
def test_an_active_object_reads_from_its_adverts(ads: set[str], shown: str) -> None:
    assert shown_delivery(own="active", ads=ads) == shown  # type: ignore[arg-type]


@pytest.mark.parametrize("own", ["paused", "paused_above", "finished", "rejected"])
def test_any_other_state_is_kept(own: str) -> None:
    """A paused group is paused whatever its adverts are doing."""
    assert shown_delivery(own=own, ads={"pending"}) == own  # type: ignore[arg-type]
