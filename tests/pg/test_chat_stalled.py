"""A campaign that says «Ishlayapti» and has shown nothing for hours: the
campaign's look-up names what stands in the way, or says the product cannot
see it - never silence, which the assistant filled with «I do not know»."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.chat.selectors.lookups import answer_lookup
from app.modules.chat.selectors.scope import asked_scopes
from app.modules.metrics.models import MetricsDaily
from core.chat import lookup_arguments as args
from tests.pg.conftest import sign_up
from tests.pg.test_chat import _account, _mirror


def _quiet(client: TestClient, db: Session, *, hours: int) -> Campaign:
    """The mirror's campaign, made ``hours`` ago, with no figures at all."""
    sign_up(client)
    owner, account, page = _account(db)
    _mirror(db, owner, account, page)
    db.execute(delete(MetricsDaily).where(MetricsDaily.owner_id == owner.id))
    campaign = db.scalar(select(Campaign).where(Campaign.owner_id == owner.id))
    assert campaign is not None
    campaign.created_time = utcnow() - timedelta(hours=hours)
    db.commit()
    return campaign


def _details(db: Session, campaign: Campaign) -> str:
    scope, counted = asked_scopes(db, owner=campaign.owner)
    return answer_lookup(
        db,
        owner=campaign.owner,
        name="campaign_details",
        arguments=args.CampaignLookup(campaign_id=campaign.external_id),
        scope=scope,
        now=utcnow(),
        counted=counted,
    )


def test_a_campaign_with_figures_has_no_such_section(
    client: TestClient, db: Session
) -> None:
    sign_up(client)
    owner, account, page = _account(db)
    _mirror(db, owner, account, page)
    db.commit()
    campaign = db.scalar(select(Campaign).where(Campaign.owner_id == owner.id))
    assert campaign is not None
    assert "Shown 0 times" not in _details(db, campaign)


def test_a_new_campaign_is_left_to_start(client: TestClient, db: Session) -> None:
    campaign = _quiet(client, db, hours=2)
    assert "Shown 0 times" not in _details(db, campaign)


def test_nothing_seen_in_the_way_says_so_and_asks_for_a_person(
    client: TestClient, db: Session
) -> None:
    campaign = _quiet(client, db, hours=94)
    text = _details(db, campaign)
    assert "## Shown 0 times although it runs - made 94 hours ago" in text
    assert "The product cannot see the cause" in text
    assert "prepare a request for Support" in text


def test_a_long_review_and_a_late_start_are_named(
    client: TestClient, db: Session
) -> None:
    campaign = _quiet(client, db, hours=50)
    ad = db.scalar(select(Ad).where(Ad.owner_id == campaign.owner_id))
    group = db.scalar(select(AdSet).where(AdSet.owner_id == campaign.owner_id))
    assert ad is not None and group is not None
    ad.delivery = "pending"
    ad.created_at = utcnow() - timedelta(hours=40)
    group.start_time = utcnow() + timedelta(days=1)
    db.commit()
    text = _details(db, campaign)
    assert "1 of 1 adverts wait for Meta's review for more than a day" in text
    assert "is scheduled to start" in text
    assert "no advert in it is running" in text
    assert "cannot see the cause" not in text
