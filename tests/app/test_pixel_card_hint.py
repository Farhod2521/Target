"""The «Piksel» card: what the website sent through each pixel, and ids for twins."""

from datetime import UTC, datetime
from typing import Any

from app.modules.ads.contract.launch.edit import _advanced, _pixel_hint, _pixel_names


def test_twin_names_are_told_apart_by_their_ids() -> None:
    pixels = [
        {"external_id": "1", "name": "Asosiy"},
        {"external_id": "2", "name": "Asosiy"},
        {"external_id": "3", "name": "Vebinar"},
    ]

    assert _pixel_names(pixels) == ["Asosiy (1)", "Asosiy (2)", "Vebinar"]


def test_the_hint_says_what_the_site_sent_and_when_it_last_fired() -> None:
    fired = datetime(2026, 11, 19, 20, 10, tzinfo=UTC)

    assert _pixel_hint({"site_results": 532, "last_fired_at": fired}) == {
        "meta": "saytdan 7 kunda 532 ta natija · oxirgi marta 19.11.2026",
        "warn": "",
    }
    assert _pixel_hint({"site_results": 0, "last_fired_at": fired})["warn"]
    assert _pixel_hint({"site_results": None, "last_fired_at": None}) == {
        "meta": "",
        "warn": "Bu piksel hech qachon ishlamagan.",
    }


def test_the_card_holds_the_chosen_twin() -> None:
    pixels: list[dict[str, Any]] = [
        {"external_id": "1", "name": "Asosiy", "is_chosen": False},
        {"external_id": "2", "name": "Asosiy", "is_chosen": True},
    ]
    row = next(
        r for r in _advanced({"advanced": {"pixels": pixels}}) if r["key"] == "pixel"
    )

    assert row["value"] == "Asosiy (2)"
