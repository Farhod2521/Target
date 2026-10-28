"""Deletes on Django's own foreign keys: NO ACTION, checked at commit.

The rows pointing at a deleted row are nulled or deleted the way Django's
``on_delete`` did, or the delete is refused with nothing changed.
"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.common.deletion import ProtectedRows, delete_rows
from app.modules.accounts.models import User
from app.modules.ads.models import CampaignLaunch, LaunchCreative, MediaAsset
from app.modules.ads.services import media
from app.modules.crm.backfill import assign_pairs
from app.modules.crm.models import CrmActivity, CrmCard, CrmMember, CrmStage
from app.modules.leads.models import Lead, RawLeadEvent
from app.modules.leads.services import purge_raw_events
from tests.pg.test_crm_pairs import _auth, _world


def _pair_of(db: Session, member: CrmMember) -> str:
    from app.modules.integrations.models import AdAccount, PageAccount

    page = db.get(PageAccount, member.page_id)
    account = db.get(AdAccount, member.ad_account_id)
    return f"{page.external_id}:{account.external_id}"


def test_a_manager_who_worked_cards_is_removed(client: TestClient, db: Session) -> None:
    world = _world(db)
    assign_pairs(db)
    manager = world["managers"][1]
    card = world["cards"]["second"]
    db.add(
        CrmActivity(
            owner_id=world["owner"].id,
            card_id=card.id,
            actor_id=manager.id,
            kind="note",
        )
    )
    db.commit()
    member = db.scalar(select(CrmMember).where(CrmMember.user_id == manager.id))
    manager_id, member_id = manager.id, member.id

    removed = client.delete(
        f"/api/v1/crm/settings/members/{member_id}",
        params={"pair": _pair_of(db, member)},
        headers=_auth(world["owner"]),
    )

    assert removed.status_code == 200, removed.text
    db.expire_all()
    assert db.get(User, manager_id) is None
    assert db.get(CrmMember, member_id) is None
    assert db.get(CrmCard, card.id).assignee_id is None
    actors = db.scalars(select(CrmActivity.actor_id).where(CrmActivity.kind == "note"))
    assert list(actors) == [None]


def test_a_lost_reason_in_use_is_deleted(client: TestClient, db: Session) -> None:
    world = _world(db)
    assign_pairs(db)
    db.commit()
    card = world["cards"]["second"]
    db.refresh(card)
    reason_id = card.lost_reason_id

    deleted = client.delete(
        f"/api/v1/crm/settings/reasons/{reason_id}",
        params={"pair": "page_2:act_1"},
        headers=_auth(world["owner"]),
    )

    assert deleted.status_code == 200, deleted.text
    db.expire_all()
    kept = db.get(CrmCard, card.id)
    assert kept.lost_reason_id is None
    assert kept.lost_reason_name == "Qimmat"


def test_a_picture_gone_from_meta_leaves_the_draft_without_it(db: Session) -> None:
    world = _world(db)
    owner, account = world["owner"], world["account"]
    old = MediaAsset(
        owner_id=owner.id,
        ad_account_id=account.id,
        provider=PROVIDER,
        kind="image",
        external_id="img_gone",
        created_at=utcnow() - timedelta(days=1),
    )
    db.add(old)
    db.flush()
    launch = db.scalar(select(CampaignLaunch).limit(1))
    creative = LaunchCreative(
        owner_id=owner.id, launch_id=launch.id, media_asset_id=old.id
    )
    db.add(creative)
    db.commit()
    old_id, creative_id = old.id, creative.id

    media._store(
        db,
        owner=owner,
        ad_account=account,
        page=None,
        kinds=("image",),
        assets=[],
        read_at=utcnow(),
    )

    db.expire_all()
    assert db.get(MediaAsset, old_id) is None
    assert db.get(LaunchCreative, creative_id).media_asset_id is None


def test_a_bad_raw_event_is_purged_from_under_its_lead(db: Session) -> None:
    world = _world(db)
    event = RawLeadEvent(
        provider=PROVIDER,
        payload={},
        signature_valid=False,
        created_at=utcnow() - timedelta(days=60),
    )
    db.add(event)
    db.flush()
    lead = db.scalar(select(Lead).where(Lead.owner_id == world["owner"].id).limit(1))
    lead.raw_event_id = event.id
    db.commit()
    event_id, lead_id = event.id, lead.id

    assert purge_raw_events(db, before=utcnow() - timedelta(days=30)) == 1

    db.expire_all()
    assert db.get(RawLeadEvent, event_id) is None
    assert db.get(Lead, lead_id).raw_event_id is None


def test_a_protected_row_refuses_and_changes_nothing(db: Session) -> None:
    world = _world(db)
    stage = world["stages"]["open"]

    with pytest.raises(ProtectedRows):
        delete_rows(db, CrmStage.__table__, CrmStage.id == stage.id)
    db.commit()

    assert db.get(CrmStage, stage.id) is not None
