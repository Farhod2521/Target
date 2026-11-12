"""A campaign Meta no longer lists keeps its name and what it bought.

The mirror forgets such a campaign; its figures stay. Until the goal was
kept on the figure itself, its money was drawn under a bare id and as
leads, whatever it had bought - measured on a production copy,
2026-10-31: 34,330 of 323,374 dollars in ninety days.
"""

from datetime import timedelta

from adskit.dto import MetricsDTO
from adskit.refs import ExternalRef, ProviderName
from metaads import PROVIDER
from metaads.adapter import MetaMetrics
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.metrics import services
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.models import MetricsDaily
from app.modules.metrics.selectors.campaigns import campaign_meta
from app.modules.metrics.selectors.periods import screen_kind
from tests.pg.test_cabinet_flows import _cabinet


def _figure(
    level: str,
    external_id: str,
    *,
    goal: str = "",
    name: str = "",
    spend: int = 500,
    days_ago: int = 1,
) -> MetricsDTO:
    return MetricsDTO(
        ref=ExternalRef(provider=ProviderName(PROVIDER), level=level, id=external_id),  # type: ignore[arg-type]
        day=utcnow().date() - timedelta(days=days_ago),
        campaign_external_id="c_gone",
        adset_external_id=external_id if level == "adset" else "",
        spend_minor=spend,
        currency="USD",
        object_name=name,
        optimization_goal_raw=goal,
    )


def _account(db: Session):  # type: ignore[no-untyped-def]
    owner = User(
        email="gone@example.com", full_name="G", password="!", date_joined=utcnow()
    )
    db.add(owner)
    db.commit()
    account, _page = _cabinet(db, owner)
    account.is_active = account.is_current = True
    db.commit()
    return owner, account


def _stored(db: Session, account, level: MetricLevel, rows: list[MetricsDTO]) -> None:  # type: ignore[no-untyped-def]
    services.store_metrics(db, ad_account=account, rows=rows, now=utcnow(), level=level)


def test_meta_s_goal_travels_with_the_figure() -> None:
    row = MetaMetrics._row(
        {
            "adset_id": "s_1",
            "campaign_id": "c_1",
            "date_start": "2026-11-11",
            "account_currency": "USD",
            "spend": "1.00",
            "optimization_goal": "LINK_CLICKS",
        },
        level="adset",
    )
    bare = MetaMetrics._row(
        {"campaign_id": "c_1", "date_start": "2026-11-11", "account_currency": "USD"},
        level="campaign",
    )

    assert row.optimization_goal_raw == "LINK_CLICKS"
    assert bare.optimization_goal_raw == ""


def test_the_goal_is_stored_and_restated(db: Session) -> None:
    _, account = _account(db)

    _stored(
        db, account, MetricLevel.ADSET, [_figure("adset", "s_1", goal="LINK_CLICKS")]
    )
    _stored(db, account, MetricLevel.ADSET, [_figure("adset", "s_1", goal="REACH")])

    assert db.scalars(select(MetricsDaily.optimization_goal_raw)).all() == ["REACH"]


def test_a_gone_campaign_keeps_its_name_and_is_not_drawn_as_leads(db: Session) -> None:
    owner, account = _account(db)
    _stored(
        db,
        account,
        MetricLevel.CAMPAIGN,
        [
            _figure("campaign", "c_gone", name="Eski nom", days_ago=5),
            _figure("campaign", "c_gone", name="Aksiya trafik", days_ago=1),
        ],
    )
    _stored(
        db,
        account,
        MetricLevel.ADSET,
        [
            _figure("adset", "s_small", goal="LEAD_GENERATION", spend=100),
            _figure("adset", "s_big", goal="LINK_CLICKS", spend=900),
        ],
    )

    by_account = campaign_meta(db, owner=owner, account=account)
    by_ids = campaign_meta(
        db, owner=owner, campaign_ids=frozenset({"c_gone", "c_never"})
    )

    for found in (by_account, by_ids):
        meta = found["c_gone"]
        assert meta.name == "Aksiya trafik"
        # The group that spent most speaks for the campaign.
        assert meta.goal == "LINK_CLICKS"
        assert screen_kind(meta) == "click"
        assert meta.delivery == "unknown"
    assert "c_never" not in by_ids


def test_figures_read_before_the_goal_was_kept_stay_as_they_were(db: Session) -> None:
    owner, account = _account(db)
    _stored(
        db, account, MetricLevel.CAMPAIGN, [_figure("campaign", "c_gone", name="Nom")]
    )
    _stored(db, account, MetricLevel.ADSET, [_figure("adset", "s_1")])

    meta = campaign_meta(db, owner=owner, account=account)["c_gone"]

    assert meta.name == "Nom" and meta.goal == ""
    assert screen_kind(meta) == "lead"
