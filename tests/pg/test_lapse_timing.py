"""An unpaid subscription, counted from the moment it ended: the adverts made
here stop after 24 hours, are deleted after 72, and from then on nothing of
the owner's is read from Meta. A delete Meta refused is shown to the office.

Measured on production, 2026-11-19: an owner unpaid since 11-12 whose account
Meta had blocked; nothing was stopped, the delete was refused, the hold closed
as "deleted", the campaign stayed ACTIVE and the account was still read each
half hour a week later.
"""

from datetime import datetime, timedelta

import pytest
from metaads import PROVIDER
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.constants import (
    LAPSE_DELETE_AFTER,
    LAPSE_MARK,
    LAPSE_PAUSE_AFTER,
)
from app.modules.ads.models import CampaignLaunch, LapseHold
from app.modules.ads.selectors import (
    frequently_swept_account_ids,
    lapse_candidates,
    last_warning_due,
    nightly_swept_account_ids,
)
from app.modules.ads.services import lapse
from app.modules.ads.services.lapse import lapse_deletion, open_lapse_hold
from app.modules.audit.models import ActionLog
from app.modules.backoffice.selectors.problems import problems
from app.modules.billing.constants import SubscriptionStatus
from app.modules.billing.models import Subscription
from tests.pg.test_ads_manage import _mirror, _owner_with_account
from tests.pg.test_sweep_accounts import _plan

REFS = {"campaign": "c_1", "adset": ["s_1"], "ad": ["a_1"]}


def _ended(db: Session, *, ago: timedelta) -> tuple[User, object, datetime]:
    """An owner with one advert made here and a subscription ended ``ago``."""
    owner, account = _owner_with_account(db)
    _mirror(db, owner, account.id)
    now = utcnow()
    end = now - ago
    db.add(
        CampaignLaunch(
            owner_id=owner.id,
            ad_account_id=account.id,
            provider=PROVIDER,
            status="created",
            created_refs=REFS,
            finished_at=end - timedelta(days=5),
        )
    )
    db.add(
        Subscription(
            owner_id=owner.id,
            plan_id=_plan(db).id,
            status=SubscriptionStatus.ACTIVE,
            extra_pages=0,
            started_at=end - timedelta(days=30),
            expires_at=end,
            note="",
        )
    )
    db.commit()
    return owner, account, now


def test_the_adverts_are_not_stopped_in_the_first_day(db: Session) -> None:
    owner, _account, now = _ended(db, ago=LAPSE_PAUSE_AFTER - timedelta(minutes=5))
    assert owner.id not in lapse_candidates(db, now=now)


def test_the_adverts_stop_once_the_day_is_over(db: Session) -> None:
    owner, _account, now = _ended(db, ago=LAPSE_PAUSE_AFTER + timedelta(minutes=5))
    assert owner.id in lapse_candidates(db, now=now)


def test_the_deletion_is_72_hours_after_the_end(
    db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lapse, "sync_ad_account", lambda *_a, **_k: None)
    owner, _account, now = _ended(db, ago=LAPSE_PAUSE_AFTER + timedelta(minutes=5))

    hold = open_lapse_hold(db, owner=owner, now=now)

    assert hold is not None
    assert hold.delete_after == hold.ended_at + LAPSE_DELETE_AFTER
    pauses = db.query(ActionLog).filter(ActionLog.action == "pause").all()
    assert [log.request_payload[LAPSE_MARK] for log in pauses] == [str(hold.id)]


def test_a_hold_opened_late_still_leaves_a_day_to_pay() -> None:
    now = utcnow()
    ended = now - timedelta(days=10)
    assert lapse_deletion(ended=ended, now=now) == now + timedelta(hours=24)
    on_time = now - LAPSE_PAUSE_AFTER
    assert lapse_deletion(ended=on_time, now=now) == on_time + LAPSE_DELETE_AFTER


def test_the_last_warning_is_the_day_before_the_deletion() -> None:
    now = utcnow()
    hold = LapseHold(
        ended_at=now - timedelta(hours=24),
        started_at=now - timedelta(hours=24),
        delete_after=now + timedelta(hours=48),
    )
    assert not last_warning_due(hold=hold, now=now)
    assert not last_warning_due(hold=hold, now=now + timedelta(hours=23))
    assert last_warning_due(hold=hold, now=now + timedelta(hours=25))
    assert not last_warning_due(hold=hold, now=now + timedelta(hours=49))


def test_the_accounts_are_read_until_the_deletion(db: Session) -> None:
    _owner, account, now = _ended(db, ago=LAPSE_DELETE_AFTER - timedelta(hours=1))
    assert account.id in frequently_swept_account_ids(db, now=now)
    assert account.id in nightly_swept_account_ids(db, now=now)


def test_nothing_is_read_after_the_deletion_time(db: Session) -> None:
    _owner, account, now = _ended(db, ago=LAPSE_DELETE_AFTER + timedelta(hours=1))
    assert account.id not in frequently_swept_account_ids(db, now=now)
    assert account.id not in nightly_swept_account_ids(db, now=now)


def _refused_delete(db: Session, owner: User, *, status: str) -> LapseHold:
    now = utcnow()
    hold = LapseHold(
        owner_id=owner.id,
        ended_at=now - timedelta(days=4),
        started_at=now - timedelta(days=3),
        delete_after=now - timedelta(hours=1),
        deleted_at=now,
    )
    db.add(hold)
    db.flush()
    db.add(
        ActionLog(
            owner_id=owner.id,
            action="delete_campaign",
            target_level="campaign",
            target_external_id="c_1",
            target_provider=PROVIDER,
            idempotency_key=f"lapse-del-{hold.id}",
            request_payload={LAPSE_MARK: str(hold.id)},
            status=status,
            error_code="account_blocked" if status == "failed" else "",
        )
    )
    db.commit()
    return hold


def _left(db: Session, owner: User) -> list:
    return [
        p
        for p in problems(db, now=utcnow(), limit=None)
        if p.kind == "lapse_left" and p.owner_id == owner.id
    ]


def test_a_delete_meta_refused_is_shown_to_the_office(db: Session) -> None:
    owner, _account, _now = _ended(db, ago=timedelta(days=4))
    _refused_delete(db, owner, status="failed")

    [problem] = _left(db, owner)
    assert problem.urgent
    assert "1 ta" in problem.what and "yoqilgan" in problem.what


def test_a_delete_done_is_not_shown(db: Session) -> None:
    owner, _account, _now = _ended(db, ago=timedelta(days=4))
    _refused_delete(db, owner, status="applied")
    assert _left(db, owner) == []


def test_a_refused_delete_of_a_paid_owner_is_not_shown(db: Session) -> None:
    owner, _account, _now = _ended(db, ago=timedelta(days=4))
    _refused_delete(db, owner, status="failed")
    paid = db.query(Subscription).filter(Subscription.owner_id == owner.id).one()
    paid.expires_at = utcnow() + timedelta(days=30)
    db.commit()
    assert _left(db, owner) == []
