"""A Brand Face's rules: complete or not, its brief, its colours, its contacts."""

import pytest
from pydantic import ValidationError

from core.montage.brand import resolved
from core.montage.brand_face import (
    BRIEF_MAX_WORDS,
    Contacts,
    Palette,
    brief,
    contrast_problems,
    is_complete,
    suggested_palette,
)
from core.montage.colors import contrast_ratio, readable_on
from core.montage.handles import instagram_username, split_handle, telegram_username
from core.montage.logo import LogoAnalysis, copies, removable

LOGO = LogoAnalysis(
    logo_type="wordmark",
    text_in_logo="Bahor",
    contains_brand_name=True,
    dominant_colors=["#e11d48"],
    best_background="any",
    style_keywords=["minimal", "bold"],
    suggested_font_preset="bold",
    suggested_accent="#22c55e",
    notes="",
)
NEUTRAL = Palette(primary="#1e293b", accent="#facc15", text="#ffffff")


@pytest.mark.parametrize(
    ("name", "description", "contacts", "complete"),
    [
        ("Bahor", "Gullar.", Contacts(telegram="bahor"), True),
        ("Bahor", "Gullar.", Contacts(instagram="bahor"), True),
        ("Bahor", "Gullar.", Contacts(phone="+12025550123"), True),
        ("", "Gullar.", Contacts(telegram="bahor"), False),
        ("Bahor", "  ", Contacts(telegram="bahor"), False),
        ("Bahor", "Gullar.", Contacts(), False),
    ],
)
def test_complete_means_a_name_a_description_and_a_contact(
    name: str, description: str, contacts: Contacts, complete: bool
) -> None:
    assert is_complete(brand_name=name, description=description, contacts=contacts) is (
        complete
    )


def test_the_brief_says_what_matters_in_few_words() -> None:
    text = brief(
        brand_name="Bahor",
        description="Toshkentda gul yetkazib beramiz",
        tagline="Har kuni yangi",
        cta_text="Yozing",
        contacts=Contacts(telegram="bahor", phone="+12025550123"),
        logo=LOGO,
    )

    assert text == (
        "Brand: Bahor. What it does: Toshkentda gul yetkazib beramiz. "
        "Tagline: Har kuni yangi. "
        'Logo: lettering only reading "Bahor"; style minimal, bold. '
        "Contact: Telegram @bahor, phone +12025550123. Call to action: Yozing."
    )


def test_a_long_description_is_cut_to_the_brief_s_limit() -> None:
    text = brief(
        brand_name="Bahor",
        description="so'z " * 300,
        tagline="",
        cta_text="",
        contacts=Contacts(telegram="bahor"),
        logo=None,
    )

    assert len(text.split()) == BRIEF_MAX_WORDS
    assert text.endswith("…")


def test_a_dark_logo_colour_is_not_offered_as_the_accent() -> None:
    picked = suggested_palette(
        colors=("#e11d48", "#1e1e3c"), logo=None, neutral=NEUTRAL
    )

    assert picked.accent == "#facc15"


def test_suggested_colours_come_from_the_logo_and_its_look() -> None:
    picked = suggested_palette(
        colors=("#ffffff", "#e11d48", "#2563eb"), logo=LOGO, neutral=NEUTRAL
    )

    # White is a background, not a brand; the accent is what was suggested;
    # white reads better than near-black on this red (4.7 to 4.0).
    assert picked == Palette(primary="#e11d48", accent="#22c55e", text="#ffffff")
    assert suggested_palette(colors=(), logo=None, neutral=NEUTRAL) == Palette(
        primary="#1e293b", accent="#facc15", text="#ffffff"
    )


@pytest.mark.parametrize(
    ("first", "second", "ratio"),
    [
        ("#000000", "#ffffff", 21.0),
        ("#ffffff", "#ffffff", 1.0),
        ("#777777", "#ffffff", 4.48),
    ],
)
def test_contrast_is_wcags(first: str, second: str, ratio: float) -> None:
    assert contrast_ratio(first, second) == pytest.approx(ratio, abs=0.01)


def test_text_on_a_colour_is_whichever_reads_better() -> None:
    assert readable_on("#facc15") == "#111111"
    assert readable_on("#1e293b") == "#ffffff"


def test_contrast_problems_are_named_and_half_typed_colours_are_not_judged() -> None:
    assert contrast_problems(primary="#1e293b", accent="#facc15", text="#ffffff") == ()
    assert contrast_problems(primary="#777777", accent="#222222", text="#888888") == (
        "text_on_primary",
        "accent_on_video",
    )
    assert contrast_problems(primary="#12", accent="", text="#ffffff") == ()


@pytest.mark.parametrize(
    ("typed", "username"),
    [
        ("dokon", "dokon"),
        ("@Dokon.Uz", "dokon.uz"),
        ("instagram.com/dokon", "dokon"),
        ("https://www.instagram.com/dokon/?igsh=abc123", "dokon"),
        ("https://m.instagram.com/dokon", "dokon"),
        ("https://example.com/dokon", ""),
        ("dokon..uz", ""),
        ("bad name", ""),
        ("", ""),
    ],
)
def test_an_instagram_username_is_found_however_typed(
    typed: str, username: str
) -> None:
    assert instagram_username(typed) == username


@pytest.mark.parametrize(
    ("typed", "username"),
    [("@osh_markazi", "osh_markazi"), ("https://t.me/osh_markazi/", "osh_markazi")],
)
def test_a_telegram_username_is_found_however_typed(typed: str, username: str) -> None:
    assert telegram_username(typed) == username


@pytest.mark.parametrize(
    ("alpha", "shares", "dark", "light"),
    [
        (True, [("#0a0a28", 1.0)], "white", "own"),
        (True, [("#f5f5f5", 1.0)], "own", "black"),
        (True, [("#e11d48", 1.0)], "own", "own"),
        # A bright mark beside dark lettering: the lettering would vanish,
        # and painting it all white would lose the pink - a badge instead.
        (True, [("#ee489a", 0.6), ("#5b1d8b", 0.4)], "light_badge", "own"),
        # Thin dark lettering beside a big green mark: a fifth of the drawing.
        (
            True,
            [("#16a44b", 0.73), ("#0f172a", 0.19), ("#f3faf5", 0.08)],
            "light_badge",
            "own",
        ),
        # One dark colour and the soft edge of its strokes: painted white.
        (True, [("#1a1a2e", 0.9), ("#5a5a6a", 0.1)], "white", "own"),
        # White lettering beside a yellow mark, on light: a dark badge.
        (True, [("#ffffff", 0.5), ("#facc15", 0.5)], "own", "dark_badge"),
        # A thin dark outline is not worth losing the colours for.
        (True, [("#ee489a", 0.9), ("#111111", 0.1)], "own", "own"),
        (False, [("#0a0a28", 1.0)], "own", "own"),
    ],
)
def test_a_logo_gets_its_own_copy_where_enough_of_it_would_vanish(
    alpha: bool, shares: list[tuple[str, float]], dark: str, light: str
) -> None:
    made = copies(has_alpha=alpha, shares=shares)

    assert (made.on_dark, made.on_light) == (dark, light)


def test_a_note_over_thirty_words_is_refused_rather_than_cut() -> None:
    """Cut at the thirtieth word, a note stops mid-sentence. Refused, it
    goes back to Claude to be written again shorter."""
    thirty = LOGO.model_dump() | {"notes": "so'z " * 30}
    over = LOGO.model_dump() | {"notes": "so'z " * 31}

    assert len(LogoAnalysis.model_validate(thirty).notes.split()) == 30
    with pytest.raises(ValidationError, match="at most 30 words"):
        LogoAnalysis.model_validate(over)


def test_the_word_limit_is_in_the_schema_claude_is_sent() -> None:
    notes = LogoAnalysis.model_json_schema()["properties"]["notes"]

    assert "At most 30 words" in notes["description"]


def test_claudes_colours_are_checked() -> None:
    with pytest.raises(ValidationError):
        LogoAnalysis.model_validate(LOGO.model_dump() | {"suggested_accent": "red"})


def test_the_brand_shows_telegram_first_and_keeps_a_known_font() -> None:
    brand = resolved(
        primary="", accent="", text="", name="", page_name="Bahor gullari",
        tagline="", cta_text="Yozing", telegram="bahor", instagram="bahor_ig",
        cta_phone="", logo="", logo_color="#e11d48", font="nonsense",
    )  # fmt: skip

    assert (brand.name, brand.cta_handle, brand.primary) == (
        "Bahor gullari",
        "@bahor",
        "#e11d48",
    )
    assert brand.font == "modern"


@pytest.mark.parametrize(
    ("typed", "split"),
    [
        ("@bahor_gul", ("bahor_gul", "")),
        ("https://t.me/bahor_gul", ("bahor_gul", "")),
        ("instagram.com/bahor.gul", ("", "bahor.gul")),
        ("https://www.instagram.com/bahor_gul/?igsh=x", ("", "bahor_gul")),
        ("@bahor.gul", ("", "bahor.gul")),
        ("@abc", ("", "abc")),
        ("", ("", "")),
        ("https://example.com/x", ("https://example.com/x", "")),
    ],
)
def test_an_old_either_network_handle_is_split_to_its_network(
    typed: str, split: tuple[str, str]
) -> None:
    assert split_handle(typed) == split


@pytest.mark.parametrize(
    ("ground", "paper"),
    [("#ffffff", True), ("#f4f6f5", True), ("#000000", True), ("#141414", True),
     ("#e11d48", False), ("#808080", False), ("#fff3c4", False)],
)  # fmt: skip
def test_only_a_white_or_black_ground_is_paper_to_take_away(
    ground: str, paper: bool
) -> None:
    assert removable(ground) is paper


# --- Whether the logo already says the name ------------------------------------


@pytest.mark.parametrize(
    ("lettering", "name", "says_it"),
    [
        ("CHILONZOR", "Chilonzor Fitnes", False),
        ("CHILONZOR fitnes markazi", "Chilonzor Fitnes", True),
        ("Bahor kafesi", "Bahor kafesi", True),
        ("BAHOR KAFESI", "Bahor Kafesi", True),
        ("BAHORKAFESI", "Bahor kafesi", True),
        ("Bahor, kafesi!", "Bahor kafesi", True),
        ("OSH MARKAZI", "Osh Markazi", True),
        ("O\u02bbzbek G\u02bballa", "O'zbek G'alla", True),
        ("O\u2018ZBEK G\u2019ALLA", "O\u02bbzbek G\u02bballa", True),
        ("O`zbek", "Ozbek", True),
        ("BAHORGUL", "Bahor", False),
        ("Kafesi Bahor", "Bahor kafesi", False),
        ("Bahor", "Bahor kafesi", False),
        ("", "Bahor", False),
        ("Bahor", "", False),
        ("— · —", "Bahor", False),
    ],
)
def test_the_name_is_left_out_only_when_the_logo_spells_all_of_it(
    lettering: str, name: str, says_it: bool
) -> None:
    from core.montage.logo import names_the_brand

    assert names_the_brand(text_in_logo=lettering, brand_name=name) is says_it
