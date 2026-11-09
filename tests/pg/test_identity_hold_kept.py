"""Meta's identity hold (31/3858385) leaves what was made at Meta, paused."""

from datetime import timedelta

import pytest
from metaads import PROVIDER
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.selectors.launches import stranded_launches
from app.modules.ads.services import creation
from tests.pg.test_ads_manage import _owner_with_account

REFS = {"campaign": "c_1", "adset": ["s_1"]}


@pytest.fixture
def removed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(
        "app.modules.ads.services.rollback.rollback_launch",
        lambda db, *, launch, **_k: calls.append(str(launch.id)) or 0,
    )
    monkeypatch.setattr(creation, "_explain_later", lambda *_a, **_k: None)
    monkeypatch.setattr(creation, "fail_log", lambda *_a, **_k: None)
    return calls


def _launch(db: Session, **fields: object) -> CampaignLaunch:
    owner, account = _owner_with_account(db)
    launch = CampaignLaunch(
        owner_id=owner.id,
        ad_account_id=account.id,
        provider=PROVIDER,
        status="creating",
        created_refs=REFS,
        **fields,
    )
    db.add(launch)
    db.commit()
    return launch


def _undo(db: Session, launch: CampaignLaunch, code: str) -> str:
    return creation._undo(
        db,
        launch=launch,
        log_id="",
        token="t",
        page_token="p",
        dry_run=False,
        code=code,
        message="held",
    )


def test_the_hold_fails_the_launch_and_deletes_nothing(
    db: Session, removed: list[str]
) -> None:
    launch = _launch(db)

    assert _undo(db, launch, "account_action") == "account_action"

    db.refresh(launch)
    assert launch.status == "failed"
    assert launch.error_code == "account_action"
    assert launch.created_refs == REFS
    assert removed == []


def test_any_other_refusal_still_deletes(db: Session, removed: list[str]) -> None:
    launch = _launch(db)

    assert _undo(db, launch, "refused") == "rolled_back"

    assert removed == [str(launch.id)]


@pytest.mark.parametrize(
    ("code", "swept"), [("account_action", False), ("refused", True)]
)
def test_the_hourly_sweep_leaves_only_a_held_launch_alone(
    db: Session, code: str, swept: bool
) -> None:
    finished = utcnow() - timedelta(hours=2)
    launch = _launch(db, error_code=code, finished_at=finished)
    launch.status = "failed"
    db.commit()
    db.query(CampaignLaunch).filter_by(id=launch.id).update(
        {"updated_at": finished}, synchronize_session=False
    )
    db.commit()

    assert (launch in stranded_launches(db, now=utcnow())) is swept
