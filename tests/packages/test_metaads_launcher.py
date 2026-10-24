"""The creation sequence as the domain sees it.

The launcher is the boundary: Meta's ids go in and ``ExternalRef`` comes
out, Meta's error codes go in and ``adskit`` exceptions come out. What is
tested here is the boundary itself, not the calls underneath - those have
their own file - because the boundary is what a second provider would have
to reproduce and what the launch service is written against.
"""

from typing import Any

import httpx
import pytest
from adskit.errors import AuthFailed, InvalidRequest, RateLimited
from adskit.refs import ExternalRef
from metaads import PROVIDER
from metaads.assets import MetaAssets
from metaads.launcher import MetaLauncher
from metaads.specs import (
    STATUS_ACTIVE,
    AdSetSpec,
    CampaignSpec,
    CreativeSpec,
    LeadFormSpec,
)

ACCOUNT = ExternalRef(provider=PROVIDER, level="account", id="act_1")
PAGE = ExternalRef(provider=PROVIDER, level="page", id="99")

FORM = LeadFormSpec(name="Lidlar", privacy_policy_url="https://x/privacy/")
CAMPAIGN = CampaignSpec(name="Osh markazi", objective="OUTCOME_LEADS")
ADSET = AdSetSpec(
    name="Toshkent",
    campaign_id="120210",
    daily_budget_minor=50_000,
    optimization_goal="LEAD_GENERATION",
    billing_event="IMPRESSIONS",
    targeting={"age_min": 25, "instagram_positions": ["explore_home"]},
)
CREATIVE = CreativeSpec(
    name="c",
    page_id="99",
    message="Salom",
    image_hash="abc",
    link_url="https://targetolog.ai/",
)


@pytest.fixture
def launcher() -> MetaLauncher:
    return MetaLauncher()


@pytest.fixture
def assets() -> MetaAssets:
    return MetaAssets()


def answering(
    monkeypatch: pytest.MonkeyPatch,
    *,
    post: dict[str, Any] | None = None,
    get: dict[str, Any] | None = None,
    status: int = 200,
) -> list[httpx.Request]:
    """Point every client the launcher opens at one mock transport."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(status, json=get or {})
        return httpx.Response(status, json=post or {"id": "120210"})

    original = httpx.Client.__init__

    def patched(self: httpx.Client, **kwargs: Any) -> None:
        original(self, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", patched)
    return seen


# --- What comes out ------------------------------------------------------
def test_a_created_campaign_comes_back_as_a_ref(
    launcher: MetaLauncher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not a bare string. An id alone cannot say which provider issued it
    or what level it sits at, and the rollback needs both."""
    answering(monkeypatch)

    result = launcher.create_campaign(
        account=ACCOUNT, spec=CAMPAIGN, token="t", dry_run=False
    )

    assert result.ref == ExternalRef(provider=PROVIDER, level="campaign", id="120210")
    assert result.ok


def test_every_step_is_named_at_its_own_level(
    launcher: MetaLauncher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The level is what the rollback walks backwards."""
    answering(monkeypatch, get={"targeting": {}})

    levels = [
        launcher.create_form(page=PAGE, spec=FORM, page_token="p", dry_run=False),
        launcher.create_campaign(
            account=ACCOUNT, spec=CAMPAIGN, token="t", dry_run=False
        ),
        launcher.create_adset(account=ACCOUNT, spec=ADSET, token="t", dry_run=False),
        launcher.create_creative(
            account=ACCOUNT, spec=CREATIVE, token="t", dry_run=False
        ),
    ]

    assert [result.ref.level for result in levels] == [
        "form",
        "campaign",
        "adset",
        "creative",
    ]


def test_an_ad_is_made_switched_off_unless_told_otherwise(
    launcher: MetaLauncher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A launch switches its whole tree on at the end."""
    seen = answering(monkeypatch)
    adset = ExternalRef(provider=PROVIDER, level="adset", id="1")
    creative = ExternalRef(provider=PROVIDER, level="creative", id="2")

    result = launcher.create_ad(
        account=ACCOUNT,
        adset=adset,
        creative=creative,
        name="a",
        token="t",
        dry_run=False,
    )

    assert b"status=PAUSED" in seen[0].content
    assert result.applied["status"] == "PAUSED"


def test_a_replacing_ad_can_be_made_running(
    launcher: MetaLauncher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Made off, it leaves the group dark once the old one is switched off."""
    seen = answering(monkeypatch)
    adset = ExternalRef(provider=PROVIDER, level="adset", id="1")
    creative = ExternalRef(provider=PROVIDER, level="creative", id="2")

    launcher.create_ad(
        account=ACCOUNT,
        adset=adset,
        creative=creative,
        name="a",
        token="t",
        dry_run=False,
        status=STATUS_ACTIVE,
    )

    assert b"status=ACTIVE" in seen[0].content


def test_what_meta_dropped_survives_the_boundary(
    launcher: MetaLauncher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole reason ActionResult has the field."""
    answering(monkeypatch, get={"targeting": {"age_min": 25}})

    result = launcher.create_adset(
        account=ACCOUNT, spec=ADSET, token="t", dry_run=False
    )

    assert result.dropped == {"instagram_positions": ["explore_home"]}


def test_the_targeting_meta_holds_survives_the_boundary(
    launcher: MetaLauncher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What Meta added is not a loss, so it travels beside ``dropped``."""
    answering(monkeypatch, get={"targeting": {"age_min": 25, "age_max": 65}})

    result = launcher.create_adset(
        account=ACCOUNT, spec=ADSET, token="t", dry_run=False
    )

    assert result.raw_response["targeting"] == {"age_min": 25, "age_max": 65}


def test_a_dry_run_says_so_in_its_result(
    launcher: MetaLauncher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the audit log reads to tell a rehearsal from a campaign."""
    seen = answering(monkeypatch)

    result = launcher.create_campaign(account=ACCOUNT, spec=CAMPAIGN, token="t")

    assert result.dry_run
    assert seen == []


# --- Meta's vocabulary stops here ----------------------------------------
def test_an_expired_token_arrives_as_a_domain_failure(
    launcher: MetaLauncher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A service catching code 190 is a service that breaks the day a
    second provider is added."""
    answering(
        monkeypatch, post={"error": {"code": 190, "message": "expired"}}, status=400
    )

    with pytest.raises(AuthFailed):
        launcher.create_campaign(
            account=ACCOUNT, spec=CAMPAIGN, token="t", dry_run=False
        )


def test_a_rate_limit_arrives_as_one_the_task_can_read(
    launcher: MetaLauncher, monkeypatch: pytest.MonkeyPatch
) -> None:
    answering(
        monkeypatch, post={"error": {"code": 4, "message": "slow down"}}, status=400
    )

    with pytest.raises(RateLimited):
        launcher.create_campaign(
            account=ACCOUNT, spec=CAMPAIGN, token="t", dry_run=False
        )


def test_a_refused_creative_is_an_invalid_request(
    launcher: MetaLauncher, monkeypatch: pytest.MonkeyPatch
) -> None:
    answering(
        monkeypatch, post={"error": {"code": 1487390, "message": "bad"}}, status=400
    )

    with pytest.raises(InvalidRequest):
        launcher.create_creative(
            account=ACCOUNT, spec=CREATIVE, token="t", dry_run=False
        )


# --- Video, which is not usable when it arrives --------------------------
def test_a_video_still_processing_is_not_ready(
    assets: MetaAssets, monkeypatch: pytest.MonkeyPatch
) -> None:
    answering(monkeypatch, get={"status": {"video_status": "processing"}})

    assert not assets.video_ready(video_id="777", token="t")


def test_a_video_meta_refused_raises_rather_than_waiting_forever(
    assets: MetaAssets, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Terminal. Polling it until a timeout would tell the owner their
    campaign is still being prepared for a quarter of an hour."""
    answering(monkeypatch, get={"status": {"video_status": "error"}})

    with pytest.raises(InvalidRequest):
        assets.video_ready(video_id="777", token="t")


def test_a_status_meta_did_not_send_means_keep_waiting(
    assets: MetaAssets, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Treating an unknown status as ready builds a creative Meta then
    rejects several calls later."""
    answering(monkeypatch, get={})

    assert not assets.video_ready(video_id="777", token="t")


# --- Undoing it ----------------------------------------------------------
def test_a_rollback_deletes_the_object(
    launcher: MetaLauncher, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = answering(monkeypatch, post={"success": True})
    ref = ExternalRef(provider=PROVIDER, level="campaign", id="120210")

    assert launcher.remove(ref=ref, token="t", dry_run=False)
    assert seen[0].method == "DELETE"


def test_a_rollback_of_a_rehearsal_sends_nothing(
    launcher: MetaLauncher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refs of a dry run name objects that were never created, and a
    rollback walking them must not be where one first reaches Meta."""
    seen = answering(monkeypatch)
    ref = ExternalRef(provider=PROVIDER, level="campaign", id="dryrun-campaign")

    assert launcher.remove(ref=ref, token="t", dry_run=False)
    assert seen == []
