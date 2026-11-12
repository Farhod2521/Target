"""The link on an advert nobody follows is still about the business.

A lead form, a chat and a call open on the tap; Meta requires a link on
the creative all the same, and refuses one that misleads.
"""

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sitekit import SiteProbe

from app.common.config import settings
from app.modules.ads.services import creation, meta_specs

BUSINESS_ID = uuid.UUID("c81e3b1a-7385-4ebc-90e4-6101ca9c9c58")
PAGE = f"{settings.site_url}/biznes/{BUSINESS_ID}/"


def _built(sends_to: str = "form", *, site_down: bool = False) -> Any:
    return SimpleNamespace(
        needs_link=sends_to == "website",
        opens_profile=sends_to == "profile",
        shows_a_button=sends_to != "nothing",
        link_url="https://shop.example" if sends_to == "website" else "",
        filler_site_down=site_down,
    )


def _link(built: Any, *, website: str = "", answered: str = "") -> str:
    return meta_specs.destination(
        launch=SimpleNamespace(answers={"link_url": answered}),  # type: ignore[arg-type]
        business=SimpleNamespace(id=BUSINESS_ID, website=website),  # type: ignore[arg-type]
        built=built,
        page_id="1149300000",
        instagram_username="lebem.mebel",
    )


@pytest.mark.parametrize("sends_to", ["form", "chat", "phone"])
def test_a_business_with_no_site_links_to_its_own_page(sends_to: str) -> None:
    assert _link(_built(sends_to)) == PAGE


def test_a_site_inside_meta_is_no_site() -> None:
    assert _link(_built(), website="https://instagram.com/lebem.mebel") == PAGE


def test_the_owner_site_stands_while_it_opens() -> None:
    assert _link(_built(), website="https://lebem.uz") == "https://lebem.uz"


def test_a_dead_site_gives_way_to_the_business_page() -> None:
    assert _link(_built(site_down=True), website="https://lebem.uz") == PAGE


def test_a_buttonless_advert_with_a_dead_site_keeps_its_own_address() -> None:
    link = _link(_built("nothing", site_down=True), website="https://lebem.uz")
    assert link == "https://www.instagram.com/lebem.mebel"


def test_the_address_being_bought_is_never_replaced() -> None:
    assert _link(_built("website", site_down=True)) == "https://shop.example"


def _looked(monkeypatch: pytest.MonkeyPatch, outcome: str) -> list[str]:
    seen: list[str] = []

    def look(*, url: str) -> SiteProbe:
        seen.append(url)
        return SiteProbe(url=url, outcome=outcome)  # type: ignore[arg-type]

    monkeypatch.setattr(creation, "look_at_site", look)
    return seen


def _checked(built: Any, *, website: str) -> Any:
    return creation._without_dead_filler(
        launch=SimpleNamespace(id="l1", answers={}),  # type: ignore[arg-type]
        business=SimpleNamespace(id=BUSINESS_ID, website=website),  # type: ignore[arg-type]
        built=built,
    )


def test_the_launch_notices_a_dead_site(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.targeting import BuiltTargeting

    seen = _looked(monkeypatch, "no_such_host")
    built = BuiltTargeting(
        objective="OUTCOME_LEADS",
        optimization_goal="LEAD_GENERATION",
        billing_event="IMPRESSIONS",
        destination_type="ON_AD",
        targeting={},
        daily_budget_minor=1000,
        sends_to="form",
        call_to_action="SIGN_UP",
        currency="USD",
        special_ad_categories=(),
        preset_key="k",
        preset_version="1",
    )

    checked = _checked(built, website="https://lebem.uz")

    assert seen == ["https://lebem.uz"]
    assert checked.filler_site_down is True
    assert _link(checked, website="https://lebem.uz") == PAGE


def test_a_live_site_and_no_site_change_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _looked(monkeypatch, "ok")
    built = _built()

    assert _checked(built, website="https://lebem.uz") is built
    assert _checked(built, website="") is built
    assert seen == ["https://lebem.uz"]
