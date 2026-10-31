"""What a person may pick: ranked rows, read but never written."""

import pytest
from metaads import adapter as module

ROWS = {
    "behaviors": [
        {"id": "2", "name": "Frequent travellers"},
        {"id": "3", "name": "Gamers"},
    ],
    "life_events": [{"id": "4", "name": "Travel soon"}],
}


@pytest.fixture
def graph(monkeypatch: pytest.MonkeyPatch) -> None:
    class Session:
        def __enter__(self) -> object:
            return object()

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(module, "session", lambda _token: Session())
    monkeypatch.setattr(
        module,
        "search_interests",
        lambda **_k: [{"id": "1", "name": "Travel"}, {"name": "No id"}],
    )
    monkeypatch.setattr(module, "browse_traits", lambda *, klass, **_k: ROWS[klass])
    monkeypatch.setattr(
        module,
        "search_locales",
        lambda **_k: [{"key": 6, "name": "English"}, {"key": "x", "name": "Bad"}],
    )


@pytest.mark.usefixtures("graph")
def test_detail_finds_interests_and_the_traits_that_hold_the_word() -> None:
    found = module.MetaAudiences().search_detail(query="travel", token="t")

    assert [(row.ref.id, row.kind) for row in found] == [
        ("1", "interest"),
        ("2", "behaviour"),
        ("4", "life_event"),
    ]


@pytest.mark.usefixtures("graph")
def test_languages_keep_only_rows_with_a_number() -> None:
    found = module.MetaAudiences().search_locales(query="eng", token="t")

    assert [(row.key, row.name) for row in found] == [(6, "English")]


def test_an_empty_word_asks_nothing() -> None:
    assert module.MetaAudiences().search_detail(query=" ", token="t") == []
    assert module.MetaAudiences().search_locales(query=" ", token="t") == []
