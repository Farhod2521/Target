"""metaads/delivery.py: an ad set's bid, attribution window and frequency cap."""

from typing import Any

from metaads.delivery import Delivery, payload, read, write


def test_a_cost_cap_is_read_with_its_amount() -> None:
    held = read({"bid_strategy": "COST_CAP", "bid_amount": "250"})

    assert held == Delivery(cap_minor=250)


def test_the_lowest_cost_is_no_cap_even_with_a_stale_amount() -> None:
    assert (
        read({"bid_strategy": "LOWEST_COST_WITHOUT_CAP", "bid_amount": 90}).cap_minor
        is None
    )
    assert read({}) == Delivery()


def test_a_bid_cap_from_ads_manager_is_said_and_not_read_as_ours() -> None:
    held = read({"bid_strategy": "LOWEST_COST_WITH_BID_CAP", "bid_amount": 90})

    assert held.cap_minor is None
    assert held.foreign_bid == "LOWEST_COST_WITH_BID_CAP"


def test_the_window_and_the_frequency_are_read_as_plain_days() -> None:
    held = read(
        {
            "attribution_spec": [
                {"event_type": "VIEW_THROUGH", "window_days": 1},
                {"event_type": "CLICK_THROUGH", "window_days": 7},
            ],
            "frequency_control_specs": [
                {"event": "IMPRESSIONS", "interval_days": 7, "max_frequency": 2}
            ],
        }
    )

    assert held.window == (7, 1)
    assert held.frequency == (2, 7)


def test_a_cap_is_two_fields_and_removing_it_is_one() -> None:
    assert payload(cap_minor=300) == {"bid_strategy": "COST_CAP", "bid_amount": 300}
    assert payload(remove_cap=True) == {"bid_strategy": "LOWEST_COST_WITHOUT_CAP"}


def test_a_setting_not_named_is_not_sent() -> None:
    assert payload() == {}
    assert payload(window=(7, 0)) == {
        "attribution_spec": [{"event_type": "CLICK_THROUGH", "window_days": 7}]
    }
    assert payload(window=(1, 1))["attribution_spec"][1] == {
        "event_type": "VIEW_THROUGH",
        "window_days": 1,
    }


def test_a_frequency_cap_is_set_and_taken_off() -> None:
    assert payload(frequency=(2, 7)) == {
        "frequency_control_specs": [
            {"event": "IMPRESSIONS", "interval_days": 7, "max_frequency": 2}
        ]
    }
    assert payload(remove_frequency=True) == {"frequency_control_specs": []}


class _Graph:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, Any]]] = []

    def for_token(self, _token: str) -> "_Graph":
        return self

    def post(self, path: str, **data: Any) -> dict[str, Any]:
        self.posts.append((path, data))
        return {"success": True}


def test_one_call_carries_them_all_and_a_rehearsal_sends_nothing() -> None:
    graph = _Graph()
    data = payload(cap_minor=300, remove_frequency=True)

    assert write(adset_id="s_1", data=data, token="t", client=graph, dry_run=False)  # type: ignore[arg-type]
    assert write(adset_id="s_1", data=data, token="t", client=graph)  # type: ignore[arg-type]
    assert write(adset_id="s_1", data={}, token="t", client=graph, dry_run=False)  # type: ignore[arg-type]

    assert len(graph.posts) == 1
    path, sent = graph.posts[0]
    assert path == "s_1"
    assert set(sent) == {"bid_strategy", "bid_amount", "frequency_control_specs"}
