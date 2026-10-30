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


# --- Undoing, and following one change -----------------------------------------


def _applied(db: Session, log: ActionLog) -> ActionLog:
    log.status = ActionStatus.APPLIED
    log.dry_run = False
    db.commit()
    return log


def test_a_delete_is_never_offered_for_undoing(
    db: Session, queued: list, live: None
) -> None:
    owner, _ = _owner(db)
    deleted = _applied(
        db,
        actions.request(
            db,
            user=owner,
            ask=actions.Delete(level=ManagedLevel.ADSET, external_id="s_1"),
        ),
    )

    assert actions.undoing(deleted) is None
    with pytest.raises(NothingToRevert):
        actions.revert(db, user=owner, log_id=str(deleted.id))


def _two_budgets(db: Session, owner: User, campaign: Campaign) -> list[ActionLog]:
    made = []
    for before, after in ((100_000, 150_000), (150_000, 200_000)):
        campaign.daily_budget_minor = before
        db.commit()
        made.append(
            _applied(
                db,
                actions.request(
                    db,
                    user=owner,
                    ask=actions.Budget(
                        level=ManagedLevel.CAMPAIGN,
                        external_id="c_1",
                        daily_budget_minor=after,
                    ),
                ),
            )
        )
    campaign.daily_budget_minor = 200_000
    db.commit()
    return made


def test_only_the_latest_change_of_a_kind_is_undone(
    db: Session, queued: list, live: None
) -> None:
    owner, campaign = _owner(db)
    older, newer = _two_budgets(db, owner, campaign)

    assert actions.revertible(db, [older, newer]) == {newer.id}
    with pytest.raises(NothingToRevert):
        actions.revert(db, user=owner, log_id=str(older.id))
    back = actions.revert(db, user=owner, log_id=str(newer.id))
    assert back.request_payload["daily_budget_minor"] == 150_000


def _headers(owner: User) -> dict[str, str]:
    from app.common import tokens

    token = tokens.issue(subject=str(owner.id), kind="access", now=utcnow())
    return {"Authorization": f"Bearer {token}"}


def test_the_history_offers_undo_only_on_the_latest(
    client: Any, db: Session, queued: list, live: None
) -> None:
    owner, campaign = _owner(db)
    older, newer = _two_budgets(db, owner, campaign)

    rows = client.get(
        f"/api/v1/campaigns/{campaign.id}/history", headers=_headers(owner)
    ).json()["history"]

    offered = {row["log"]["id"]: row["log"]["revertible"] for row in rows}
    assert offered == {str(older.id): False, str(newer.id): True}


def test_one_change_is_followed_by_its_id(client: Any, db: Session) -> None:
    owner, _ = _owner(db)
    log = actions.request(
        db,
        user=owner,
        ask=actions.Pause(level=ManagedLevel.CAMPAIGN, external_id="c_1"),
    )
    db.commit()
    path = f"/api/v1/campaigns/actions/{log.id}"

    pending = client.get(path, headers=_headers(owner))
    log.status = ActionStatus.FAILED
    log.error_code = "learning"
    db.commit()
    failed = client.get(path, headers=_headers(owner)).json()

    assert pending.status_code == 200, pending.text
    assert pending.json()["status"] == "pending" and pending.json()["polling"] is True
    assert pending.json()["target"] == {
        "level": "campaign",
        "external_id": "c_1",
        "name": "Bahor",
        "provider": "meta",
    }
    assert failed["polling"] is False
    assert failed["error_message"].startswith("Guruh hali o'rganmoqda")
    assert (
        client.get(
            "/api/v1/campaigns/actions/00000000-0000-0000-0000-000000000000",
            headers=_headers(owner),
        ).status_code
        == 404
    )
