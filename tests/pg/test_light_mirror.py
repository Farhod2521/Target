"""The half-hourly mirror of a large account asks only about what runs.

Measured on production, 2026-11-12: after the figures were moved to their
own queue the mirror was the largest load left, and on the accounts that
made it most rows sat under campaigns long switched off - read again, page
after page, every half hour. Every campaign is still listed each time, so
one switched on in Ads Manager is seen at once; the night reads everything.
"""

from typing import Any

import pytest
from adskit.dto import AdDTO, AdSetDTO, CampaignDTO
from adskit.refs import ExternalRef
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.ads.services import mirror
from app.modules.integrations.constants import ConnectionStatus
from app.modules.integrations.models import AdAccount
from tests.pg.test_sweep_accounts import _account

META = "meta"


def _ref(level: str, external_id: str) -> ExternalRef:
    return ExternalRef(provider=META, level=level, id=external_id)  # type: ignore[arg-type]


def _campaign(external_id: str, *, on: bool) -> CampaignDTO:
    word = "ACTIVE" if on else "PAUSED"
    return CampaignDTO(
        ref=_ref("campaign", external_id),
        name=external_id,
        status=word,
        effective_status=word,
        delivery="active" if on else "paused",
    )


def _adset(external_id: str, campaign: str) -> AdSetDTO:
    return AdSetDTO(
        ref=_ref("adset", external_id),
        campaign_ref=_ref("campaign", campaign),
        name=external_id,
        status="ACTIVE",
        effective_status="ACTIVE",
        delivery="active",
    )


def _ad(external_id: str, adset: str) -> AdDTO:
    return AdDTO(
        ref=_ref("ad", external_id),
        adset_ref=_ref("adset", adset),
        name=external_id,
        status="ACTIVE",
        effective_status="ACTIVE",
        delivery="active",
    )


class Meta:
    """An account at the provider, counting what it is asked."""

    def __init__(self, *, old_ads: int) -> None:
        self.campaigns = [_campaign("c_live", on=True), _campaign("c_old", on=False)]
        self.adsets = [_adset("s_live", "c_live"), _adset("s_old", "c_old")]
        self.ads = [_ad("a_live", "s_live")] + [
            _ad(f"a_old_{n}", "s_old") for n in range(old_ads)
        ]
        self.asked: list[Any] = []

    def list_campaigns(self, **_: Any) -> list[CampaignDTO]:
        self.asked.append("campaigns")
        return list(self.campaigns)

    def list_adsets(self, **_: Any) -> list[AdSetDTO]:
        self.asked.append("adsets")
        return list(self.adsets)

    def list_ads(self, **_: Any) -> list[AdDTO]:
        self.asked.append("ads")
        return list(self.ads)

    def list_campaign_children(
        self, *, campaigns: list[ExternalRef], token: str
    ) -> tuple[list[AdSetDTO], list[AdDTO]]:
        wanted = {ref.id for ref in campaigns}
        self.asked.append(("children", tuple(sorted(wanted))))
        adsets = [row for row in self.adsets if row.campaign_ref.id in wanted]
        kept = {row.ref.id for row in adsets}
        return adsets, [row for row in self.ads if row.adset_ref.id in kept]


class WholeOnly:
    """A provider with nothing but the three lists, as Google's is."""

    def __init__(self, inner: Meta) -> None:
        self.list_campaigns = inner.list_campaigns
        self.list_adsets = inner.list_adsets
        self.list_ads = inner.list_ads


def _wired(monkeypatch: pytest.MonkeyPatch, port: Any) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        mirror,
        "registry",
        SimpleNamespace(get=lambda _: SimpleNamespace(campaigns=port)),
    )
    monkeypatch.setattr(mirror, "token_for", lambda **_: "token")
    # The account's money is another read, and not this test's.
    monkeypatch.setattr(
        "app.modules.ads.services.stops.read_account_state", lambda _account: None
    )


def _counts(db: Session) -> tuple[int, int, int]:
    def count(model: Any) -> int:
        return int(db.scalar(select(func.count()).select_from(model)) or 0)

    return count(Campaign), count(AdSet), count(Ad)


def _large(db: Session, monkeypatch: pytest.MonkeyPatch) -> tuple[AdAccount, Meta]:
    """An account read whole once: 302 adverts, one of them under what runs."""
    account = _account(db, 70, status=ConnectionStatus.ACTIVE)
    port = Meta(old_ads=301)
    _wired(monkeypatch, port)
    mirror.sync_ad_account(db, ad_account=account, whole=False)
    assert port.asked == ["campaigns", "adsets", "ads"], "never read: read whole"
    assert _counts(db) == (2, 2, 302)
    port.asked.clear()
    return account, port


def test_a_large_account_is_asked_only_about_what_runs(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    account, port = _large(db, monkeypatch)

    summary = mirror.sync_ad_account(db, ad_account=account, whole=False)

    assert port.asked == ["campaigns", ("children", ("c_live",))]
    assert (summary.campaigns, summary.adsets, summary.ads) == (2, 1, 1)
    # What was not asked about is kept, not forgotten.
    assert _counts(db) == (2, 2, 302)


def test_an_advert_gone_under_a_running_campaign_is_forgotten(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    account, port = _large(db, monkeypatch)
    port.ads = [row for row in port.ads if row.ref.id != "a_live"]

    mirror.sync_ad_account(db, ad_account=account, whole=False)

    assert db.scalar(select(Ad.id).where(Ad.external_id == "a_live")) is None
    assert _counts(db) == (2, 2, 301)


def test_a_campaign_switched_on_elsewhere_is_seen_at_the_next_read(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    account, port = _large(db, monkeypatch)
    port.campaigns = [
        _campaign("c_live", on=True),
        _campaign("c_new", on=True),
        _campaign("c_old", on=False),
    ]
    port.adsets.append(_adset("s_new", "c_new"))
    port.ads.append(_ad("a_new", "s_new"))

    mirror.sync_ad_account(db, ad_account=account, whole=False)

    assert port.asked == ["campaigns", ("children", ("c_live", "c_new"))]
    assert db.scalar(select(Ad.delivery).where(Ad.external_id == "a_new")) == "active"


def test_a_campaign_just_stopped_is_asked_about_once_more(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    account, port = _large(db, monkeypatch)
    port.campaigns = [_campaign("c_live", on=False), _campaign("c_old", on=False)]

    mirror.sync_ad_account(db, ad_account=account, whole=False)
    first = list(port.asked)
    port.asked.clear()
    mirror.sync_ad_account(db, ad_account=account, whole=False)

    assert first == ["campaigns", ("children", ("c_live",))]
    # Nothing runs and nothing moved: the list of campaigns is the whole read.
    assert port.asked == ["campaigns"]


def test_a_campaign_gone_from_meta_goes_with_everything_under_it(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    account, port = _large(db, monkeypatch)
    port.campaigns = [_campaign("c_live", on=True)]

    mirror.sync_ad_account(db, ad_account=account, whole=False)

    assert _counts(db) == (1, 1, 1)


def test_the_night_and_a_press_read_everything(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    account, port = _large(db, monkeypatch)

    mirror.sync_ad_account(db, ad_account=account)

    assert port.asked == ["campaigns", "adsets", "ads"]


def test_without_a_whole_read_in_the_day_the_next_read_is_whole(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.common.cache import cache

    account, port = _large(db, monkeypatch)
    cache.delete(mirror.WHOLE_READ_KEY.format(account_id=account.id))

    mirror.sync_ad_account(db, ad_account=account, whole=False)

    assert port.asked == ["campaigns", "adsets", "ads"]


def test_a_small_account_is_read_whole_because_that_is_cheaper(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = _account(db, 71, status=ConnectionStatus.ACTIVE)
    port = Meta(old_ads=3)
    _wired(monkeypatch, port)
    mirror.sync_ad_account(db, ad_account=account, whole=False)
    port.asked.clear()

    mirror.sync_ad_account(db, ad_account=account, whole=False)

    # Two calls bring the rest; two for the one running campaign is no fewer.
    assert port.asked == ["campaigns", "adsets", "ads"]


def test_a_provider_without_the_light_read_is_read_whole(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    account, port = _large(db, monkeypatch)
    _wired(monkeypatch, WholeOnly(port))

    mirror.sync_ad_account(db, ad_account=account, whole=False)

    assert port.asked == ["campaigns", "adsets", "ads"]


def test_a_light_read_meta_refuses_falls_back_to_the_whole_one(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adskit.errors import ProviderError

    account, port = _large(db, monkeypatch)

    def refuse(**_: Any) -> Any:
        port.asked.append("children refused")
        raise ProviderError("the edge would not answer")

    monkeypatch.setattr(port, "list_campaign_children", refuse)

    summary = mirror.sync_ad_account(db, ad_account=account, whole=False)

    assert port.asked == ["campaigns", "children refused", "adsets", "ads"]
    assert (summary.campaigns, summary.adsets, summary.ads) == (2, 2, 302)
