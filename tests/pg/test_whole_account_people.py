"""A total's people: the account's own count, only where the rows are all of it."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.metrics.models import MetricsDaily, PeopleCount
from app.modules.metrics.ranges import Range
from app.modules.metrics.selectors.expert import whole_account_people
from tests.pg.test_campaigns_v2 import PROVIDER, _figures

WHOLE = 9_000


def _whole(db: Session, campaign: object, today: object) -> None:
    account = campaign.ad_account  # type: ignore[attr-defined]
    db.add(
        PeopleCount(
            owner_id=account.owner_id,
            ad_account_id=account.id,
            provider=PROVIDER,
            external_id=account.external_id,
            level="account",
            since=today - timedelta(days=6),  # type: ignore[operator]
            until=today,
            reach=WHOLE,
            recallers=0,
            unique_link_clicks=700,
            synced_at=utcnow(),
        )
    )
    db.commit()


def _other_campaign(db: Session, campaign: object, today: object, shown: int) -> None:
    account = campaign.ad_account  # type: ignore[attr-defined]
    db.add(
        MetricsDaily(
            owner_id=account.owner_id,
            ad_account_id=account.id,
            provider=PROVIDER,
            external_id="s_2",
            level="adset",
            campaign_external_id="c_2",
            adset_external_id="s_2",
            date=today,
            currency="USD",
            impressions=shown,
            synced_at=utcnow(),
        )
    )
    db.commit()


def _ask(
    db: Session, campaign: object, today: object, level: str = "campaign"
) -> object:
    account = campaign.ad_account  # type: ignore[attr-defined]
    return whole_account_people(
        db,
        owner=account.owner,
        account=account,
        level=level,
        ids=["c_1"] if level == "campaign" else ["s_1"],
        date_range=Range(
            since=today - timedelta(days=6),  # type: ignore[operator]
            until=today,  # type: ignore[arg-type]
            key="7d",
        ),
    )


def test_rows_that_are_the_whole_account_take_its_people(
    client: TestClient, db: Session
) -> None:
    _, campaign, today = _figures(client, db, goal="LINK_CLICKS")
    _whole(db, campaign, today)
    _other_campaign(db, campaign, today, shown=0)

    found = _ask(db, campaign, today)

    assert found is not None
    assert found.reach == WHOLE  # type: ignore[attr-defined]
    assert found.unique_link_clicks == 700  # type: ignore[attr-defined]
    assert _ask(db, campaign, today, level="adset") is not None


def test_a_left_out_campaign_that_was_shown_leaves_the_people_unknown(
    client: TestClient, db: Session
) -> None:
    _, campaign, today = _figures(client, db, goal="LINK_CLICKS")
    _whole(db, campaign, today)
    _other_campaign(db, campaign, today, shown=500)

    assert _ask(db, campaign, today) is None
    assert _ask(db, campaign, today, level="adset") is None


def test_no_count_from_meta_is_no_people(client: TestClient, db: Session) -> None:
    _, campaign, today = _figures(client, db, goal="LINK_CLICKS")

    assert _ask(db, campaign, today) is None
