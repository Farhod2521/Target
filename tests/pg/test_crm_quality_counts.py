"""Qualified and sold are the CRM's word, counted by the day the lead came."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.crm.quality import crm_account_ids, crm_is_on
from app.modules.crm.selectors import qualified_count
from app.modules.integrations.models import AdAccount
from app.modules.leads import services as lead_services
from app.modules.leads.models import Lead
from app.modules.leads.selectors import counts_by_ad, counts_by_campaign, sales_by
from tests.pg.test_crm_http import CRM, _auth, _owner, _running


def _stages(board: dict) -> dict[str, dict]:  # type: ignore[type-arg]
    return {c["stage"]["kind"]: c["stage"] for c in board["columns"]}


def _board(client: TestClient, db: Session):  # type: ignore[no-untyped-def]
    owner = _owner(db)
    head = _auth(owner)
    board = _running(client, head)
    stages = _stages(board)
    client.post(
        f"{CRM}/settings/quality",
        headers=head,
        json={"quality": [stages["open"]["id"]]},
    )
    good, junk, sold = [card["id"] for card in board["columns"][0]["cards"]]
    client.post(
        f"{CRM}/cards/{good}/move", headers=head, json={"to": stages["open"]["id"]}
    )
    client.post(
        f"{CRM}/cards/{junk}/move", headers=head, json={"to": stages["junk"]["id"]}
    )
    client.post(f"{CRM}/cards/{sold}/win", headers=head, json={"amount": "150"})
    return owner


def _window():  # type: ignore[no-untyped-def]
    now = utcnow()
    return now - timedelta(days=1), now


def test_qualified_counts_the_crm_and_sold_counts_the_won(
    client: TestClient, db: Session
) -> None:
    owner = _board(client, db)
    since, until = _window()

    assert counts_by_campaign(db, owner=owner, since=since, until=until) == {
        "c_1": (3, 2)
    }
    assert counts_by_ad(db, owner=owner, since=since, until=until) == {"ad_1": (3, 2)}
    assert sales_by(db, owner=owner, level="ad", since=since, until=until) == {
        "ad_1": 1
    }
    assert sales_by(db, owner=owner, level="campaign", since=since, until=until) == {
        "c_1": 1
    }
    assert qualified_count(db, owner=owner, since=since, until=until) == 2


def test_a_manual_verdict_on_the_leads_page_is_not_counted(
    client: TestClient, db: Session
) -> None:
    owner = _board(client, db)
    junk = db.query(Lead).filter_by(owner_id=owner.id, full_name="lid1").one()
    lead_services.mark_outcome(db, user=owner, lead_id=str(junk.id), status="qualified")
    db.commit()
    since, until = _window()

    assert counts_by_campaign(db, owner=owner, since=since, until=until) == {
        "c_1": (3, 2)
    }


def test_a_lead_counts_on_the_day_it_came_not_the_day_it_was_marked(
    client: TestClient, db: Session
) -> None:
    owner = _board(client, db)
    now = utcnow()

    later = counts_by_campaign(
        db, owner=owner, since=now - timedelta(minutes=30), until=now
    )
    assert later == {}
    assert (
        qualified_count(db, owner=owner, since=now - timedelta(minutes=30), until=now)
        == 0
    )


def test_the_crm_is_on_only_for_the_accounts_it_was_switched_on_for(
    client: TestClient, db: Session
) -> None:
    owner = _board(client, db)
    account = db.query(AdAccount).filter_by(owner_id=owner.id).one()

    assert crm_account_ids(db, owner_id=owner.id) == {account.id}
    assert crm_is_on(db, owner_id=owner.id, ad_account_ids=[account.id])
    assert not crm_is_on(db, owner_id=owner.id, ad_account_ids=[])
