"""Writes to Meta and what the mirror keeps of them, on Django's own foreign keys.

The production database was built by Django: ``adsets.campaign_id`` and
``ads.adset_id`` are NO ACTION, DEFERRABLE INITIALLY DEFERRED, because
Django's CASCADE lived in its ORM. ``tests/pg/conftest.py`` builds every
foreign key that way.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from adskit.dto import AccountStateDTO, ActionResult, StatusDTO
from adskit.errors import NotFound, PermissionDenied
from adskit.refs import ExternalRef
from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.common import tokens
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.actions import executor
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.ads.services import manage, mirror, removal, swap
from app.modules.audit.constants import ActionStatus, ActionType
from app.modules.audit.models import ActionLog
from app.modules.integrations.models import AdAccount
from tests.pg.test_ads_manage import _mirror
from tests.pg.test_cabinet_flows import _cabinet


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


class StartedCampaigns(FakeCampaigns):
    """Meta after a start: what was held by the campaign delivers now."""

    def __init__(self) -> None:
        super().__init__(ok=True)
        self.delivery = "paused"

    def get_status(self, *, ref: ExternalRef, token: str) -> StatusDTO:
        return StatusDTO(ref=ref, status="ACTIVE", delivery=self.delivery)

    def set_status(self, *, ref: ExternalRef, **_: Any) -> ActionResult:
        self.delivery = "active"
        return self._result(ref)

    def read_objects(self, *, refs: Any, **_: Any) -> SimpleNamespace:
        return SimpleNamespace(
            adsets=(),
            ads=tuple(
                SimpleNamespace(
                    ref=ref,
                    status="ACTIVE",
                    effective_status="ACTIVE",
                    delivery="active",
                )
                for ref in refs
                if ref.level == "ad"
            ),
        )


def test_a_start_above_is_read_back_below(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, account = _owner_with_mirror(db)
    port = StartedCampaigns()
    monkeypatch.setattr(
        executor,
        "registry",
        SimpleNamespace(get=lambda _: SimpleNamespace(campaigns=port)),
    )
    _signed_in(monkeypatch, executor, account)
    ad = db.scalars(select(Ad)).one()
    ad.delivery = "paused_above"
    db.scalars(select(Campaign)).one().delivery = "paused"
    db.commit()
    log_id = _log(db, owner, ActionType.RESUME, ManagedLevel.CAMPAIGN, "c_1")

    assert manage.apply_change(db, log_id=log_id) == "applied"

    db.expire_all()
    assert db.scalars(select(Ad)).one().delivery == "active"


def test_a_sync_forgets_a_campaign_with_everything_under_it(
    db: Session,
) -> None:
    _owner, account = _owner_with_mirror(db)

    mirror.store_everything(db, ad_account=account, campaigns=[], adsets=[], ads=[])

    assert (_count(db, Campaign), _count(db, AdSet), _count(db, Ad)) == (0, 0, 0)


def test_a_deleted_campaign_takes_its_groups_and_ads_with_it(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, account = _owner_with_mirror(db)
    _provider(monkeypatch, executor, ok=True)
    _signed_in(monkeypatch, executor, account)
    log_id = _log(db, owner, ActionType.DELETE_CAMPAIGN, ManagedLevel.CAMPAIGN, "c_1")

    assert removal.apply_delete(db, log_id=log_id) == "applied"

    db.expire_all()
    assert db.get(ActionLog, log_id).status == ActionStatus.APPLIED
    assert (_count(db, Campaign), _count(db, AdSet), _count(db, Ad)) == (0, 0, 0)


def test_a_delete_meta_refused_quietly_keeps_the_mirror(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, account = _owner_with_mirror(db)
    _provider(monkeypatch, executor, ok=False)
    _signed_in(monkeypatch, executor, account)
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
    _signed_in(monkeypatch, executor, account)

    def broken(_: str) -> Any:
        raise KeyError("no port")

    monkeypatch.setattr(executor, "registry", SimpleNamespace(get=broken))
    log_id = _log(db, owner, ActionType.DELETE_AD, ManagedLevel.AD, "a_1")

    assert removal.apply_delete(db, log_id=log_id) == "failed"

    db.expire_all()
    log = db.get(ActionLog, log_id)
    assert (log.status, log.error_code) == (ActionStatus.FAILED, "unknown")


def test_a_change_meta_refused_quietly_is_not_recorded_as_applied(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, account = _owner_with_mirror(db)
    _provider(monkeypatch, executor, ok=False)
    _signed_in(monkeypatch, executor, account)
    log_id = _log(db, owner, ActionType.PAUSE, ManagedLevel.CAMPAIGN, "c_1")

    assert manage.apply_change(db, log_id=log_id) == "failed"

    db.expire_all()
    log = db.get(ActionLog, log_id)
    assert (log.status, log.error_code) == (ActionStatus.FAILED, "not_applied")


def test_a_creative_swap_that_lands_is_saved(
    db: Session, pg_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.ads import selectors

    owner, account = _owner_with_mirror(db)
    _provider(monkeypatch, executor, ok=True)
    monkeypatch.setattr(
        executor, "target_account_and_token", lambda **_: (account, "t")
    )
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


class RefusingCampaigns(FakeCampaigns):
    """Meta refusing the delete, and reading the account when asked."""

    def __init__(self, error: Exception, *, standing: str = "active") -> None:
        super().__init__(ok=True)
        self.error = error
        self.standing = standing
        self.reads = 0

    def delete(self, *, ref: ExternalRef, **_: Any) -> ActionResult:
        raise self.error

    def set_status(self, *, ref: ExternalRef, **_: Any) -> ActionResult:
        raise self.error

    def read_account(self, *, account: Any, token: str) -> AccountStateDTO:
        self.reads += 1
        return AccountStateDTO(ref=account, standing=self.standing)


def _refusing(monkeypatch: pytest.MonkeyPatch, module: Any, port: Any) -> None:
    monkeypatch.setattr(
        module,
        "registry",
        SimpleNamespace(get=lambda _: SimpleNamespace(campaigns=port)),
    )


def test_a_refused_delete_on_a_blocked_account_says_so(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, account = _owner_with_mirror(db)
    error = PermissionDenied(
        "(#200) no permission",
        code="200",
        user_title="Hisob to'xtatilgan",
        user_message="To'lovni yangilang.",
    )
    port = RefusingCampaigns(error, standing="disabled_payment")
    _refusing(monkeypatch, executor, port)
    _signed_in(monkeypatch, executor, account)
    log_id = _log(db, owner, ActionType.DELETE_ADSET, ManagedLevel.ADSET, "s_1")

    assert removal.apply_delete(db, log_id=log_id) == "failed"

    db.expire_all()
    log = db.get(ActionLog, log_id)
    assert port.reads == 1
    assert db.get(AdAccount, account.id).standing == "disabled_payment"
    assert log.error_code == "account_blocked"
    assert log.error_message == "[200] (#200) no permission"
    assert log.result_payload["user_title"] == "Hisob to'xtatilgan"
    assert log.result_payload["user_message"] == "To'lovni yangilang."


def test_a_refused_change_is_named_by_its_kind(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, account = _owner_with_mirror(db)
    port = RefusingCampaigns(NotFound("gone", code="100"))
    _refusing(monkeypatch, executor, port)
    _signed_in(monkeypatch, executor, account)
    log_id = _log(db, owner, ActionType.PAUSE, ManagedLevel.ADSET, "s_1")

    assert manage.apply_change(db, log_id=log_id) == "failed"

    db.expire_all()
    log = db.get(ActionLog, log_id)
    assert (log.error_code, port.reads) == ("not_found", 0)


def test_the_screen_says_why_a_delete_did_not_go_through(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = User(
        email="ads@example.com", full_name="Ads", password="!", date_joined=utcnow()
    )
    db.add(owner)
    db.commit()
    account, page = _cabinet(db, owner)
    page.is_current = page.is_active = True
    account.is_active = account.is_current = True
    db.commit()
    _mirror(db, owner, account.id)
    port = RefusingCampaigns(
        PermissionDenied("denied", code="200", user_message="Rol bering.")
    )
    _refusing(monkeypatch, executor, port)
    _signed_in(monkeypatch, executor, account)
    log_id = _log(db, owner, ActionType.DELETE_ADSET, ManagedLevel.ADSET, "s_1")
    removal.apply_delete(db, log_id=log_id)
    token = tokens.issue(subject=str(owner.id), kind="access", now=utcnow())

    state = client.get(
        "/api/v1/campaigns/manage/adset/s_1/state",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert state.status_code == 200, state.text
    failure = state.json()["failure"]
    assert failure["text"].endswith("Rol bering.")


# --- An audience is replaced only over the one that was edited ---------------
SEEN = {
    "geo_locations": {"cities": [{"key": "2019233"}]},
    "age_min": 25,
    "age_max": 45,
}


class FakeAudiences:
    """Meta's ad set as it reads now, and what a write leaves behind."""

    def __init__(self, *, live: dict[str, Any] | Exception) -> None:
        self.live = live
        self.written: list[dict[str, Any]] = []

    def read_targeting(self, *, ref: ExternalRef, token: str) -> dict[str, Any]:
        if isinstance(self.live, Exception):
            raise self.live
        return self.live

    def same_targeting(self, first: dict[str, Any], second: dict[str, Any]) -> bool:
        from metaads.audience_diff import same_audience

        return same_audience(first, second)

    def apply(
        self, *, ref: ExternalRef, targeting: dict[str, Any], **_: Any
    ) -> ActionResult:
        self.written.append(targeting)
        held = {
            **targeting,
            "geo_locations": {"cities": [{"key": "2019233", "name": "Tashkent"}]},
        }
        return ActionResult(
            ok=True, ref=ref, applied={"targeting": held}, dropped={}, dry_run=False
        )


def _audience_change(
    db: Session, monkeypatch: pytest.MonkeyPatch, *, live: dict[str, Any] | Exception
) -> tuple[FakeAudiences, str]:
    owner, account = _owner_with_mirror(db)
    adset = db.scalar(select(AdSet).where(AdSet.external_id == "s_1"))
    assert adset is not None
    adset.targeting_raw = SEEN
    db.commit()
    audiences = FakeAudiences(live=live)
    monkeypatch.setattr(
        executor,
        "registry",
        SimpleNamespace(
            get=lambda _: SimpleNamespace(
                campaigns=FakeCampaigns(ok=True), audiences=audiences
            )
        ),
    )
    monkeypatch.setattr(manage.settings, "ads_dry_run", False)
    _signed_in(monkeypatch, executor, account)
    log = manage.open_log(
        db,
        owner=owner,
        action=ActionType.TARGETING_SWAP,
        provider=PROVIDER,
        level=ManagedLevel.ADSET,
        external_id="s_1",
        requested={"targeting": {**SEEN, "age_min": 30}},
        previous={"targeting": SEEN},
        dry_run=False,
    )
    db.commit()
    return audiences, str(log.id)


def test_an_audience_changed_in_ads_manager_is_not_written_over(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The spec goes out whole: written over a newer audience, it would undo
    whatever was changed there. The mirror takes Meta's, the owner looks again."""
    elsewhere = {**SEEN, "age_max": 35}
    audiences, log_id = _audience_change(db, monkeypatch, live=elsewhere)

    assert manage.apply_change(db, log_id=log_id) == "refused"

    db.expire_all()
    log = db.get(ActionLog, log_id)
    assert (log.status, log.error_code) == (ActionStatus.FAILED, "changed_elsewhere")
    assert audiences.written == []
    adset = db.scalar(select(AdSet).where(AdSet.external_id == "s_1"))
    assert adset.targeting_raw == elsewhere


def test_meta_spelling_the_same_audience_its_own_way_is_no_change(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Meta expands a city key into a whole location and adds defaults; that is
    the same audience, and the write goes ahead. The mirror then keeps what
    Meta holds, not what was sent."""
    spelled = {
        **SEEN,
        "geo_locations": {"cities": [{"key": "2019233", "name": "Tashkent"}]},
        "targeting_automation": {"advantage_audience": 0},
    }
    audiences, log_id = _audience_change(db, monkeypatch, live=spelled)

    assert manage.apply_change(db, log_id=log_id) == "applied"

    db.expire_all()
    assert len(audiences.written) == 1
    adset = db.scalar(select(AdSet).where(AdSet.external_id == "s_1"))
    assert adset.targeting_raw["geo_locations"]["cities"][0]["name"] == "Tashkent"
    assert adset.targeting_raw["age_min"] == 30


def test_an_audience_that_cannot_be_read_is_not_replaced(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    audiences, log_id = _audience_change(db, monkeypatch, live=NotFound("gone"))

    assert manage.apply_change(db, log_id=log_id) == "refused"

    db.expire_all()
    log = db.get(ActionLog, log_id)
    assert log.error_code == "read"
    assert audiences.written == []


def test_a_refused_creative_swap_is_explained_like_any_other_refusal(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The swap kept Meta's raw code ("[200]") where every other write kept
    the screen's word, so its failure read as Meta's bare refusal."""
    from app.modules.ads import selectors

    owner, account = _owner_with_mirror(db)
    _refusing(monkeypatch, executor, RefusingCampaigns(KeyError("unused")))
    _signed_in(monkeypatch, executor, account)
    monkeypatch.setattr(
        selectors, "creative_of", lambda *_, **__: SimpleNamespace(story_raw={"a": 1})
    )
    monkeypatch.setattr(swap, "swap_refusal", lambda *_, **__: "")

    def refused(**_: Any) -> ActionResult:
        raise PermissionDenied(
            "(#200) Permissions error",
            code="200",
            user_title="Ruxsat yo'q",
            user_message="Sahifa egasidan ruxsat so'rang.",
        )

    monkeypatch.setattr(swap, "_swap", refused)
    log_id = _log(db, owner, ActionType.CREATIVE_SWAP, ManagedLevel.AD, "a_1")

    assert swap.apply_swap(db, log_id=log_id) == "failed"

    db.expire_all()
    log = db.get(ActionLog, log_id)
    assert log.error_code == "permission"
    assert log.result_payload["user_title"] == "Ruxsat yo'q"
