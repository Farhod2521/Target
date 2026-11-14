"""A hold closes only on what was really done, and a blocked account's adverts
made here stop at once and are deleted a day later."""

from datetime import timedelta

import pytest
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import BlockReason, User
from app.modules.accounts.services.block_user import block_user, unblock_user
from app.modules.ads.constants import BLOCK_DELETE_AFTER, LAPSE_DELETE_AFTER, LAPSE_MARK
from app.modules.ads.models import Campaign, CampaignLaunch, LapseHold
from app.modules.ads.services import lapse
from app.modules.ads.services.lapse import (
    BLOCK_STOP_REASON,
    MAX_ASKS,
    hold_blocked_owner,
    release_unblocked_owner,
    remove_after_lapse,
    resume_after_lapse,
    settle_lapse,
    stop_running,
)
from app.modules.audit.models import ActionLog
from tests.pg.test_ads_manage import _mirror, _owner_with_account

REFS = {"campaign": "c_1", "adset": ["s_1"], "ad": ["a_1"]}


@pytest.fixture
def paid(monkeypatch: pytest.MonkeyPatch) -> dict[str, bool]:
    """Whether the owner's subscription is live, switched by the test."""
    state = {"live": True}
    monkeypatch.setattr(lapse, "_has_live", lambda _db, _owner: state["live"])
    monkeypatch.setattr(
        "app.modules.billing.services.require_live_subscription",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(lapse, "sync_ad_account", lambda *_a, **_k: None)
    return state


def _world(db: Session) -> tuple[User, LapseHold]:
    owner, account = _owner_with_account(db)
    _mirror(db, owner, account.id)
    now = utcnow()
    db.add(
        CampaignLaunch(
            owner_id=owner.id,
            ad_account_id=account.id,
            provider=PROVIDER,
            status="created",
            created_refs=REFS,
            finished_at=now - timedelta(days=5),
        )
    )
    hold = LapseHold(
        owner_id=owner.id,
        ended_at=now - timedelta(hours=2),
        started_at=now - timedelta(hours=2),
        delete_after=now + LAPSE_DELETE_AFTER,
    )
    db.add(hold)
    db.commit()
    return owner, hold


def _logs(db: Session, action: str) -> list[ActionLog]:
    return list(
        db.scalars(
            select(ActionLog)
            .where(ActionLog.action == action)
            .order_by(ActionLog.created_at)
        )
    )


def _settle(db: Session, action: str, status: str, code: str = "") -> None:
    for log in _logs(db, action):
        if log.status == "pending":
            log.status, log.error_code = status, code
    db.commit()


def _stopped(db: Session, hold: LapseHold) -> None:
    """The hold's stop went through, and the mirror shows the campaign off."""
    assert stop_running(db, hold=hold) == 1
    _settle(db, "pause", "applied")
    campaign = db.scalars(select(Campaign)).one()
    campaign.delivery, campaign.status = "paused", "PAUSED"
    db.commit()


def test_a_paid_hold_stays_open_until_its_resume_is_done(
    db: Session, queued: list, paid: dict[str, bool]
) -> None:
    _owner, hold = _world(db)
    _stopped(db, hold)

    assert resume_after_lapse(db, hold=hold, now=utcnow()) is None
    assert hold.is_open
    assert [log.status for log in _logs(db, "resume")] == ["pending"]

    _settle(db, "resume", "applied")
    assert resume_after_lapse(db, hold=hold, now=utcnow()) == 0
    assert not hold.is_open and hold.resumed_at is not None
    assert len(_logs(db, "resume")) == 1


def test_a_resume_meta_dropped_is_asked_again_and_not_for_ever(
    db: Session, queued: list, paid: dict[str, bool]
) -> None:
    _owner, hold = _world(db)
    _stopped(db, hold)

    for asked in range(1, MAX_ASKS + 1):
        assert resume_after_lapse(db, hold=hold, now=utcnow()) is None
        assert len(_logs(db, "resume")) == asked
        _settle(db, "resume", "failed", "temporary")

    assert resume_after_lapse(db, hold=hold, now=utcnow()) == 0
    assert not hold.is_open
    assert len(_logs(db, "resume")) == MAX_ASKS


def test_a_resume_refused_for_its_own_reason_is_not_asked_again(
    db: Session, queued: list, paid: dict[str, bool]
) -> None:
    _owner, hold = _world(db)
    _stopped(db, hold)
    resume_after_lapse(db, hold=hold, now=utcnow())
    _settle(db, "resume", "failed", "payment_missing")

    assert resume_after_lapse(db, hold=hold, now=utcnow()) == 0
    assert not hold.is_open
    assert len(_logs(db, "resume")) == 1


def test_an_unpaid_hold_stays_open_until_its_delete_is_done(
    db: Session, queued: list, paid: dict[str, bool]
) -> None:
    paid["live"] = False
    _owner, hold = _world(db)
    _stopped(db, hold)
    due = hold.delete_after + timedelta(minutes=1)

    assert remove_after_lapse(db, hold=hold, now=utcnow()) is None
    assert _logs(db, "delete_campaign") == []

    assert remove_after_lapse(db, hold=hold, now=due) is None
    assert hold.is_open
    deletes = _logs(db, "delete_campaign")
    assert [log.status for log in deletes] == ["pending"]
    assert deletes[0].request_payload[LAPSE_MARK] == str(hold.id)

    _settle(db, "delete_campaign", "failed", "temporary")
    assert remove_after_lapse(db, hold=hold, now=due) is None
    assert len(_logs(db, "delete_campaign")) == 2

    _settle(db, "delete_campaign", "applied")
    assert remove_after_lapse(db, hold=hold, now=due) == 0
    assert hold.deleted_at is not None


def test_a_payment_while_a_delete_was_lost_still_gives_the_advert_back(
    db: Session, queued: list, paid: dict[str, bool]
) -> None:
    paid["live"] = False
    _owner, hold = _world(db)
    _stopped(db, hold)
    due = hold.delete_after + timedelta(minutes=1)
    remove_after_lapse(db, hold=hold, now=due)
    _settle(db, "delete_campaign", "failed", "temporary")

    paid["live"] = True
    assert settle_lapse(db, hold=hold, now=due) == "later"
    assert [log.status for log in _logs(db, "resume")] == ["pending"]
    assert hold.is_open


def test_a_blocked_accounts_adverts_stop_now_and_go_after_a_day(
    db: Session, queued: list, paid: dict[str, bool]
) -> None:
    owner, old = _world(db)
    db.delete(old)
    owner.is_active = False
    db.commit()
    now = utcnow()

    hold = hold_blocked_owner(db, owner=owner, now=now)

    assert hold is not None and hold.delete_after == now + BLOCK_DELETE_AFTER
    stops = _logs(db, "pause")
    assert [log.reason for log in stops] == [BLOCK_STOP_REASON]

    _settle(db, "pause", "applied")
    campaign = db.scalars(select(Campaign)).one()
    campaign.delivery, campaign.status = "paused", "PAUSED"
    db.commit()
    # Paid or not, a blocked account gets nothing back.
    assert settle_lapse(db, hold=hold, now=now + timedelta(hours=1)) == "held"
    assert _logs(db, "resume") == []

    later = now + BLOCK_DELETE_AFTER + timedelta(minutes=1)
    assert settle_lapse(db, hold=hold, now=later) == "held"
    assert [log.status for log in _logs(db, "delete_campaign")] == ["pending"]
    _settle(db, "delete_campaign", "applied")
    assert settle_lapse(db, hold=hold, now=later) == "removed"


def test_blocking_an_unpaid_account_brings_its_deletion_forward(
    db: Session, queued: list, paid: dict[str, bool]
) -> None:
    paid["live"] = False
    owner, hold = _world(db)
    owner.is_active = False
    db.commit()
    now = utcnow()

    assert hold_blocked_owner(db, owner=owner, now=now) == hold
    assert hold.delete_after == now + BLOCK_DELETE_AFTER
    assert db.scalars(select(LapseHold)).all() == [hold]


def test_an_account_opened_again_in_time_gets_its_adverts_back(
    db: Session, queued: list, paid: dict[str, bool]
) -> None:
    owner, old = _world(db)
    db.delete(old)
    owner.is_active = False
    db.commit()
    now = utcnow()
    hold = hold_blocked_owner(db, owner=owner, now=now)
    assert hold is not None
    _settle(db, "pause", "applied")
    campaign = db.scalars(select(Campaign)).one()
    campaign.delivery, campaign.status = "paused", "PAUSED"
    owner.is_active = True
    db.commit()

    assert release_unblocked_owner(db, owner=owner, now=now) == "later"
    assert [log.status for log in _logs(db, "resume")] == ["pending"]


def test_an_unpaid_account_opened_again_has_the_usual_days(
    db: Session, queued: list, paid: dict[str, bool]
) -> None:
    paid["live"] = False
    owner, hold = _world(db)
    now = utcnow()
    hold.delete_after = now + timedelta(hours=3)
    db.commit()

    assert release_unblocked_owner(db, owner=owner, now=now) == "held"
    assert hold.delete_after == now + LAPSE_DELETE_AFTER


def test_a_block_and_its_lifting_send_the_adverts_after_them(
    db: Session, queued: list
) -> None:
    owner, _account = _owner_with_account(db)
    reason = BlockReason(name="Sinov", message_uz="", message_ru="", message_en="")
    db.add(reason)
    db.commit()

    block_user(db, user=owner, reason=reason, shown_to_user=False)
    db.commit()
    unblock_user(db, user=owner, note="xato")
    db.commit()

    names = [name.rsplit(".", 1)[-1] for name, _args in queued]
    assert names == ["hold_blocked_owner_task", "release_unblocked_owner_task"]
    assert queued[0][1] == (str(owner.id),)
