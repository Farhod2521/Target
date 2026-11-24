"""A business for every page and ad account pair, against PostgreSQL: the
link each stored pair gets, what a second pair, a changed account and a
removed pair do to it, and the business written beside the pair on rows."""

from datetime import timedelta

from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.crypto import fingerprint
from app.common.db import utcnow
from app.common.deletion import delete_rows
from app.modules.accounts.models import User
from app.modules.ads.models import CampaignLaunch
from app.modules.businesses.backfill import left_empty, link_everyone
from app.modules.businesses.models import Business, BusinessLink
from app.modules.businesses.selectors import businesses_for
from app.modules.businesses.services.links import (
    business_of_pair,
    fill_rows,
    sync_links,
)
from app.modules.chat.models import ChatSession
from app.modules.crm.models import CrmCard, CrmStage
from app.modules.integrations.models import (
    AdAccount,
    PageAccount,
    PagePair,
    ProviderConnection,
)
from app.modules.leads.models import Lead, LeadForm


class World:
    """One owner with a Meta login; pages, accounts and pairs on request."""

    def __init__(self, db: Session, email: str = "ega@example.com") -> None:
        self.db = db
        self.now = utcnow()
        self.owner = User(
            email=email, full_name="Ega", password="!", date_joined=self.now
        )
        db.add(self.owner)
        db.flush()
        self.connection = ProviderConnection(
            owner_id=self.owner.id,
            provider=PROVIDER,
            external_user_id=f"fb-{email}",
            token_encrypted=b"x",
            token_fingerprint=fingerprint(email),
        )
        db.add(self.connection)
        db.flush()
        self.made = 0

    def account(self, external_id: str) -> AdAccount:
        row = AdAccount(
            owner_id=self.owner.id,
            provider=PROVIDER,
            external_id=external_id,
            connection_id=self.connection.id,
            name=external_id,
            currency="USD",
            timezone="Asia/Tashkent",
            may_advertise=True,
            is_active=True,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def page(self, external_id: str, *, profile: bool = True) -> PageAccount:
        row = PageAccount(
            owner_id=self.owner.id,
            provider=PROVIDER,
            external_id=external_id,
            connection_id=self.connection.id,
            name=f"Sahifa {external_id}",
            token_encrypted=b"x",
            token_fingerprint=f"{self.owner.email}-{external_id}",
            is_active=True,
        )
        self.db.add(row)
        self.db.flush()
        if profile:
            self.profile(row)
        return row

    def profile(self, page: PageAccount) -> Business:
        row = Business(
            user_id=self.owner.id,
            page_id=page.id,
            name=f"Biznes {page.external_id}",
            timezone="Asia/Tashkent",
            city="Toshkent",
            website="https://example.uz",
        )
        self.db.add(row)
        self.db.flush()
        return row

    def pair(self, page: PageAccount, account: AdAccount) -> PagePair:
        self.made += 1
        row = PagePair(
            owner_id=self.owner.id,
            page_id=page.id,
            ad_account_id=account.id,
            created_at=self.now + timedelta(seconds=self.made),
        )
        self.db.add(row)
        self.db.flush()
        return row

    def sync(self):  # type: ignore[no-untyped-def]
        return sync_links(self.db, owner_id=self.owner.id)

    def links(self) -> list[BusinessLink]:
        return list(
            self.db.scalars(
                select(BusinessLink)
                .where(BusinessLink.owner_id == self.owner.id)
                .order_by(BusinessLink.bound_at, BusinessLink.external_id)
            )
        )

    def open_links(self) -> list[BusinessLink]:
        return [link for link in self.links() if link.unbound_at is None]


def _profile_of(db: Session, page: PageAccount) -> Business:
    return db.scalars(select(Business).where(Business.page_id == page.id)).one()


def test_each_page_s_pair_is_its_profile_s_business(db: Session) -> None:
    world = World(db)
    account = world.account("act_1")
    first, second = world.page("p1"), world.page("p2")
    world.pair(first, account)
    world.pair(second, account)

    done = world.sync()

    assert (done.bound, done.opened, done.waiting) == (2, 0, 0)
    by_page = {link.page_id: link for link in world.open_links()}
    assert by_page[first.id].business_id == _profile_of(db, first).id
    assert by_page[second.id].business_id == _profile_of(db, second).id
    assert by_page[first.id].external_id == "p1:act_1"
    assert by_page[first.id].kind == "meta_pair"


def test_a_second_run_changes_nothing(db: Session) -> None:
    world = World(db)
    world.pair(world.page("p1"), world.account("act_1"))
    world.sync()
    before = [(link.id, link.updated_at) for link in world.links()]

    done = world.sync()

    assert (done.kept, done.changed) == (1, 0)
    assert [(link.id, link.updated_at) for link in world.links()] == before
    assert db.scalar(select(Business.id).where(Business.page_id.is_(None))) is None


def test_a_page_with_no_profile_waits_and_no_profile_is_made_for_it(
    db: Session,
) -> None:
    world = World(db)
    page = world.page("p1", profile=False)
    world.pair(page, world.account("act_1"))

    done = world.sync()

    assert done.waiting == 1
    assert world.links() == []
    assert db.scalars(select(Business)).all() == []

    world.profile(page)
    assert world.sync().bound == 1
    assert len(world.open_links()) == 1


def test_a_second_pair_on_the_page_is_a_business_of_its_own(db: Session) -> None:
    world = World(db)
    page = world.page("p1")
    main, extra = world.account("act_1"), world.account("act_2")
    world.pair(page, main)
    world.pair(page, extra)

    done = world.sync()

    assert (done.bound, done.opened) == (1, 1)
    profile = _profile_of(db, page)
    by_account = {link.ad_account_id: link for link in world.open_links()}
    assert by_account[main.id].business_id == profile.id
    own = db.get(Business, by_account[extra.id].business_id)
    assert own is not None and own.id != profile.id
    assert (own.page_id, own.ad_account_id) == (None, extra.id)
    assert (own.name, own.city, own.website) == (
        profile.name,
        profile.city,
        profile.website,
    )
    # The cabinet's own reads still see one profile for the owner.
    assert [row.id for row in businesses_for(db, owner=world.owner)] == [profile.id]


def test_an_account_that_already_keys_a_business_leaves_the_pair_unlinked(
    db: Session,
) -> None:
    world = World(db)
    first, second = world.page("p1"), world.page("p2")
    main, extra = world.account("act_1"), world.account("act_2")
    for page in (first, second):
        world.pair(page, main)
    world.pair(first, extra)
    world.pair(second, extra)

    done = world.sync()

    assert (done.bound, done.opened, done.blocked) == (2, 1, 1)
    assert len(world.open_links()) == 3
    assert world.sync().blocked == 1


def test_a_changed_account_keeps_the_business_and_closes_the_old_link(
    db: Session,
) -> None:
    world = World(db)
    page = world.page("p1")
    old, new = world.account("act_1"), world.account("act_2")
    pair = world.pair(page, old)
    world.sync()
    business = world.open_links()[0].business_id

    pair.ad_account_id = new.id
    db.flush()
    done = world.sync()

    assert (done.moved, done.closed, done.bound) == (1, 0, 0)
    closed = [link for link in world.links() if link.unbound_at is not None]
    assert [link.ad_account_id for link in closed] == [old.id]
    (now_open,) = world.open_links()
    assert (now_open.ad_account_id, now_open.business_id) == (new.id, business)
    assert now_open.external_id == "p1:act_2"


def test_a_second_pair_s_business_follows_its_changed_account(db: Session) -> None:
    world = World(db)
    page = world.page("p1")
    main, extra, later = (world.account(f"act_{n}") for n in (1, 2, 3))
    world.pair(page, main)
    pair = world.pair(page, extra)
    world.sync()

    pair.ad_account_id = later.id
    db.flush()
    world.sync()

    link = next(row for row in world.open_links() if row.ad_account_id == later.id)
    own = db.get(Business, link.business_id)
    assert own is not None and own.ad_account_id == later.id


def test_a_removed_pair_closes_its_link_and_keeps_the_business(db: Session) -> None:
    world = World(db)
    page = world.page("p1")
    pair = world.pair(page, world.account("act_1"))
    world.sync()

    db.delete(pair)
    db.flush()
    done = world.sync()

    assert done.closed == 1
    assert world.open_links() == []
    assert _profile_of(db, page) is not None

    # The same pair stored again is the same business, on a new link.
    world.pair(page, db.scalars(select(AdAccount)).one())
    assert world.sync().bound == 1
    assert world.open_links()[0].business_id == _profile_of(db, page).id


def test_every_owner_is_linked_in_one_run_and_a_rollback_leaves_nothing(
    db: Session,
) -> None:
    worlds = [World(db, "bir@example.com"), World(db, "ikki@example.com")]
    for n, world in enumerate(worlds):
        world.pair(world.page(f"p{n}"), world.account(f"act_{n}"))
    db.commit()

    done = link_everyone(db)
    assert done.bound == 2
    db.rollback()
    assert db.scalars(select(BusinessLink)).all() == []

    link_everyone(db)
    db.commit()
    assert [len(world.open_links()) for world in worlds] == [1, 1]


def _rows(world: World, page: PageAccount, account: AdAccount) -> dict[str, object]:
    db, owner = world.db, world.owner
    form = LeadForm(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id=f"f-{page.external_id}-{account.external_id}",
        page_id=page.id,
    )
    db.add(form)
    db.flush()
    leads = []
    for n in (1, 2):
        lead = Lead(
            owner_id=owner.id,
            provider=PROVIDER,
            leadgen_id=f"{form.external_id}-{n}",
            form_id=form.id,
            phone_e164="+998900000001",
            full_name="Lid",
            submitted_at=world.now,
            received_at=world.now,
        )
        db.add(lead)
        leads.append(lead)
    stage = CrmStage(
        owner_id=owner.id,
        page_id=page.id,
        ad_account_id=account.id,
        name="Yangi",
        color="#000000",
        kind="new",
        position=0,
    )
    db.add(stage)
    db.flush()
    card = CrmCard(
        owner_id=owner.id,
        page_id=page.id,
        ad_account_id=account.id,
        lead_id=leads[0].id,
        stage_id=stage.id,
    )
    chat = ChatSession(owner_id=owner.id, page_id=page.id, ad_account_id=account.id)
    launch = CampaignLaunch(
        owner_id=owner.id,
        ad_account_id=account.id,
        page_id=page.id,
        provider=PROVIDER,
        status="created",
    )
    db.add_all([card, chat, launch])
    db.flush()
    return {
        "stage": stage,
        "card": card,
        "chat": chat,
        "launch": launch,
        "carded": leads[0],
        "loose": leads[1],
    }


def test_rows_that_name_a_pair_get_its_business(db: Session) -> None:
    world = World(db)
    page, account = world.page("p1"), world.account("act_1")
    world.pair(page, account)
    rows = _rows(world, page, account)
    world.sync()
    business = world.open_links()[0].business_id

    filled = fill_rows(db)

    for row in rows.values():
        db.refresh(row)
        assert row.business_id == business, row
    assert filled["crm_cards"] == 1 and filled["leads"] == 2
    assert all(count == 0 for count in fill_rows(db).values())
    assert all(count == 0 for count in left_empty(db).values())


def test_on_a_page_with_two_businesses_each_row_goes_to_its_own_pair(
    db: Session,
) -> None:
    world = World(db)
    page = world.page("p1")
    main, extra, gone = (world.account(f"act_{n}") for n in (1, 2, 3))
    world.pair(page, main)
    world.pair(page, extra)
    of_main, of_extra = _rows(world, page, main), _rows(world, page, extra)
    orphan = ChatSession(
        owner_id=world.owner.id, page_id=page.id, ad_account_id=gone.id
    )
    db.add(orphan)
    db.flush()
    world.sync()
    by_account = {link.ad_account_id: link.business_id for link in world.open_links()}

    fill_rows(db)

    for rows, account in ((of_main, main), (of_extra, extra)):
        for name in ("stage", "card", "chat", "launch", "carded"):
            db.refresh(rows[name])
            assert rows[name].business_id == by_account[account.id], name
        # A lead with no card names only its form's page, which is two
        # businesses here: it is left for a person, not guessed.
        db.refresh(rows["loose"])
        assert rows["loose"].business_id is None
    db.refresh(orphan)
    assert orphan.business_id is None
    assert left_empty(db)["chat_sessions"] == 1


def test_a_row_on_an_account_the_pair_left_goes_to_the_page_s_only_business(
    db: Session,
) -> None:
    world = World(db)
    page = world.page("p1")
    old, new = world.account("act_1"), world.account("act_2")
    pair = world.pair(page, old)
    rows = _rows(world, page, old)
    pair.ad_account_id = new.id
    db.flush()
    world.sync()
    (link,) = world.open_links()

    fill_rows(db)

    db.refresh(rows["card"])
    assert rows["card"].business_id == link.business_id
    assert business_of_pair(db, page_id=page.id, ad_account_id=old.id) == (
        link.business_id
    )
    assert business_of_pair(db, page_id=page.id, ad_account_id=new.id) == (
        link.business_id
    )
    assert business_of_pair(db, page_id=None, ad_account_id=new.id) is None


def test_a_deleted_business_takes_its_links_and_empties_the_rows(db: Session) -> None:
    world = World(db)
    page, account = world.page("p1"), world.account("act_1")
    world.pair(page, account)
    rows = _rows(world, page, account)
    world.sync()
    fill_rows(db)
    db.commit()

    delete_rows(db, Business.__table__, Business.page_id == page.id)
    db.commit()

    assert world.links() == []
    for row in rows.values():
        db.refresh(row)
        assert row.business_id is None
