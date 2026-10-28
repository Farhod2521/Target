"""Writes to Meta and what the mirror keeps of them, on Django's own foreign keys.

The production database was built by Django: ``adsets.campaign_id`` and
``ads.adset_id`` are NO ACTION, DEFERRABLE INITIALLY DEFERRED, because
Django's CASCADE lived in its ORM. ``create_all`` would make them CASCADE
and hide every delete that forgets the rows beneath it, so these tests put
Django's constraints back first.
"""

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from adskit.dto import ActionResult, StatusDTO
from adskit.refs import ExternalRef
from metaads import PROVIDER
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.ads.services import manage, mirror, removal, swap
from app.modules.audit.constants import ActionStatus, ActionType
from app.modules.audit.models import ActionLog
from app.modules.integrations.models import AdAccount
from tests.pg.test_ads_manage import _mirror
from tests.pg.test_cabinet_flows import _cabinet

LINKS = [("adsets", "campaign_id", "campaigns"), ("ads", "adset_id", "adsets")]


def _relink(engine: Engine, *, cascade: bool) -> None:
    rule = "ON DELETE CASCADE" if cascade else "DEFERRABLE INITIALLY DEFERRED"
    with engine.begin() as conn:
        for table, column, parent in LINKS:
            name = conn.execute(
                text(
                    "SELECT conname FROM pg_constraint WHERE contype = 'f' "
                    "AND conrelid = CAST(:t AS regclass) "
                    "AND confrelid = CAST(:p AS regclass)"
                ),
                {"t": table, "p": parent},
            ).scalar_one()
            conn.execute(text(f'ALTER TABLE {table} DROP CONSTRAINT "{name}"'))
            conn.execute(
                text(
                    f'ALTER TABLE {table} ADD CONSTRAINT "{name}" FOREIGN KEY '
                    f"({column}) REFERENCES {parent} (id) {rule}"
                )
            )


@pytest.fixture
def django_links(pg_engine: Engine, db: Session) -> Iterator[None]:
    _relink(pg_engine, cascade=False)
    yield
    # The test's session still holds its locks; ALTER TABLE would wait on it.
    db.close()
    _relink(pg_engine, cascade=True)


def _owner_with_mirror(db: Session) -> tuple[User, AdAccount]:
    owner = User(
        email="ads@example.com", full_name="Ads", password="!", date_joined=utcnow()
    )
    db.add(owner)
    db.commit()
    account, _page = _cabinet(db, owner)
    _mirror(db, owner, account.id)
    return owner, account


def _count(db: Session, model: Any) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def _log(db: Session, owner: User, action: str, level: str, external_id: str) -> str:
    log = manage.open_log(
        db,
        owner=owner,
        action=action,
        provider=PROVIDER,
        level=level,
        external_id=external_id,
        requested={"status": "deleted"},
        previous={},
        dry_run=False,
    )
    db.commit()
    return str(log.id)


class FakeCampaigns:
    def __init__(self, *, ok: bool) -> None:
        self.ok = ok

    def _result(self, ref: ExternalRef) -> ActionResult:
        return ActionResult(
            ok=self.ok, ref=ref, dry_run=False, raw_response={"success": self.ok}
        )

    def get_status(self, *, ref: ExternalRef, token: str) -> StatusDTO:
        return StatusDTO(ref=ref, status="ACTIVE", delivery="active")

    def set_status(self, *, ref: ExternalRef, **_: Any) -> ActionResult:
        return self._result(ref)

    def delete(self, *, ref: ExternalRef, **_: Any) -> ActionResult:
        return self._result(ref)


def _provider(monkeypatch: pytest.MonkeyPatch, module: Any, *, ok: bool) -> None:
    port = FakeCampaigns(ok=ok)
    monkeypatch.setattr(
        module,
        "registry",
        SimpleNamespace(get=lambda _: SimpleNamespace(campaigns=port)),
    )


def _signed_in(
    monkeypatch: pytest.MonkeyPatch, module: Any, account: AdAccount
) -> None:
    monkeypatch.setattr(
        module, "target_account_and_token", lambda **_: (account, "token")
    )


def test_a_sync_forgets_a_campaign_with_everything_under_it(
    db: Session, django_links: None
) -> None:
    _owner, account = _owner_with_mirror(db)

    mirror.store_everything(db, ad_account=account, campaigns=[], adsets=[], ads=[])

    assert (_count(db, Campaign), _count(db, AdSet), _count(db, Ad)) == (0, 0, 0)


def test_a_deleted_campaign_takes_its_groups_and_ads_with_it(
    db: Session, django_links: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, account = _owner_with_mirror(db)
    _provider(monkeypatch, removal, ok=True)
    _signed_in(monkeypatch, removal, account)
    log_id = _log(db, owner, ActionType.DELETE_CAMPAIGN, ManagedLevel.CAMPAIGN, "c_1")

    assert removal.apply_delete(db, log_id=log_id) == "applied"

    db.expire_all()
    assert db.get(ActionLog, log_id).status == ActionStatus.APPLIED
    assert (_count(db, Campaign), _count(db, AdSet), _count(db, Ad)) == (0, 0, 0)


def test_a_delete_meta_refused_quietly_keeps_the_mirror(
    db: Session, django_links: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, account = _owner_with_mirror(db)
    _provider(monkeypatch, removal, ok=False)
    _signed_in(monkeypatch, removal, account)
    log_id = _log(db, owner, ActionType.DELETE_ADSET, ManagedLevel.ADSET, "s_1")

    assert removal.apply_delete(db, log_id=log_id) == "failed"

    db.expire_all()
    log = db.get(ActionLog, log_id)
    assert (log.status, log.error_code) == (ActionStatus.FAILED, "not_applied")
    assert (_count(db, Campaign), _count(db, AdSet), _count(db, Ad)) == (1, 1, 1)


def test_an_unexpected_error_in_a_delete_does_not_leave_it_pending(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, account = _owner_with_mirror(db)
    _signed_in(monkeypatch, removal, account)

    def broken(_: str) -> Any:
        raise KeyError("no port")

    monkeypatch.setattr(removal, "registry", SimpleNamespace(get=broken))
    log_id = _log(db, owner, ActionType.DELETE_AD, ManagedLevel.AD, "a_1")

    assert removal.apply_delete(db, log_id=log_id) == "failed"

    db.expire_all()
    log = db.get(ActionLog, log_id)
    assert (log.status, log.error_code) == (ActionStatus.FAILED, "unknown")


def test_a_change_meta_refused_quietly_is_not_recorded_as_applied(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, account = _owner_with_mirror(db)
    _provider(monkeypatch, manage, ok=False)
    _signed_in(monkeypatch, manage, account)
    log_id = _log(db, owner, ActionType.PAUSE, ManagedLevel.CAMPAIGN, "c_1")

    assert manage.apply_change(db, log_id=log_id) == "failed"

    db.expire_all()
    log = db.get(ActionLog, log_id)
    assert (log.status, log.error_code) == (ActionStatus.FAILED, "not_applied")


def test_a_creative_swap_that_lands_is_saved(
    db: Session, pg_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.ads import selectors
    from app.modules.ads.services import access

    owner, account = _owner_with_mirror(db)
    _provider(monkeypatch, swap, ok=True)
    monkeypatch.setattr(access, "target_account_and_token", lambda **_: (account, "t"))
    monkeypatch.setattr(
        selectors, "creative_of", lambda *_, **__: SimpleNamespace(story_raw={"a": 1})
    )
    monkeypatch.setattr(swap, "swap_refusal", lambda *_, **__: "")
    monkeypatch.setattr(
        swap,
        "_swap",
        lambda **kw: ActionResult(ok=True, ref=kw["ref"], dry_run=True),
    )
    log_id = _log(db, owner, ActionType.CREATIVE_SWAP, ManagedLevel.AD, "a_1")

    assert swap.apply_swap(db, log_id=log_id) == "applied"
    db.close()

    with pg_factory() as fresh:
        assert fresh.get(ActionLog, log_id).status == ActionStatus.APPLIED
