"""A frozen subscription serves nothing and loses no day; an unpaid one is cut
off 72 hours after its end, and its adverts are kept, stopped, not deleted.

User decisions 2026-11-25: Support and the superuser freeze, with a reason
and a release time the customer sees; while frozen everything stops as if
the plan had ended; on release the days come back and the customer is told
in the bot and the cabinet. Leads stop being fetched 72 hours after an
unpaid end too.
"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.ads.constants import LAPSE_CUT_OFF
from app.modules.ads.models import Campaign
from app.modules.ads.selectors import frequently_swept_account_ids, lapse_candidates
from app.modules.ads.services import lapse
from app.modules.ads.services.lapse import (
    FREEZE_RESUME_REASON,
    FREEZE_STOP_REASON,
    hold_frozen_owner,
    resume_after_lapse,
)
from app.modules.audit.models import ActionLog
from app.modules.backoffice.constants import ActionKind, Role
from app.modules.billing.constants import HistoryKind
from app.modules.billing.models import SubscriptionChange
from app.modules.billing.selectors import (
    cut_off,
    expiring_subscriptions,
    has_live_subscription,
)
from app.modules.billing.services import release_due
from app.modules.leads.services import served_no_more
from app.modules.notifications.selectors.inbox import cabinet_inbox
from tests.pg.test_ads_manage import _owner_with_account
from tests.pg.test_lapse_timing import _ended
from tests.pg.test_office_actions import (
    URL,
    _bearer,
    _kinds,
    _plan_of,
    _shop,
    _staff,
)


def _freeze(client: TestClient, customer_id: object, headers: dict, **extra: object):
    body = {
        "until": (utcnow() + timedelta(days=7)).isoformat(),
        "reason": "Mijoz ta'tilda",
        **extra,
    }
    return client.post(f"{URL}/{customer_id}/freeze", headers=headers, json=body)


def _tasks(queued: list) -> list[str]:
    return [name.rsplit(".", 1)[-1] for name, _ in queued]


def test_support_freezes_and_the_customer_is_served_nothing(
    client: TestClient, db: Session, queued: list
) -> None:
    customer, _ = _shop(db)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")

    done = _freeze(client, customer.id, support)

    assert done.status_code == 200, done.text
    db.expire_all()
    subscription = _plan_of(db, customer)
    assert subscription.frozen_at is not None
    assert subscription.frozen_reason == "Mijoz ta'tilda"
    assert not has_live_subscription(db, owner=customer)
    assert "hold_frozen_owner_task" in _tasks(queued)
    assert _kinds(db, customer) == [ActionKind.SUBSCRIPTION_FROZEN]

    status = client.get("/api/v1/billing/status", headers=_bearer(customer)).json()
    assert status["is_read_only"] is True
    assert status["frozen"]["reason"] == "Mijoz ta'tilda"
    assert status["frozen"]["until"] is not None
    assert status["lapse_until"] == ""

    card = client.get(f"{URL}/{customer.id}", headers=support).json()
    assert card["subscription"]["frozen"]["reason"] == "Mijoz ta'tilda"
    assert card["lapsed"] is None


def test_only_support_and_the_superuser_may_freeze(
    client: TestClient, db: Session
) -> None:
    customer, _ = _shop(db)
    _, seller = _staff(db, Role.SALES, email="seller@office.test")
    _, finance = _staff(db, Role.FINANCE, email="finance@office.test")
    _, root = _staff(db, email="root@office.test", superuser=True)

    assert _freeze(client, customer.id, seller).status_code == 404
    assert _freeze(client, customer.id, finance).status_code == 404
    assert _freeze(client, customer.id, root).status_code == 200


def test_a_freeze_needs_a_reason_a_future_release_and_a_running_plan(
    client: TestClient, db: Session
) -> None:
    customer, _ = _shop(db)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")

    assert _freeze(client, customer.id, support, reason="").status_code == 422
    past = (utcnow() - timedelta(hours=1)).isoformat()
    assert _freeze(client, customer.id, support, until=past).status_code == 400
    far = (utcnow() + timedelta(days=400)).isoformat()
    assert _freeze(client, customer.id, support, until=far).status_code == 400

    db.delete(_plan_of(db, customer))
    db.commit()
    assert _freeze(client, customer.id, support).status_code == 400


def test_freezing_again_moves_the_release_not_the_start(
    client: TestClient, db: Session
) -> None:
    customer, _ = _shop(db)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    _freeze(client, customer.id, support)
    db.expire_all()
    began = _plan_of(db, customer).frozen_at

    later = (utcnow() + timedelta(days=20)).isoformat()
    assert _freeze(client, customer.id, support, until=later).status_code == 200

    db.expire_all()
    subscription = _plan_of(db, customer)
    assert subscription.frozen_at == began
    assert subscription.frozen_until > utcnow() + timedelta(days=19)
    frozen = db.scalars(
        select(SubscriptionChange).where(SubscriptionChange.kind == HistoryKind.FROZEN)
    ).all()
    assert len(frozen) == 1


def test_the_release_gives_back_every_frozen_minute_and_tells_the_customer(
    client: TestClient, db: Session, queued: list
) -> None:
    customer, _ = _shop(db)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    _freeze(client, customer.id, support)
    db.expire_all()
    subscription = _plan_of(db, customer)
    subscription.frozen_at = utcnow() - timedelta(days=5)
    db.commit()
    before = subscription.expires_at
    queued.clear()

    done = client.post(
        f"{URL}/{customer.id}/unfreeze", headers=support, json={"reason": "Qaytdi"}
    )

    assert done.status_code == 200, done.text
    db.expire_all()
    subscription = _plan_of(db, customer)
    gained = subscription.expires_at - before
    assert timedelta(days=5) <= gained < timedelta(days=5, minutes=1)
    assert subscription.frozen_at is None and subscription.frozen_until is None
    assert has_live_subscription(db, owner=customer)
    sent = _tasks(queued)
    assert "resume_after_payment_task" in sent
    assert "reread_unpaid_leads_task" in sent
    assert "announce_unfrozen_task" in sent
    change = db.scalars(
        select(SubscriptionChange).where(
            SubscriptionChange.kind == HistoryKind.UNFROZEN
        )
    ).one()
    assert change.days == 5

    items = cabinet_inbox(db, owner=customer, now=utcnow())
    assert any(item.key == f"subscription:unfrozen:{change.id}" for item in items)

    again = client.post(
        f"{URL}/{customer.id}/unfreeze", headers=support, json={"reason": "x"}
    )
    assert again.status_code == 400


def test_a_freeze_whose_time_came_is_released_on_its_own(
    client: TestClient, db: Session, queued: list
) -> None:
    customer, _ = _shop(db)
    _, support = _staff(db, Role.SUPPORT, email="support@office.test")
    _freeze(client, customer.id, support)
    db.expire_all()
    subscription = _plan_of(db, customer)
    subscription.frozen_until = utcnow() - timedelta(minutes=1)
    db.commit()

    assert release_due(db, now=utcnow()) == 1

    db.expire_all()
    assert _plan_of(db, customer).frozen_at is None
    assert release_due(db, now=utcnow()) == 0


def test_a_frozen_owner_is_not_read_warned_nor_lapsed(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, account, now = _ended(db, ago=timedelta(days=-3))
    subscription = _plan_of(db, owner)
    assert account.id in frequently_swept_account_ids(db, now=now)

    subscription.frozen_at = now - timedelta(days=10)
    subscription.frozen_until = now + timedelta(days=10)
    db.commit()

    assert account.id not in frequently_swept_account_ids(db, now=now)
    assert served_no_more(db, owner_id=owner.id, now=now)
    assert subscription not in expiring_subscriptions(
        db, start=now, end=now + timedelta(days=5)
    )
    # Its plan's end passes while frozen: still the freeze's, not a lapse.
    later = now + timedelta(days=5)
    assert owner.id not in lapse_candidates(db, now=later)


def test_leads_stop_72_hours_after_an_unpaid_end(db: Session) -> None:
    fresh, _account, now = _ended(db, ago=LAPSE_CUT_OFF - timedelta(hours=1))
    assert not served_no_more(db, owner_id=fresh.id, now=now)
    assert not cut_off(db, owner_id=fresh.id, since=now - LAPSE_CUT_OFF)


def test_leads_are_cut_off_past_the_72_hours(db: Session) -> None:
    stale, account, now = _ended(db, ago=LAPSE_CUT_OFF + timedelta(hours=1))
    assert served_no_more(db, owner_id=stale.id, now=now)
    assert account.id not in frequently_swept_account_ids(db, now=now)


def test_an_owner_who_never_subscribed_still_gets_leads(db: Session) -> None:
    owner, _account = _owner_with_account(db)
    assert not served_no_more(db, owner_id=owner.id, now=utcnow())


def test_a_freeze_stops_the_adverts_and_the_release_starts_them(
    db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lapse, "sync_ad_account", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "app.modules.billing.services.require_live_subscription",
        lambda *_a, **_k: None,
    )
    owner, _account, now = _ended(db, ago=timedelta(days=-10))
    subscription = _plan_of(db, owner)
    subscription.frozen_at = now
    subscription.frozen_until = now + timedelta(days=3)
    db.commit()

    hold = hold_frozen_owner(db, owner=owner, now=now)

    assert hold is not None
    stops = db.scalars(select(ActionLog).where(ActionLog.action == "pause")).all()
    assert [stop.reason for stop in stops] == [FREEZE_STOP_REASON]
    for stop in stops:
        stop.status = "applied"
    campaign = db.scalars(select(Campaign)).one()
    campaign.delivery, campaign.status = "paused", "PAUSED"
    assert lapse.remove_after_lapse(db, hold=hold, now=now + timedelta(days=9)) is None

    subscription.frozen_at = None
    subscription.frozen_until = None
    db.commit()
    resume_after_lapse(db, hold=hold, now=now)
    resumes = db.scalars(select(ActionLog).where(ActionLog.action == "resume")).all()
    assert [log.reason for log in resumes] == [FREEZE_RESUME_REASON]


def test_a_cut_off_owners_lead_is_not_fetched_and_is_read_after_paying(
    db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from cryptography.fernet import Fernet
    from metaads import PROVIDER

    from app.common.config import settings
    from app.modules.billing.models import Subscription
    from app.modules.leads import services as leads
    from app.modules.leads.constants import UNPAID, RawEventStatus
    from app.modules.leads.models import RawLeadEvent
    from tests.pg.test_connection_heal import _owner
    from tests.pg.test_sweep_accounts import _plan

    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    asked: list[object] = []
    monkeypatch.setattr(
        leads.registry,
        "get",
        lambda _: SimpleNamespace(
            leads=SimpleNamespace(fetch_lead=lambda **kw: asked.append(kw))
        ),
    )
    owner, _connection, page = _owner(db, 1)
    end = utcnow() - LAPSE_CUT_OFF - timedelta(hours=1)
    db.add(
        Subscription(
            owner_id=owner.id,
            plan_id=_plan(db).id,
            status="active",
            extra_pages=0,
            started_at=end - timedelta(days=30),
            expires_at=end,
            note="",
        )
    )
    event = RawLeadEvent(
        provider=PROVIDER,
        signature_valid=True,
        page_external_id=page.external_id,
        leadgen_external_id="lead-1",
    )
    db.add(event)
    db.commit()

    assert leads.import_lead(db, event_id=str(event.id)) == UNPAID
    db.refresh(event)
    assert asked == []
    assert (event.status, event.error_code) == (RawEventStatus.FAILED, UNPAID)
    assert event not in leads.retryable_deliveries(
        db, now=utcnow() + timedelta(hours=1)
    )

    queued.clear()
    assert leads.reread_unpaid_leads(db, owner_id=owner.id, now=utcnow()) == 1
    db.commit()
    assert [name.rsplit(".", 1)[-1] for name, _ in queued] == ["import_lead_task"]
