"""What a launch is called in Ads Manager: the campaign, the ad set and the ad."""

from datetime import UTC, datetime
from typing import Any

from app.modules.accounts.models import User
from app.modules.ads import naming
from app.modules.ads.constants import BUDGET_LEVEL, DraftSection
from app.modules.ads.models import CampaignLaunch
from app.modules.businesses.models import Business
from app.modules.integrations.models import PageAccount

AT = datetime(2026, 11, 17, 12, 18, tzinfo=UTC)


def _launch(
    *,
    language: str = "uz",
    goal: str = "calls",
    targeting: dict[str, Any] | None = None,
    geo: dict[str, Any] | None = None,
    answers: dict[str, Any] | None = None,
) -> CampaignLaunch:
    audience = {"geo": geo} if geo is not None else {}
    return CampaignLaunch(
        answers={"goal": goal, **(answers or {})},
        targeting=targeting or {},
        draft={DraftSection.AUDIENCE: {"ai": None, "chosen": audience}},
        owner=User(language=language),
        page=PageAccount(name="Baraka Market"),
        created_at=AT,
    )


def _business() -> Business:
    return Business(name="Baraka", timezone="Asia/Tashkent")


def test_the_campaign_is_page_goal_and_day() -> None:
    name = naming.goal_campaign_name(
        launch=_launch(), business=_business(), page_name="Baraka Market", at=AT
    )
    assert name == "Baraka Market - Qo'ng'iroq - 17.11.2026"


def test_the_goal_follows_the_owners_language_and_the_level_is_left_out() -> None:
    launch = _launch(language="en", answers={BUDGET_LEVEL: "campaign"})
    name = naming.goal_campaign_name(
        launch=launch, business=_business(), page_name="Baraka Market", at=AT
    )
    assert name == "Baraka Market - Calls - 17.11.2026"
    ru = naming.campaign_name(launch=_launch(language="ru"), business=_business())
    assert ru == "Baraka Market - Звонки - 17.11.2026"


def test_a_long_page_name_is_cut_and_the_stamp_kept() -> None:
    name = naming.goal_campaign_name(
        launch=_launch(), business=_business(), page_name="X" * 300, at=AT
    )
    assert len(name) <= naming.MAX_NAME
    assert name.endswith("… - Qo'ng'iroq - 17.11.2026")


def test_nothing_chosen_is_everyone() -> None:
    assert _adset({}) == "Hamma"


def test_only_what_was_chosen_shows() -> None:
    spec = {
        "age_min": 25,
        "age_max": 45,
        "genders": [2],
        "flexible_spec": [{"interests": [{"id": "1", "name": "Moda"}]}],
        "targeting_automation": {"advantage_audience": 0},
    }
    places = [
        {"key": str(n), "name": name, "kind": "city"}
        for n, name in enumerate(["Toshkent", "Samarqand", "Buxoro", "Xiva", "Nukus"])
    ]
    geo = {"mode": "places", "places": places, "origin": "chosen"}
    assert _adset(spec, geo=geo) == "25-45 - Ayol - Toshkent, Samarqand +3 - Qiziqish"


def test_advantage_and_the_owners_own_lists() -> None:
    spec = {
        "age_min": 18,
        "genders": [1, 2],
        "custom_audiences": [{"id": "111"}, {"id": "222"}],
        "targeting_automation": {"advantage_audience": 1},
    }
    assert _adset(spec, lookalikes={"111"}) == "Hamma - O'xshash - O'z - Adv+"
    assert _adset(spec, lookalikes={"111", "222"}) == "Hamma - O'xshash - Adv+"


def test_the_country_nobody_picked_is_left_out() -> None:
    geo = {
        "mode": "country",
        "places": [{"key": "UZ", "name": "Uzbekistan", "kind": "country"}],
        "origin": "derived",
    }
    assert _adset({"genders": [1]}, geo=geo) == "Erkak"
    assert _adset({"genders": [1]}, geo={**geo, "origin": "chosen"}) == (
        "Erkak - Uzbekistan"
    )


def test_a_second_group_is_numbered_and_the_words_follow_the_language() -> None:
    launch = _launch(language="ru", targeting={"genders": [2]})
    name = naming.adset_name(launch=launch, business=_business(), position=1, of=2)
    assert name == "Жен #2"


def test_the_ad_is_its_number() -> None:
    assert naming.ad_name(launch=_launch(), business=_business(), position=2) == "#3"


def test_a_row_drops_the_stamp() -> None:
    assert naming.short_name("Baraka - Qo'ng'iroq - 17.11.2026") == (
        "Baraka - Qo'ng'iroq"
    )
    assert naming.short_name("Baraka - Qo'ng'iroq - ABO - 17.11.2026 - 17:18") == (
        "Baraka - Qo'ng'iroq - ABO"
    )


def _adset(
    spec: dict[str, Any],
    *,
    geo: dict[str, Any] | None = None,
    lookalikes: set[str] | None = None,
) -> str:
    launch = _launch(targeting=spec, geo=geo)
    return naming.adset_name(
        launch=launch, business=_business(), lookalikes=lookalikes or set()
    )
