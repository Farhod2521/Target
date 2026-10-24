"""The greeting at the start goes; the button the close repeats goes too."""

from videokit import Brand, Cut

from core.montage import SpokenWord
from core.montage.greetings import without_greeting
from core.montage.placement import place
from core.montage.plan import plan_schema

OKINA = chr(0x02BB)


def _said(text: str, *, start: float = 0.5) -> tuple[SpokenWord, ...]:
    return tuple(
        SpokenWord(text=w, start=start + i * 0.5, end=start + i * 0.5 + 0.4)
        for i, w in enumerate(text.split())
    )


def test_a_greeting_and_a_name_are_cut_from_the_start() -> None:
    words = _said(f"Assalomu alaykum, do{OKINA}stlar! Bugun sizga chegirma haqida")
    cuts = [Cut(start=0.42, end=5.0), Cut(start=6.0, end=8.0)]

    kept = without_greeting(cuts, words)

    # On the fourth word, with a breath before it; the rest untouched.
    assert kept[0].start == round(words[3].start - 0.08, 3)
    assert kept[1:] == cuts[1:]


def test_russian_greetings_count_too() -> None:
    words = _said("Всем привет! Сегодня расскажу про скидки")

    assert without_greeting([Cut(start=0.4, end=4.0)], words)[0].start > 1.4


def test_a_greeting_with_nothing_after_it_stays() -> None:
    words = _said("Salom do'stlar va")
    cuts = [Cut(start=0.4, end=2.0)]

    assert without_greeting(cuts, words) == cuts


def test_a_planners_button_near_the_end_gives_way_to_the_closing_one() -> None:
    words = tuple(
        SpokenWord(text=f"w{i}", start=i * 0.5, end=i * 0.5 + 0.4) for i in range(40)
    )
    plan = plan_schema(word_count=40).model_validate(
        {"segments": [{"start": 0, "end": 20}], "summary": "-", "events": [
            {"component": "cta_button", "anchor_word": 10, "until_word": 12,
             "props": {}},
            {"component": "cta_button", "anchor_word": 26, "until_word": 28,
             "props": {}},
        ]}
    )  # fmt: skip

    placed = place(
        events=plan.events,
        words=words,
        cuts=(Cut(start=0, end=20),),
        brand=Brand(name="B", cta_text="Telegram", cta_handle="@b"),
    )

    buttons = [c.start for c in placed.components if c.name == "cta_button"]
    assert buttons == [5.0]
