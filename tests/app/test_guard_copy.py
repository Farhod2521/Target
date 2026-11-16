"""The guard's sentences: fixed words in three languages, figures put in."""

import uuid

import pytest

from app.common.i18n import override
from app.modules.agent.guard_copy import (
    BUTTONS,
    PLACES,
    TEXTS,
    WORDS,
    advised_of,
    buttons_of,
    guard_advice,
    guard_body,
    guard_place,
    guard_title,
    times_of,
)
from app.modules.agent.models import GuardAlert


def _row(**changes: object) -> GuardAlert:
    row = GuardAlert(
        id=uuid.uuid4(),
        kind="price",
        action="warn",
        advice="budget_down",
        step=3,
        times=320,
        result_kind="lead",
        currency="USD",
        name="Guruh",
        figures={
            "spend_minor": 640,
            "results": 1,
            "impressions": 2_000,
            "link_clicks": 10,
            "usual_cost_minor": 200,
            "usual_link_ctr_bp": 100,
            "usual_cpm_minor": 200,
            "causes": ["ctr"],
            "ours": True,
            "own_budget": True,
        },
    )
    for name, value in changes.items():
        setattr(row, name, value)
    return row


def test_every_language_has_every_sentence() -> None:
    assert set(TEXTS) == set(BUTTONS) == set(WORDS) == {"uz", "ru", "en"}
    for table in (TEXTS, BUTTONS, WORDS):
        assert table["uz"].keys() == table["ru"].keys() == table["en"].keys()


def test_every_sentence_takes_the_same_figures_in_every_language() -> None:
    import string

    def fields(text: str) -> set[str]:
        return {name for _, name, _, _ in string.Formatter().parse(text) if name}

    for key, text in TEXTS["uz"].items():
        assert fields(text) == fields(TEXTS["ru"][key]) == fields(TEXTS["en"][key]), key


def test_a_price_rise_in_uzbek() -> None:
    with override("uz"):
        row = _row()
        assert guard_title(row) == "Narx 3,2 baravar qimmatlashdi"
        body = guard_body(row)
        assert "Bugun bitta lid: $6,40 (1 ta). Odatda: $2." in body
        assert "Sabab: kam bosishyapti (CTR 0,50%, odatda 1,00%)." in body
        assert "Narx 5 baravarga yetsa, guruhni o'zim to'xtataman." in body
        assert guard_advice(row) == "Tavsiya: Byudjetni 20% kamaytirish."


def test_the_same_rise_in_russian_and_english() -> None:
    row = _row()
    with override("ru"):
        assert guard_title(row) == "Цена выросла в 3,2 раза"
        assert (
            "Сегодня цена результата (лид): $6,40 (всего: 1). Обычно: $2."
            in guard_body(row)
        )
        assert guard_advice(row) == "Совет: Снизить бюджет на 20%."
    with override("en"):
        assert guard_title(row) == "The price is 3.2× the usual"
        body = guard_body(row)
        assert "Today one lead costs $6.40 (1 so far). Usually: $2." in body
        assert "(CTR 0.50%, usually 1.00%)" in body


@pytest.mark.parametrize(
    ("times", "said"),
    [
        (300, "3 раза"),
        (500, "5 раз"),
        (320, "3,2 раза"),
        (1100, "11 раз"),
        (2200, "22 раза"),
    ],
)
def test_russian_times(times: int, said: str) -> None:
    with override("ru"):
        assert times_of(times) == said


def test_a_stop_says_what_was_done_and_offers_the_way_back() -> None:
    row = _row(action="stop", advice="keep_off", step=5, times=510)
    with override("uz"):
        assert guard_title(row) == "To'xtatdim: narx 5,1 baravar qimmat"
        assert "guruhni to'xtatdim" in guard_body(row)
    assert buttons_of(row) == ("resume", "keep_off")
    assert advised_of(row) == "keep_off"


def test_a_budget_is_lowered_only_where_the_group_has_one() -> None:
    row = _row()
    assert buttons_of(row) == ("pause", "budget_down", "leave")
    row.figures = {**row.figures, "own_budget": False}
    assert buttons_of(row) == ("pause", "leave")
    assert advised_of(row) == "pause"


def test_no_cause_is_said_plainly_and_never_invented() -> None:
    with override("uz"):
        row = _row()
        row.figures = {**row.figures, "causes": []}
        assert "Aniq sabab topilmadi" in guard_body(row)
        # No usual rates to hold against: nothing is claimed either way.
        row.figures = {**row.figures, "usual_link_ctr_bp": None}
        assert "sabab" not in guard_body(row).lower()


def test_money_with_nothing_back() -> None:
    row = _row(kind="fruitless", action="stop", advice="keep_off", times=300)
    row.figures = {**row.figures, "results": 0, "spend_minor": 600, "causes": []}
    with override("uz"):
        assert guard_title(row) == "To'xtatdim: natija yo'q"
        assert "Bugun $6 sarflandi, lid: 0. Odatda bitta lid: $2." in guard_body(row)


def test_where_a_group_sits_is_named_top_down() -> None:
    row = _row(
        figures={"page_name": "Gul do'koni", "campaign_name": "Kuz aksiya"},
        name="Toshkent 25-45",
    )
    with override("uz"):
        assert guard_place(row) == (
            ("Sahifa", "Gul do'koni"),
            ("Kampaniya", "Kuz aksiya"),
            ("Guruh", "Toshkent 25-45"),
        )
    with override("ru"):
        assert [label for label, _ in guard_place(row)] == [
            "Страница",
            "Кампания",
            "Группа",
        ]


def test_an_advert_finding_names_its_group_and_itself() -> None:
    row = _row(
        level="ad",
        kind="weak_ad",
        name="Video 2",
        figures={"page_name": "P", "campaign_name": "C", "group_name": "G"},
    )
    with override("en"):
        assert guard_place(row) == (
            ("Page", "P"),
            ("Campaign", "C"),
            ("Ad set", "G"),
            ("Ad", "Video 2"),
        )


def test_an_unknown_page_is_left_out_not_made_up() -> None:
    with override("uz"):
        assert guard_place(_row(figures={"campaign_name": "C"})) == (
            ("Kampaniya", "C"),
            ("Guruh", "Guruh"),
        )


def test_every_language_labels_every_place() -> None:
    assert set(PLACES) == {"uz", "ru", "en"}
    assert PLACES["uz"].keys() == PLACES["ru"].keys() == PLACES["en"].keys()


def test_the_phone_message_names_page_campaign_and_group() -> None:
    from app.modules.notifications.selectors.inbox_guard import guard_item
    from app.modules.notifications.services.announce_guard import guard_message

    row = _row(
        provider="meta",
        external_id="1",
        figures={**_row().figures, "page_name": "Gul", "campaign_name": "Kuz"},
    )
    with override("uz"):
        text = guard_message(row)
        assert "Sahifa: Gul" in text
        assert "Kampaniya: Kuz" in text
        assert "Guruh: Guruh" in text
        item = guard_item(row)
    assert item.subject is not None
    assert item.subject.place[0] == ("Sahifa", "Gul")
