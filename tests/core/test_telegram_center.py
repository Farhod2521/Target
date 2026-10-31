"""A notice says what happened; the answer is in the center, never on another page."""

from core.inbox import InboxItem


def test_a_trouble_links_to_its_line_in_the_center() -> None:
    from app.modules.notifications.services.compose import trouble_message

    item = InboxItem(
        key="stop:1 2",
        kind="stop",
        level="urgent",
        title="To'xtadi",
        body="Sabab",
        action="To'lov sahifasini ochish",
        href="https://business.facebook.com/billing",
    )

    text = trouble_message(item=item).text

    assert "/app/amallar/?item=stop%3A1+2" in text
    assert "business.facebook.com" not in text


def test_a_refused_ad_and_a_broken_connection_link_to_the_center() -> None:
    from app.modules.notifications.services.compose import (
        connection_message,
        rejection_message,
    )

    refused = rejection_message(ad_name="a", group_name="g", feedback={})

    assert "/app/amallar/" in refused.text
    assert "/app/amallar/" in connection_message().text


def test_meta_asking_for_a_person_links_to_the_center_too() -> None:
    from app.modules.notifications.services.compose import action_required_message

    text = action_required_message(person="A", manager_url="https://m.example").text

    assert "https://m.example" in text
    assert "/app/amallar/?item=meta_hold" in text


def test_a_notice_button_opens_its_own_line(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.modules.notifications.services import compose

    monkeypatch.setattr(compose, "miniapp_button", lambda **kept: kept)

    assert compose.center_button(item_key="suggestion:1")["query"] == (
        "item=suggestion%3A1"
    )
    assert compose.center_button()["query"] == ""
