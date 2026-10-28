"""The CRM per page and ad account pair against PostgreSQL: handing the
Django project's one CRM out to the pairs, a lead landing on its own pair,
and a manager's free seat that works on its own page only."""

from datetime import timedelta

from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common import tokens
from app.common.crypto import fingerprint
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.models import CampaignLaunch
from app.modules.billing.models import Plan, Subscription
from app.modules.crm.backfill import assign_pairs
from app.modules.crm.models import (
    CrmActivity,
    CrmCard,
    CrmLostReason,
    CrmMember,
    CrmSetup,
    CrmStage,
)
from app.modules.crm.services import place_lead
from app.modules.integrations.models import (
    AdAccount,
    PageAccount,
    PagePair,
    ProviderConnection,
)
from app.modules.leads.models import Lead, LeadForm


def _auth(user: User) -> dict[str, str]:
    token = tokens.issue(subject=str(user.id), kind="access", now=utcnow())
    return {"Authorization": f"Bearer {token}"}


def _world(db: Session) -> dict[str, object]:
    """Two pages on one account, each with a launch of ours, a paid plan, and
    the one CRM the Django project kept for the owner."""
    now = utcnow()
    owner = User(
        email="crm@example.com", full_name="Ega", password="!", date_joined=now
    )
    db.add(owner)
    db.flush()
    plan = Plan(price=100, max_adsets=10, llm_cost_limit_minor=0)
    db.add(plan)
    db.flush()
    db.add(
        Subscription(
            owner_id=owner.id,
            plan_id=plan.id,
            status="active",
            started_at=now - timedelta(days=1),
            expires_at=now + timedelta(days=29),
        )
    )
    connection = ProviderConnection(
        owner_id=owner.id,
        provider=PROVIDER,
        external_user_id="fb-1",
        token_encrypted=b"x",
        token_fingerprint=fingerprint("x"),
    )
    db.add(connection)
    db.flush()
    account = AdAccount(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id="act_1",
        connection_id=connection.id,
        name="Asosiy",
        currency="USD",
        timezone="Asia/Tashkent",
        may_advertise=True,
        is_active=True,
        is_current=True,
    )
    pages = [
        PageAccount(
            owner_id=owner.id,
            provider=PROVIDER,
            external_id=f"page_{n}",
            connection_id=connection.id,
            name=f"Sahifa {n}",
            token_encrypted=b"x",
            token_fingerprint=f"p{n}",
            is_active=True,
            is_current=n == 1,
        )
        for n in (1, 2)
    ]
    db.add_all([account, *pages])
    db.flush()
    forms = []
    for n, page in enumerate(pages, start=1):
        db.add(PagePair(owner_id=owner.id, page_id=page.id, ad_account_id=account.id))
        db.add(
            CampaignLaunch(
                owner_id=owner.id,
                ad_account_id=account.id,
                page_id=page.id,
                provider=PROVIDER,
                status="created",
                created_refs={"campaign": f"c_{n}"},
            )
        )
        form = LeadForm(
            owner_id=owner.id, provider=PROVIDER, external_id=f"f_{n}", page_id=page.id
        )
        db.add(form)
        forms.append(form)
    db.flush()

    def lead(name: str, campaign: str, form: LeadForm, phone: str) -> Lead:
        row = Lead(
            owner_id=owner.id,
            provider=PROVIDER,
            leadgen_id=name,
            form_id=form.id,
            campaign_external_id=campaign,
            phone_e164=phone,
            full_name=name,
            submitted_at=now - timedelta(hours=2),
            received_at=now - timedelta(hours=2),
        )
        db.add(row)
        db.flush()
        return row

    first = lead("bir", "c_1", forms[0], "+998900000001")
    second = lead("ikki", "c_2", forms[1], "+998900000001")
    foreign = lead("begona", "c_9", forms[0], "+998900000003")

    setup = CrmSetup(owner_id=owner.id, state="on", currency="USD", step=5)
    db.add(setup)
    stages = {
        kind: CrmStage(
            owner_id=owner.id, name=kind, color="#000000", kind=kind, position=n
        )
        for n, kind in enumerate(("new", "open", "won", "lost"))
    }
    reason = CrmLostReason(owner_id=owner.id, name="Qimmat", position=0)
    db.add_all([*stages.values(), reason])
    managers = []
    for n in (1, 2):
        user = User(
            email=f"m{n}@example.com",
            full_name=f"Menejer {n}",
            password="!",
            date_joined=now,
            crm_owner_id=owner.id,
        )
        db.add(user)
        db.flush()
        member = CrmMember(
            owner_id=owner.id,
            user_id=user.id,
            must_change_password=False,
            created_at=now - timedelta(days=3 - n),
        )
        db.add(member)
        managers.append(user)
    db.flush()
    cards = {
        "first": CrmCard(
            owner_id=owner.id,
            lead_id=first.id,
            stage_id=stages["open"].id,
            assignee_id=managers[1].id,
        ),
        "second": CrmCard(
            owner_id=owner.id,
            lead_id=second.id,
            stage_id=stages["lost"].id,
            assignee_id=managers[1].id,
            lost_reason_id=reason.id,
            lost_reason_name=reason.name,
            closed_at=now,
        ),
        "foreign": CrmCard(
            owner_id=owner.id, lead_id=foreign.id, stage_id=stages["new"].id
        ),
    }
    db.add_all(cards.values())
    db.flush()
    for card in cards.values():
        db.add(CrmActivity(owner_id=owner.id, card_id=card.id, kind="arrived"))
    db.commit()
    return {
        "owner": owner,
        "account": account,
        "pages": pages,
        "forms": forms,
        "setup": setup,
        "stages": stages,
        "reason": reason,
        "managers": managers,
        "cards": cards,
    }


def _count(db: Session, model: type) -> int:
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def test_django_rows_go_to_their_pairs_and_nothing_is_lost(db: Session) -> None:
    world = _world(db)
    page_1, page_2 = world["pages"]  # type: ignore[misc]
    cards = world["cards"]
    stages = world["stages"]
    before = {
        model: _count(db, model)
        for model in (CrmCard, CrmActivity, CrmMember, CrmSetup)
    }

    report = assign_pairs(db)
    db.commit()

    assert report.cards_placed == 2 and report.cards_left == 1
    assert report.setups_copied == 1
    assert _count(db, CrmCard) == before[CrmCard]
    assert _count(db, CrmActivity) == before[CrmActivity]
    assert _count(db, CrmMember) == before[CrmMember]
    assert _count(db, CrmSetup) == before[CrmSetup] + 1

    setups = {s.page_id: s for s in db.scalars(select(CrmSetup))}
    assert set(setups) == {page_1.id, page_2.id}
    # The original keeps its id on the cabinet's pair; the copy is running too.
    assert setups[page_1.id].id == world["setup"].id
    assert setups[page_2.id].state == "on"

    first = db.get(CrmCard, cards["first"].id)
    assert (first.page_id, first.stage_id) == (page_1.id, stages["open"].id)
    second = db.get(CrmCard, cards["second"].id)
    copy = db.get(CrmStage, second.stage_id)
    assert second.page_id == page_2.id
    assert copy.page_id == page_2.id and copy.kind == "lost"
    assert copy.id != stages["lost"].id
    reason = db.get(CrmLostReason, second.lost_reason_id)
    assert reason.page_id == page_2.id and reason.name == "Qimmat"
    assert second.lost_reason_name == "Qimmat"
    # Not one of ours: kept, off every board.
    assert db.get(CrmCard, cards["foreign"].id).page_id is None
    assert {m.page_id for m in db.scalars(select(CrmMember))} == {page_1.id}

    again = assign_pairs(db)
    db.commit()
    assert again.cards_placed == 0 and again.setups_copied == 0
    assert _count(db, CrmSetup) == before[CrmSetup] + 1


def test_boards_leads_and_seats_by_pair(client: TestClient, db: Session) -> None:
    world = _world(db)
    assign_pairs(db)
    db.commit()
    owner = world["owner"]
    page_2 = world["pages"][1]  # type: ignore[index]
    cards = world["cards"]
    auth = _auth(owner)  # type: ignore[arg-type]

    home = client.get("/api/v1/crm", headers=auth)
    assert home.status_code == 200, home.text
    body = home.json()
    assert body["pair"] == "page_1:act_1"
    assert {p["key"] for p in body["pairs"]} == {"page_1:act_1", "page_2:act_1"}
    on_home = {c["id"] for col in body["columns"] for c in col["cards"]}
    assert on_home == {str(cards["first"].id)}

    other = client.get("/api/v1/crm", params={"pair": "page_2:act_1"}, headers=auth)
    assert other.status_code == 200, other.text
    on_other = {c["id"] for col in other.json()["columns"] for c in col["cards"]}
    assert on_other == {str(cards["second"].id)}

    # A card opened by its link opens on its own pair.
    opened = client.get(f"/api/v1/crm/cards/{cards['second'].id}", headers=auth)
    assert opened.status_code == 200, opened.text
    assert opened.json()["pair"] == "page_2:act_1"
    assert (
        client.get(f"/api/v1/crm/cards/{cards['foreign'].id}", headers=auth).status_code
        == 404
    )

    # A new lead of page 2's launch lands on page 2's CRM, not page 1's.
    lead = Lead(
        owner_id=owner.id,
        provider=PROVIDER,
        leadgen_id="uch",
        form_id=world["forms"][1].id,
        campaign_external_id="c_2",
        phone_e164="+998900000004",
        submitted_at=utcnow(),
        received_at=utcnow(),
    )
    db.add(lead)
    db.commit()
    assert place_lead(db, lead_id=str(lead.id)) == "placed"
    card = db.scalar(select(CrmCard).where(CrmCard.lead_id == lead.id))
    assert card.page_id == page_2.id
    assert db.get(CrmStage, card.stage_id).page_id == page_2.id

    # Page 1 has both old managers: the older sits in its free seat.
    team = {m["user"]["email"]: m["seated"] for m in body["members"]}
    assert team == {"m1@example.com": True, "m2@example.com": False}
    waiting = client.get("/api/v1/crm", headers=_auth(world["managers"][1]))
    assert waiting.status_code == 409 and waiting.json()["detail"] == {"crm": "seat"}

    # Page 2's free seat goes to its first manager, and only there.
    added = client.post(
        "/api/v1/crm/settings/members",
        params={"pair": "page_2:act_1"},
        json={
            "name": "Uchinchi",
            "email": "m3@example.com",
            "password": "Kuchli-parol-77",
        },
        headers=auth,
    )
    assert added.status_code == 201, added.text
    assert added.json()["seated"] is True
    member = db.scalar(
        select(CrmMember)
        .join(User, User.id == CrmMember.user_id)
        .where(User.email == "m3@example.com")
    )
    assert member.page_id == page_2.id
    extra = client.post(
        "/api/v1/crm/settings/members",
        params={"pair": "page_2:act_1"},
        json={
            "name": "To'rtinchi",
            "email": "m4@example.com",
            "password": "Kuchli-parol-77",
        },
        headers=auth,
    )
    assert extra.status_code == 201 and extra.json()["seated"] is False

    # A manager sees only their own pair, whatever pair they ask for.
    first_manager = _auth(world["managers"][0])
    mine = client.get(
        "/api/v1/crm", params={"pair": "page_2:act_1"}, headers=first_manager
    )
    assert mine.status_code == 200, mine.text
    assert mine.json()["pair"] == "page_1:act_1" and mine.json()["pairs"] == []
    assert (
        client.get(
            f"/api/v1/crm/cards/{cards['second'].id}", headers=first_manager
        ).status_code
        == 404
    )
