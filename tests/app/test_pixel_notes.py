"""The review's warnings about the launch's pixel: said, never refused."""

from app.modules.ads.contract.launch.review import _pixel_notes


def test_ok_and_nothing_say_nothing() -> None:
    assert _pixel_notes(None) == []
    assert _pixel_notes({"state": "ok", "pixel": "AI pixel"}) == []


def test_a_pixel_on_another_site_names_where_it_fired() -> None:
    (note,) = _pixel_notes(
        {
            "state": "not_on_site",
            "pixel": "AI pixel",
            "host": "bahor.uz",
            "hosts": ["shop.example.com", "landing.example.com"],
        }
    )

    assert note["tone"] == "w" and note["action"]["to"] == "adv"
    assert "bahor.uz" in note["text"] and "shop.example.com" in note["text"]


def test_never_fired_and_no_results_have_their_own_words() -> None:
    never = _pixel_notes({"state": "never_fired", "pixel": "X"})
    quiet = _pixel_notes({"state": "no_results", "pixel": "X"})

    assert never[0]["id"] == "pixel_never_fired"
    assert quiet[0]["id"] == "pixel_no_results"


def test_a_poor_match_names_its_score() -> None:
    (note,) = _pixel_notes({"state": "poor_match", "pixel": "X", "match_quality": 2.5})

    assert note["id"] == "pixel_poor_match" and "2.5/10" in note["text"]
