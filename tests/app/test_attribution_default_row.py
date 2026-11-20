"""The Attribution card names the window Meta counts by when none was chosen."""

from typing import Any

from app.modules.ads.contract.launch.edit import _advanced

WINDOWS = [
    {"key": "click_7_view_1", "label": "7 kun bosish, 1 kun ko'rish"},
    {"key": "click_1", "label": "1 kun bosish"},
]


def _found(chosen: str) -> dict[str, Any]:
    delivery = {
        "offers_window": True,
        "windows": WINDOWS,
        "chosen_window": chosen,
        "locked": False,
    }
    return {"advanced": {"delivery": delivery}}


def _row(chosen: str) -> dict[str, Any]:
    return next(row for row in _advanced(_found(chosen)) if row["key"] == "attribution")


def test_no_choice_shows_metas_default() -> None:
    assert _row("")["value"] == "7 kun bosish, 1 kun ko'rish"


def test_the_owners_choice_is_shown() -> None:
    assert _row("click_1")["value"] == "1 kun bosish"
