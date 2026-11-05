"""The nightly check: our stored sums against Meta's own account total."""

from datetime import timedelta
from typing import Any

import pytest
from adskit import MinorUnits
from adskit.dto import MetricsDTO
from adskit.refs import ExternalRef
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.metrics import check as report
from app.modules.metrics.models import MetricsCheck, MetricsDaily
from app.modules.metrics.services import check, sync
from tests.pg.test_campaigns_v2 import (
    IMPRESSIONS,
    LINK_CLICKS,
    PROVIDER,
    SPEND,
    _figures,
)


def _yesterday_stored(db: Session) -> Any:
    """Moves the fixture's day back to yesterday, a day the check reads."""
    for row in db.scalars(select(MetricsDaily)):
        row.date = row.date - timedelta(days=1)
    db.commit()


def _meta(
    monkeypatch: pytest.MonkeyPatch, *, day: Any, spend: int, shown: int
) -> list[str]:
    asked: list[str] = []

    def read(_db: Session, account: Any, *, since: Any, until: Any, level: str) -> Any:
        asked.append(level)
        return [
            MetricsDTO(
                ref=ExternalRef(provider=PROVIDER, level="account", id="1"),
                day=day,
                spend_minor=MinorUnits(spend),
                currency="USD",
                impressions=shown,
                clicks=7000,
                inline_link_clicks=LINK_CLICKS,
            )
        ]

    monkeypatch.setattr(sync, "read_level", read)
    return asked


def test_a_day_that_matches_meta_is_kept_as_matching(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, campaign, today = _figures(client, db, goal="LINK_CLICKS")
    _yesterday_stored(db)
    asked = _meta(
        monkeypatch, day=today - timedelta(days=1), spend=SPEND, shown=IMPRESSIONS
    )

    found = check.check_account(db, ad_account=campaign.ad_account, today=today)

    assert asked == ["account"]
    assert found.days == 1
    assert found.differing == ()
    (kept,) = db.scalars(select(MetricsCheck))
    assert kept.differs is False
    assert kept.ours["spend_minor"] == SPEND
    assert kept.theirs["impressions"] == IMPRESSIONS


def test_a_day_apart_from_meta_is_marked_and_reported(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, campaign, today = _figures(client, db, goal="LINK_CLICKS")
    _yesterday_stored(db)
    yesterday = today - timedelta(days=1)
    _meta(monkeypatch, day=yesterday, spend=SPEND * 2, shown=IMPRESSIONS)

    found = check.check_account(db, ad_account=campaign.ad_account, today=today)

    assert found.differing == (yesterday,)
    lines = report.report(db, days=7)
    assert "1 tasi farq qiladi" in lines[0]
    assert f"Sarf (minor) biz {SPEND} / Meta {SPEND * 2}" in lines[1]
    assert "Ko'rsatildi" not in lines[1]


def test_a_day_meta_has_and_we_do_not_is_apart(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, campaign, today = _figures(client, db, goal="LINK_CLICKS")
    two_days_ago = today - timedelta(days=2)
    _meta(monkeypatch, day=two_days_ago, spend=SPEND, shown=IMPRESSIONS)

    found = check.check_account(db, ad_account=campaign.ad_account, today=today)

    # Today's row is not a closed day and is not read.
    assert found.differing == (two_days_ago,)
    assert found.days == 1


def test_the_night_read_runs_the_check_and_survives_its_refusal(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.ads.exceptions import SyncFailed

    _, campaign, today = _figures(client, db, goal="LINK_CLICKS")

    def refuse(*_: Any, **__: Any) -> Any:
        raise SyncFailed(cause="provider_error")

    monkeypatch.setattr(check, "check_account", refuse)

    sync._check(db, ad_account=campaign.ad_account, today=today)

    assert db.scalar(select(MetricsCheck)) is None


def test_a_rounding_gap_is_not_apart() -> None:
    assert not check.apart(10_001, 10_000)
    assert not check.apart(100_900, 100_000)
    assert check.apart(101_100, 100_000)
    assert check.apart(3, 0)
    assert not check.apart(1, 0)


def test_only_meta_accounts_are_checked(client: TestClient, db: Session) -> None:
    _, campaign, today = _figures(client, db, goal="LINK_CLICKS")
    account = campaign.ad_account
    account.provider = "google"

    assert check.check_account(db, ad_account=account, today=today).days == 0
    db.rollback()
