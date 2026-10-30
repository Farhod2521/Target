"""One way in for every change: a preview that only checks, a request that opens.

The campaigns screen, the assistant's button, the agent and the lapse sweep
all ask for a change through :mod:`app.modules.ads.actions`. A preview must
refuse exactly what the request would, and open nothing.
"""

from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads import actions
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.exceptions import AlreadyInState, NothingToRevert
from app.modules.ads.models import Campaign
from app.modules.audit.constants import ActionStatus
from app.modules.audit.models import ActionLog
from tests.pg.test_ads_manage import _mirror
from tests.pg.test_cabinet_flows import _cabinet


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> None:
    """A paying owner: the subscription check is not what these tests are about."""
    import app.modules.billing.services as billing

    monkeypatch.setattr(billing, "require_live_subscription", lambda *_a, **_k: None)


def _owner(db: Session) -> tuple[User, Campaign]:
    owner = User(
        email="actions@example.com", full_name="A", password="!", date_joined=utcnow()
    )
    db.add(owner)
    db.commit()
    account, page = _cabinet(db, owner)
    page.is_current = page.is_active = True
    account.is_active = account.is_current = True
    db.commit()
    return owner, _mirror(db, owner, account.id)


def _logs(db: Session) -> int:
    return db.scalar(select(func.count(ActionLog.id))) or 0


def test_a_preview_checks_and_opens_nothing(db: Session, queued: list) -> None:
    owner, _ = _owner(db)
    ask = actions.Pause(level=ManagedLevel.CAMPAIGN, external_id="c_1")

    plan = actions.preview(db, user=owner, ask=ask)

    assert plan.action == "pause"
    assert plan.provider == "meta"
    assert plan.requested["status"] == "paused"
    assert _logs(db) == 0 and not queued


def test_a_preview_refuses_what_the_request_refuses(db: Session) -> None:
    owner, campaign = _owner(db)
    campaign.delivery = "paused"
    db.commit()
    ask = actions.Pause(level=ManagedLevel.CAMPAIGN, external_id="c_1")

    with pytest.raises(AlreadyInState):
        actions.preview(db, user=owner, ask=ask)
    with pytest.raises(AlreadyInState):
        actions.request(db, user=owner, ask=ask)
    db.rollback()
    assert _logs(db) == 0


def test_a_request_opens_the_change_and_sends_it(
    db: Session, queued: list, live: None
) -> None:
    owner, campaign = _owner(db)
    campaign.daily_budget_minor = 100_000
    db.commit()

    log = actions.request(
        db,
        user=owner,
        ask=actions.Budget(
            level=ManagedLevel.CAMPAIGN, external_id="c_1", daily_budget_minor=150_000
        ),
    )
    db.commit()

    assert log.status == ActionStatus.PENDING and log.action == "budget_up"
    assert log.request_payload["daily_budget_minor"] == 150_000
    assert log.target_provider == "meta"
    assert queued and queued[-1][0].endswith("apply_change_task")


def test_a_delete_goes_to_its_own_worker(db: Session, queued: list, live: None) -> None:
    owner, _ = _owner(db)

    log = actions.request(
        db,
        user=owner,
        ask=actions.Delete(level=ManagedLevel.CAMPAIGN, external_id="c_1"),
    )
    db.commit()

    assert log.action == "delete_campaign"
    assert queued[-1][0].endswith("apply_delete_task")


def test_a_revert_asks_for_the_state_before(
    db: Session, queued: list, live: None
) -> None:
    owner, campaign = _owner(db)
    paused = actions.request(
        db,
        user=owner,
        ask=actions.Pause(level=ManagedLevel.CAMPAIGN, external_id="c_1"),
    )
    paused.status = ActionStatus.APPLIED
    paused.dry_run = False
    campaign.delivery = "paused"
    db.commit()

    back = actions.revert(db, user=owner, log_id=str(paused.id))
    db.commit()

    assert back.action == "resume"
    assert back.request_payload["reverts"] == str(paused.id)
    with pytest.raises(NothingToRevert):
        actions.revert(db, user=owner, log_id="not-a-log")


def test_every_kind_of_ask_has_a_spec() -> None:
    asks: set[Any] = set(actions.Ask.__args__)  # type: ignore[attr-defined]

    assert asks == set(actions.SPECS)
