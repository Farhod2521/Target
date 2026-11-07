"""TZ 4: a running campaign's name, changed from the cabinet.

Campaigns only, never empty, at most 100 characters, sent to Meta through
the same change log as every other write: history, undo and the mirror
follow from that.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from adskit.dto import ActionResult, StatusDTO
from adskit.refs import ExternalRef
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads import actions
from app.modules.ads.actions import executor
from app.modules.ads.actions.specs import undoing
from app.modules.ads.constants import LAUNCH_NAME_MAX
from app.modules.ads.models import Campaign
from app.modules.ads.services import manage
from app.modules.audit.constants import ActionType
from app.modules.audit.models import ActionLog
from app.modules.billing.services import start_trial
from tests.pg.test_ads_manage import _mirror
from tests.pg.test_cabinet_flows import _cabinet


def _signed_in(client: TestClient, db: Session) -> tuple[dict, User, Campaign]:
    from tests.pg.conftest import sign_up

    headers = sign_up(client)
    owner = db.scalar(select(User).order_by(User.date_joined.desc()))
    account, page = _cabinet(db, owner)
    page.is_current = page.is_active = True
    account.is_active = account.is_current = True
    db.commit()
    start_trial(db, user=owner, now=utcnow())
    db.commit()
    return headers, owner, _mirror(db, owner, account.id)


def _rename(client: TestClient, campaign: Campaign, headers: dict, name: str) -> Any:
    return client.post(
        f"/api/v1/campaigns/{campaign.id}/name", json={"name": name}, headers=headers
    )


def test_a_new_name_goes_out_as_a_change(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, _owner, campaign = _signed_in(client, db)

    answer = _rename(client, campaign, headers, "  Kuzgi   qabul ")

    assert answer.status_code == 200, answer.text
    assert answer.json()["action"]["status"] == "pending"
    log = db.scalar(select(ActionLog).where(ActionLog.action == ActionType.NAME_SET))
    assert log is not None
    assert log.request_payload["name"] == "Kuzgi qabul"
    assert log.previous_state["name"] == "Bahor"
    assert queued and queued[-1][0].endswith("apply_change_task")


@pytest.mark.parametrize("name", ["", "   ", "x" * (LAUNCH_NAME_MAX + 1)])
def test_an_empty_or_long_name_is_refused_under_the_field(
    client: TestClient, db: Session, queued: list, name: str
) -> None:
    headers, _owner, campaign = _signed_in(client, db)

    answer = _rename(client, campaign, headers, name)

    assert answer.status_code == 422, answer.text
    assert "name" in answer.text
    assert db.scalar(select(ActionLog)) is None


def test_the_longest_name_allowed_is_taken(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, _owner, campaign = _signed_in(client, db)

    answer = _rename(client, campaign, headers, "x" * LAUNCH_NAME_MAX)

    assert answer.status_code == 200, answer.text


def test_the_same_name_is_not_sent(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, _owner, campaign = _signed_in(client, db)

    answer = _rename(client, campaign, headers, "Bahor")

    assert answer.status_code == 400, answer.text
    assert db.scalar(select(ActionLog)) is None


def test_a_second_name_waits_for_the_first(
    client: TestClient, db: Session, queued: list
) -> None:
    headers, _owner, campaign = _signed_in(client, db)

    assert _rename(client, campaign, headers, "Birinchi").status_code == 200
    second = _rename(client, campaign, headers, "Ikkinchi")

    assert second.status_code == 400, second.text
    assert second.json()["code"] == "change_in_flight"


def test_another_owner_s_campaign_is_not_found(
    client: TestClient, db: Session, queued: list
) -> None:
    from tests.pg.conftest import sign_up

    _headers, _owner, campaign = _signed_in(client, db)
    stranger = sign_up(client, email="stranger@example.com")

    assert _rename(client, campaign, stranger, "Meniki").status_code == 404


class Renamed:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def get_status(self, *, ref: ExternalRef, token: str) -> StatusDTO:
        return StatusDTO(ref=ref, status="ACTIVE", delivery="active")

    def set_name(self, *, ref: ExternalRef, name: str, **_: Any) -> ActionResult:
        self.sent.append(name)
        return ActionResult(ok=True, ref=ref, applied={"name": name}, dry_run=False)


def test_meta_is_sent_the_name_and_the_mirror_and_history_keep_it(
    client: TestClient, db: Session, queued: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, _owner, campaign = _signed_in(client, db)
    port = Renamed()
    monkeypatch.setattr(
        executor,
        "registry",
        SimpleNamespace(get=lambda _: SimpleNamespace(campaigns=port)),
    )
    account = campaign.ad_account
    monkeypatch.setattr(
        executor, "target_account_and_token", lambda **_: (account, "token")
    )
    assert _rename(client, campaign, headers, "Kuzgi qabul").status_code == 200
    log = db.scalar(select(ActionLog).where(ActionLog.action == ActionType.NAME_SET))
    assert log is not None

    assert manage.apply_change(db, log_id=str(log.id)) == "applied"

    assert port.sent == ["Kuzgi qabul"]
    db.expire_all()
    assert db.get(Campaign, campaign.id).name == "Kuzgi qabul"
    history = client.get(f"/api/v1/campaigns/{campaign.id}", headers=headers).json()
    assert any("Nom" in row["text"] for row in history["history"]), history["history"]
    undo = undoing(db.get(ActionLog, log.id))
    assert undo == actions.Rename(external_id="c_1", name="Bahor")
