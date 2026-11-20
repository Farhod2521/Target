"""Places an AI answer names: the name in the reader's language, the link
from the one table of routes, and nothing for a key that is not ours."""

from app.common.config import settings
from app.common.places import PLACES, keys_line, linked, url_of
from app.common.routes import reverse


def test_every_place_has_a_route_and_three_names() -> None:
    for key, place in PLACES.items():
        assert reverse(place.route).startswith("/"), key
        assert {"uz", "ru", "en"} <= set(place.names), key


def test_a_token_becomes_the_name_and_a_link() -> None:
    placed = linked(
        "1. [[boshqaruv]] da «Qayta ulash» ni bosing.\n2. Yana [[boshqaruv]].",
        language="uz",
    )

    assert placed.text.startswith("1. «Sozlash → Boshqaruv» da")
    assert "[[" not in placed.text
    assert placed.links == [
        {
            "key": "boshqaruv",
            "title": "Sozlash → Boshqaruv",
            "url": f"{settings.site_url}/app/connections/",
        }
    ]


def test_the_name_follows_the_language_and_the_brackets_are_not_doubled() -> None:
    placed = linked("Откройте «[[obuna]]».", language="ru")

    assert placed.text == "Откройте «Настройка → Подписка и оплата»."


def test_an_unknown_key_leaves_nothing() -> None:
    placed = linked("Oching: [[admin_panel]].", language="uz")

    assert placed.text == "Oching: ."
    assert placed.links == []


def test_a_token_half_written_is_held_back_while_streaming() -> None:
    assert linked("Bosing [[boshq", language="uz", done=False).text == "Bosing "
    assert linked("Bosing [[boshqaruv]", language="uz", done=False).text == "Bosing "
    whole = linked("Bosing [[boshqaruv]]", language="uz", done=False)
    assert whole.text == "Bosing «Sozlash → Boshqaruv»"


def test_the_support_card_opens_the_guest_chat() -> None:
    assert url_of("kirish_yordam").endswith("/accounts/login/?yordam=chat")


def test_the_prompt_lists_every_key() -> None:
    from app.common.llm import prompts

    for name in ("assistant", "chat_answer"):
        template, _version = prompts().get(name)
        assert "{{ places }}" in template, name
    assert all(f"[[{key}]]" in keys_line() for key in PLACES)


def test_a_place_is_named_in_the_script_the_person_wrote() -> None:
    from app.common.places import linked

    assert linked("[[kirish]]", language="uz").text == "«Kirish sahifasi»"
    assert linked("[[kirish]]", language="uz-cyrl").text == "«Кириш саҳифаси»"
    assert linked("[[kirish]]", language="ru").text == "«Страница входа»"


def test_status_lines_follow_the_answer() -> None:
    from app.common.shown import shown, shown_language

    assert shown("Qidiryapman…", "ru") == "Ищу…"
    assert shown("Qidiryapman…", "uz-cyrl") == "Қидиряпман…"
    assert shown("Qidiryapman…", "uz") == "Qidiryapman…"
    assert shown("Unknown line", "en") == "Unknown line"
    assert shown_language({"language": "uz", "shown": "uz-cyrl"}) == "uz-cyrl"
    assert shown_language({"language": "ru"}) == "ru"
