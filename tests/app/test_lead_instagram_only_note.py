"""A lead form on Instagram alone is warned about before launch, never refused."""

from app.modules.ads.contract.launch.review import attention


def _ids(found: dict) -> list[str]:
    return [note["id"] for note in attention({}, found)]


def test_a_lead_form_on_instagram_alone_is_warned_about() -> None:
    found = {"lead_form": {"card": {}}, "audience": {"placement_mode": "instagram"}}

    notes = attention({}, found)

    note = next(note for note in notes if note["id"] == "lead_instagram_only")
    assert note["tone"] == "w"
    assert note["action"]["to"] == "aud"


def test_no_warning_with_facebook_or_left_to_meta() -> None:
    for mode in ("standard", "automatic", "facebook"):
        found = {"lead_form": {"card": {}}, "audience": {"placement_mode": mode}}
        assert "lead_instagram_only" not in _ids(found)


def test_no_warning_without_a_lead_form() -> None:
    found = {"lead_form": None, "audience": {"placement_mode": "instagram"}}

    assert "lead_instagram_only" not in _ids(found)
