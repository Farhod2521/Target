"""An ad set's delivery settings: what a result may cost, which results count, how often.

Three settings Meta keeps on the ad set and this product's mirror does not:
the bid (a strategy and, under a cap, an amount), the attribution window, and
the frequency cap. They are read when somebody opens them and written in one
call, because Meta refuses some pairs taken apart - a cost cap strategy with
no amount is one.

**A cap is two fields and removing it is one.** ``COST_CAP`` needs
``bid_amount`` beside it; going back to the lowest cost sends the strategy
alone, and an amount sent with it is refused.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from metaads.client import GraphClient
from metaads.specs import BID_COST_CAP, BID_LOWEST_COST, CAPPED_STRATEGIES
from metaads.writing import is_dry_run_id, post_object

CLICK: Final = "CLICK_THROUGH"
VIEW: Final = "VIEW_THROUGH"
IMPRESSIONS: Final = "IMPRESSIONS"
_SUCCESS: Final = "success"


@dataclass(frozen=True, slots=True)
class Delivery:
    """The three settings as plain values.

    ``cap_minor`` is the price per result in the account currency's minor
    units, ``None`` for no cap. ``window`` is days counted after a click and
    after a view, ``None`` where Meta holds none. ``frequency`` is how many
    times in how many days, ``None`` for no cap.
    """

    cap_minor: int | None = None
    window: tuple[int, int] | None = None
    frequency: tuple[int, int] | None = None
    # A capped strategy that is not a cost cap (a bid cap made in Ads
    # Manager): shown, and never rewritten as something it is not.
    foreign_bid: str = ""


def read(row: Mapping[str, Any]) -> Delivery:
    """Meta's own four fields, as they come from the ad set, in plain values."""
    strategy = str(row.get("bid_strategy") or "")
    amount = _whole(row.get("bid_amount"))
    capped = strategy == BID_COST_CAP and amount
    return Delivery(
        cap_minor=amount if capped else None,
        window=_window(row.get("attribution_spec")),
        frequency=_frequency(row.get("frequency_control_specs")),
        foreign_bid=strategy
        if strategy in CAPPED_STRATEGIES and strategy != BID_COST_CAP
        else "",
    )


def _whole(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _window(spec: object) -> tuple[int, int] | None:
    if not isinstance(spec, list) or not spec:
        return None
    days = {CLICK: 0, VIEW: 0}
    for row in spec:
        if isinstance(row, Mapping) and row.get("event_type") in days:
            days[str(row["event_type"])] = _whole(row.get("window_days"))
    return (days[CLICK], days[VIEW]) if days[CLICK] else None


def _frequency(specs: object) -> tuple[int, int] | None:
    if not isinstance(specs, list):
        return None
    for row in specs:
        if not isinstance(row, Mapping) or row.get("event") != IMPRESSIONS:
            continue
        times = _whole(row.get("max_frequency"))
        days = _whole(row.get("interval_days"))
        if times and days:
            return times, days
    return None


def payload(
    *,
    cap_minor: int | None = None,
    remove_cap: bool = False,
    window: tuple[int, int] | None = None,
    frequency: tuple[int, int] | None = None,
    remove_frequency: bool = False,
) -> dict[str, Any]:
    """The fields one change sends; a setting not named is not in it."""
    data: dict[str, Any] = {}
    if remove_cap:
        data["bid_strategy"] = BID_LOWEST_COST
    elif cap_minor:
        data["bid_strategy"] = BID_COST_CAP
        data["bid_amount"] = cap_minor
    if window is not None:
        clicks, views = window
        spec: list[dict[str, Any]] = [{"event_type": CLICK, "window_days": clicks}]
        if views:
            spec.append({"event_type": VIEW, "window_days": views})
        data["attribution_spec"] = spec
    if remove_frequency:
        data["frequency_control_specs"] = []
    elif frequency is not None:
        times, days = frequency
        data["frequency_control_specs"] = [
            {"event": IMPRESSIONS, "interval_days": days, "max_frequency": times}
        ]
    return data


def write(
    *,
    adset_id: str,
    data: Mapping[str, Any],
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> bool:
    """Send the settings to one ad set, all in one call."""
    if dry_run or is_dry_run_id(adset_id) or not data:
        return True
    answer = post_object(path=adset_id, data=dict(data), token=token, client=client)
    return bool(answer.get(_SUCCESS, True))


__all__ = ["CLICK", "IMPRESSIONS", "VIEW", "Delivery", "payload", "read", "write"]
