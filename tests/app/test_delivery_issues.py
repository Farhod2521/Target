"""An advert Meta will not run: the answer names where the fault really is."""

from types import SimpleNamespace

import pytest
from adskit.errors import (
    AccountNotWritable,
    AdvertiserRoleMissing,
    MediaTooLarge,
    NotFound,
    PageAccessDenied,
    PermissionDenied,
)
from metaads.adapter import translate_error
from metaads.errors import MetaAPIError, MetaAuthError

from app.modules.ads.constants import META_SIDE_FAILURES, Delivery
from app.modules.ads.contract.launch.failures import failure
from app.modules.ads.selectors import rejections
from app.modules.ads.selectors.rejections import (
    SWAP_LABEL,
    known_trouble,
    rejection_of,
    review_key,
)
from app.modules.ads.services.creation import FAILURE_CODES
from app.modules.ads.services.manage import provider_failure
from app.modules.ads.troubles import first_known
from app.modules.chat.services import refused as refused_module
from core.chat.preparations import TROUBLE_WORDS


def _ad(*, codes=(), feedback=None, summary="", kind="link"):  # type: ignore[no-untyped-def]
    issues = [{"code": code, "summary": summary, "message": summary} for code in codes]
    return SimpleNamespace(
        delivery=Delivery.REJECTED,
        review_feedback=feedback,
        issues=issues,
        issue_codes=list(codes),
        issue_summary=summary,
        adset=SimpleNamespace(
            issue_summary="",
            issue_codes=[],
            campaign_id="11111111-1111-1111-1111-111111111111",
            campaign=SimpleNamespace(ad_account=SimpleNamespace(external_id="act_1")),
        ),
        provider="meta",
        external_id="123",
        content=SimpleNamespace(kind=kind),
    )


@pytest.mark.parametrize(
    ("code", "title", "button"),
    [
        ("2490471", "Reklama akkaunti yopilmoqda", "Account Quality'ni ochish"),
        ("1359208", "Auditoriya endi mavjud emas", "Auditoriyani tahrirlash"),
        (
            "1815199",
            "Reklama akkauntida Instagram'ga kirish yo'q",
            "Ads Manager'ni ochish",
        ),
        ("3253001", "Sahifaning reklama limiti tugagan", "Reklamalarni ochish"),
        (
            "1359008",
            "Reklama akkauntida to'lanmagan qarz bor",
            "To'lov sahifasini ochish",
        ),
    ],
)
def test_a_fault_outside_the_advert_never_offers_a_new_advert(
    code, title, button
) -> None:  # type: ignore[no-untyped-def]
    found = rejection_of(_ad(codes=[code], summary="Meta's words"))

    assert found["title"] == title
    assert found["fix"]["label"] == button
    assert found["fix"]["label"] != SWAP_LABEL
    assert found["key"] is None and found["explaining"] is False
    assert found["providerWords"] == "Meta's words — Meta's words"


def test_waiting_for_an_admin_is_not_called_a_refusal() -> None:
    found = rejection_of(_ad(codes=["2446984"], summary="Do nothing"))

    assert "rad et" not in found["title"]
    assert found["cause"].startswith("Bu rad etish emas")


def test_a_written_trouble_costs_no_question() -> None:
    assert review_key(_ad(codes=["3253001"], summary="Limit")) == ""


def test_a_policy_meta_named_stays_the_reviews() -> None:
    ad = _ad(
        codes=["2490468"],
        feedback={"overall": {"Lead Ads": "Not allowed."}},
        summary="Rejected",
    )

    assert known_trouble(ad) is None
    found = rejection_of(ad)
    assert found["title"] == rejections.TITLE
    assert found["key"] and found["explaining"] is True
    assert found["fix"]["label"] == SWAP_LABEL


def test_an_unlisted_issue_is_not_called_refused_and_gets_an_answer() -> None:
    found = rejection_of(_ad(codes=["999"], summary="Something new"))

    assert found["title"] == rejections.NOT_RUNNING
    assert found["key"] and found["explaining"] is True
    assert found["fix"] is None
    assert not any("qayta ko'rib chiqadi" in step for step in found["steps"])


def test_a_refusal_with_nothing_said_points_at_meta() -> None:
    found = rejection_of(_ad())

    assert found["key"] is None
    assert found["fix"]["label"] == "Ads Manager'ni ochish"


def test_a_post_cannot_be_swapped_even_for_a_written_trouble() -> None:
    found = rejection_of(_ad(codes=["2875006"], summary="Narrow", kind="existing_post"))

    assert found["fix"] is None
    assert any("yangi reklama" in step for step in found["steps"])


@pytest.mark.parametrize(
    ("error", "subcode", "cls", "launch", "change"),
    [
        (
            MetaAuthError("x", code=200, subcode=2490592),
            2490592,
            AccountNotWritable,
            "account_disabled",
            "account_blocked",
        ),
        (
            MetaAuthError("x", code=200, subcode=4841021),
            4841021,
            AccountNotWritable,
            "account_disabled",
            "account_blocked",
        ),
        (
            MetaAuthError("x", code=200, subcode=2490585),
            2490585,
            AdvertiserRoleMissing,
            "account_role",
            "account_role",
        ),
        (
            MetaAPIError("x", code=100, subcode=1487202),
            1487202,
            PageAccessDenied,
            "page_role",
            "page_role",
        ),
    ],
)
def test_meta_codes_say_whose_fault_it_is(error, subcode, cls, launch, change) -> None:  # type: ignore[no-untyped-def]
    found = translate_error(error)

    assert type(found) is cls
    assert found.key.endswith(str(subcode))
    assert FAILURE_CODES[cls.__name__] == launch
    assert provider_failure(found, None) == change


def test_they_stay_permission_refusals_for_the_readers_that_only_stop() -> None:
    assert issubclass(AccountNotWritable, PermissionDenied)
    assert issubclass(AdvertiserRoleMissing, PermissionDenied)


def test_a_role_refusal_on_a_launch_does_not_say_reconnect_alone() -> None:
    found = failure(
        {"error_code": "account_role"}, ads_total=1, page="", budget="", minimum=""
    )

    assert found["code"] == "account_role"
    assert "administrator" in found["refusal"]["steps"][0]


def _press(monkeypatch, exc, operation, account):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(refused_module, "ready_answer", lambda *a, **k: None)
    monkeypatch.setattr(refused_module, "_note", lambda **k: None)
    owner = SimpleNamespace(language="uz", id="x")
    return refused_module.refusal_for(
        None, owner=owner, exc=exc, operation=operation, account=account
    )


def test_a_blocked_account_is_named_on_a_press_too(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    account = SimpleNamespace(external_id="1", may_advertise=False, standing="")

    found = _press(monkeypatch, PermissionDenied("no", code="200"), "media", account)

    assert "ruxsat" in found.cause and "profil" not in found.cause


def test_a_file_too_large_says_so(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    found = _press(monkeypatch, MediaTooLarge("big", code="413"), "media", None)

    assert "katta" in found.cause


def test_a_missing_audience_is_not_called_an_advert(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    found = _press(monkeypatch, NotFound("no", code="803"), "audience", None)

    assert "auditoriya" in found.cause
    assert "reklama topilmadi" not in found.cause.lower()


def test_the_inbox_and_the_agent_read_the_same_sentence() -> None:
    found = first_known(("2490471",))

    assert found is not None
    assert found.headline == "Reklama akkaunti yopilmoqda"
    assert first_known(("2460004",)) is not None


def test_a_silent_refusal_elsewhere_sends_nobody_to_ads_manager() -> None:
    ad = _ad()
    ad.provider = "google"

    assert rejection_of(ad)["fix"] is None


def test_a_role_refusal_says_fix_it_first_and_the_chat_knows_it() -> None:
    assert "account_role" in META_SIDE_FAILURES
    assert "account_role" in TROUBLE_WORDS
