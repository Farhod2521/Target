"""TZ 7.4: Meta's advice is never shown, and only its technical side
reaches the AI.

The two recommendations production holds - "Ad Set Ended" and "Your Ad Set
Targets Multiple Countries" - are both dropped, as is every budget,
placement, audience and Advantage+ suggestion.
"""

from app.modules.ads.recommendations import is_technical, technical
from app.modules.chat.selectors.readings import advice_of

ENDED = {
    "code": "1942016",
    "title": "Ad Set Ended",
    "message": "Your ad set 'mebel' recently ended. Consider rescheduling it.",
    "blame_field": "end_time",
    "confidence": "HIGH",
}
COUNTRIES = {
    "code": "1942004",
    "title": "Your Ad Set Targets Multiple Countries",
    "message": "Impressions for these ads may not be distributed evenly.",
    "blame_field": "targeting",
    "confidence": "HIGH",
}
PIXEL = {
    "title": "Pixel not receiving events",
    "message": "Your pixel has not received a Lead event in 7 days.",
    "confidence": "HIGH",
}


def test_what_production_holds_is_not_technical() -> None:
    assert not is_technical(ENDED)
    assert not is_technical(COUNTRIES)


def test_a_pixel_fault_is_technical() -> None:
    assert is_technical(PIXEL)


def test_budget_placement_and_advantage_advice_is_dropped() -> None:
    for title in (
        "Increase your budget",
        "Use Advantage+ placements",
        "Try Advantage+ audience",
        "Optimise event delivery with a larger budget",
    ):
        assert not is_technical({"title": title, "confidence": "HIGH"}), title


def test_a_low_confidence_one_is_dropped() -> None:
    assert not is_technical(PIXEL | {"confidence": "LOW"})


def test_only_technical_ones_are_kept_in_order() -> None:
    assert technical([ENDED, PIXEL, "noise", COUNTRIES]) == [PIXEL]


def test_the_chat_hears_only_the_technical_one() -> None:
    assert advice_of([ENDED, COUNTRIES]) == ""
    assert advice_of([ENDED, PIXEL]) == "Pixel not receiving events"
