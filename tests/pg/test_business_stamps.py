"""The business kept level without anybody asking, against PostgreSQL: a
commit that stored a pair or a page's profile links it, and a row made
afterwards carries its pair's business from the flush that writes it."""

import pytest
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.modules.ads.models import CampaignLaunch
from app.modules.businesses.models import BusinessLink
from app.modules.businesses.services import links
from app.modules.chat.models import ChatSession
from app.modules.crm.models import CrmCard, CrmStage
from app.modules.integrations.models import PagePair
from app.modules.leads.models import Lead, LeadForm
from tests.pg.test_business_links import World, _rows


def test_a_commit_that_stored_a_pair_links_it(db: Session) -> None:
    world = World(db)
    page = world.page("p1")
    world.pair(page, world.account("act_1"))
    assert world.links() == []

    db.commit()

    (link,) = world.open_links()
    assert link.external_id == "p1:act_1"


def test_a_rolled_back_pair_links_nothing_later(db: Session) -> None:
    world = World(db)
    page, account = world.page("p1"), world.account("act_1")
    db.commit()
    world.pair(page, account)
    db.rollback()

    db.add(ChatSession(owner_id=world.owner.id))
    db.commit()

    assert world.links() == []
    assert db.scalars(select(PagePair)).all() == []


def test_a_profile_saved_after_the_pair_links_it_and_fills_the_rows(
    db: Session,
) -> None:
    world = World(db)
    page, account = world.page("p1", profile=False), world.account("act_1")
    world.pair(page, account)
    rows = _rows(world, page, account)
    db.commit()
    assert world.links() == []
    assert rows["card"].business_id is None

    profile = world.profile(page)
    db.commit()

    (link,) = world.open_links()
    assert link.business_id == profile.id
    for name, row in rows.items():
        db.refresh(row)
        assert row.business_id == profile.id, name


def test_a_changed_and_a_removed_pair_are_followed_at_commit(db: Session) -> None:
    world = World(db)
    page = world.page("p1")
    old, new = world.account("act_1"), world.account("act_2")
    pair = world.pair(page, old)
    db.commit()
    business = world.open_links()[0].business_id

    pair.ad_account_id = new.id
    db.commit()
    (link,) = world.open_links()
    assert (link.ad_account_id, link.business_id) == (new.id, business)

    db.delete(pair)
    db.commit()
    assert world.open_links() == []


def test_a_row_made_after_the_link_carries_the_business_from_its_flush(
    db: Session,
) -> None:
    world = World(db)
    page, account = world.page("p1"), world.account("act_1")
    world.pair(page, account)
    db.commit()
    business = world.open_links()[0].business_id

    rows = _rows(world, page, account)

    for name, row in rows.items():
        assert row.business_id == business, name


def test_a_lead_with_no_form_takes_its_card_s_business(db: Session) -> None:
    world = World(db)
    page, account = world.page("p1"), world.account("act_1")
    world.pair(page, account)
    db.commit()
    business = world.open_links()[0].business_id
    stage = CrmStage(
        owner_id=world.owner.id,
        page_id=page.id,
        ad_account_id=account.id,
        name="Yangi",
        color="#000000",
        kind="new",
        position=0,
    )
    lead = Lead(
        owner_id=world.owner.id,
        provider="manual",
        leadgen_id="manual:1",
        full_name="Qo'lda",
        phone_e164="+998900000009",
        submitted_at=world.now,
        received_at=world.now,
    )
    db.add_all([stage, lead])
    db.flush()
    assert lead.business_id is None

    db.add(
        CrmCard(
            owner_id=world.owner.id,
            page_id=page.id,
            ad_account_id=account.id,
            lead_id=lead.id,
            stage_id=stage.id,
        )
    )
    db.flush()

    assert lead.business_id == business


def test_a_row_that_names_no_page_or_an_unlinked_one_is_left_empty(
    db: Session,
) -> None:
    world = World(db)
    page, account = world.page("p1", profile=False), world.account("act_1")
    world.pair(page, account)
    db.commit()
    form = LeadForm(
        owner_id=world.owner.id, provider=PROVIDER, external_id="f1", page_id=page.id
    )
    db.add(form)
    db.flush()
    loose = ChatSession(owner_id=world.owner.id)
    launch = CampaignLaunch(
        owner_id=world.owner.id,
        ad_account_id=account.id,
        page_id=page.id,
        provider=PROVIDER,
        status="created",
    )
    lead = Lead(
        owner_id=world.owner.id,
        provider=PROVIDER,
        leadgen_id="l1",
        form_id=form.id,
        full_name="Lid",
        phone_e164="+998900000001",
        submitted_at=world.now,
        received_at=world.now,
    )
    db.add_all([loose, launch, lead])
    db.commit()

    assert (loose.business_id, launch.business_id, lead.business_id) == (
        None,
        None,
        None,
    )


def test_a_business_set_by_the_caller_is_not_replaced(db: Session) -> None:
    world = World(db)
    first, second = world.page("p1"), world.page("p2")
    account = world.account("act_1")
    world.pair(first, account)
    world.pair(second, account)
    db.commit()
    other = next(
        link.business_id for link in world.open_links() if link.page_id == second.id
    )

    chat = ChatSession(
        owner_id=world.owner.id,
        page_id=first.id,
        ad_account_id=account.id,
        business_id=other,
    )
    db.add(chat)
    db.commit()

    assert chat.business_id == other


def test_links_that_cannot_be_settled_do_not_fail_the_commit(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World(db)
    page, account = world.page("p1"), world.account("act_1")

    def broken(*args: object, **kwargs: object) -> None:
        raise OperationalError("select 1", {}, Exception("lock timeout"))

    monkeypatch.setattr(links, "sync_links", broken)
    world.pair(page, account)
    db.commit()

    assert db.scalars(select(PagePair)).all() != []
    assert db.scalars(select(BusinessLink)).all() == []

    monkeypatch.undo()
    chat = ChatSession(owner_id=world.owner.id, page_id=page.id)
    db.add(chat)
    db.commit()
    assert world.links() == []
    assert links.settle(db, owner_id=world.owner.id) is not None
    db.commit()
    assert len(world.open_links()) == 1
