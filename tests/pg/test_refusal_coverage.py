"""A refusal reaches the owner from every press, and after the page was closed."""

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.models import Ad, AdCreative, Campaign
from app.modules.ads.selectors.rejections import review_key
from app.modules.ads.services import mirror
from app.modules.audit.constants import ActionStatus, ActionType
from app.modules.audit.models import ActionLog
from app.modules.billing.services import start_trial
from app.modules.chat.constants import REFUSAL_LOCK
from app.modules.chat.models import RefusalAnswer
from app.modules.chat.services.refused import explain_rejections
from tests.pg.conftest import sign_up
from tests.pg.test_ads_editing import _running
from tests.pg.test_cabinet_flows import _cabinet

BLAMED = {"user_title": "Byudjet kam", "user_message": "Kamida 1$ kiriting."}
KEPT = "Instagram ads can't be created using this Page post."
CAROUSEL = "The selected objective doesn't support ads including carousel."


def _ready(client: Any, db: Session) -> tuple[User, dict[str, str], Campaign]:
    headers = sign_up(client)
    owner = db.scalar(select(User).order_by(User.date_joined.desc()))
    assert owner is not None
    account, page = _cabinet(db, owner)
    page.is_current = page.is_active = True
    account.is_active = account.is_current = True
    db.commit()
    start_trial(db, user=owner, now=utcnow())
    db.commit()
    return owner, headers, _running(db, owner, account)


def _ad(db: Session, campaign: Campaign) -> Ad:
    return campaign.adsets[0].ads[0]


def _failed(db: Session, owner: User, level: str, external_id: str) -> ActionLog:
    log = ActionLog(
        owner_id=owner.id,
        action=ActionType.PAUSE,
        target_provider="meta",
        target_level=level,
        target_external_id=external_id,
        idempotency_key=f"failed:{external_id}",
        status=ActionStatus.FAILED,
        error_code="refused",
        error_message="[100] Invalid parameter",
        result_payload={**BLAMED, "key": "meta:100/1487851"},
    )
    db.add(log)
    db.commit()
    return log


def _turned_down(db: Session, ad: Ad, **said: Any) -> None:
    ad.delivery = "rejected"
    for name, value in said.items():
        setattr(ad, name, value)
    db.commit()


def test_a_failed_change_stays_on_its_row_and_asks_nothing(
    client, db: Session, queued: list
) -> None:  # type: ignore[no-untyped-def]
    owner, headers, campaign = _ready(client, db)
    group = campaign.adsets[0]
    _failed(db, owner, ManagedLevel.ADSET, group.external_id)
    _failed(db, owner, ManagedLevel.AD, group.ads[0].external_id)
    _failed(db, owner, ManagedLevel.CAMPAIGN, campaign.external_id)
    queued.clear()

    tree = client.get(f"/api/v1/campaigns/{campaign.id}/tree", headers=headers).json()
    detail = client.get(f"/api/v1/campaigns/{campaign.id}", headers=headers).json()
    listed = client.get("/api/v1/campaigns", headers=headers).json()
    rows = client.get("/api/v1/campaigns/manager", headers=headers).json()

    shown = [
        tree["groups"][0]["refusal"],
        tree["groups"][0]["ads"][0]["refusal"],
        detail["refusal"],
        listed["campaigns"][0]["refusal"],
        rows["campaigns"][0]["refusal"],
        rows["adsets"][0]["refusal"],
        rows["ads"][0]["refusal"],
    ]
    assert all(found["key"] == "change:meta:100/1487851" for found in shown)
    assert all(found["steps"] and found["explaining"] for found in shown)
    assert tree["groups"][0]["ads"][0]["lastAction"] == "failed"
    assert not [name for name, _ in queued if "explain" in name]


def test_a_row_with_nothing_wrong_says_nothing(
    client, db: Session, queued: list
) -> None:  # type: ignore[no-untyped-def]
    _, headers, campaign = _ready(client, db)

    tree = client.get(f"/api/v1/campaigns/{campaign.id}/tree", headers=headers).json()

    assert tree["groups"][0]["refusal"] is None
    assert tree["groups"][0]["rejection"] is None
    assert tree["groups"][0]["ads"][0]["rejection"] is None


def test_a_refused_advert_reaches_the_campaign_above_it(
    client, db: Session, queued: list
) -> None:  # type: ignore[no-untyped-def]
    _, headers, campaign = _ready(client, db)
    assert not campaign.issue_summary
    _turned_down(
        db,
        _ad(db, campaign),
        review_feedback={"overall": {"Circumventing Systems": "Bu yozuv mumkin emas."}},
    )

    detail = client.get(f"/api/v1/campaigns/{campaign.id}", headers=headers).json()
    tree = client.get(f"/api/v1/campaigns/{campaign.id}/tree", headers=headers).json()
    listed = client.get("/api/v1/campaigns", headers=headers).json()
    rows = client.get("/api/v1/campaigns/manager", headers=headers).json()

    assert "Bu yozuv mumkin emas." in detail["problem"]["text"]
    assert detail["rejection"]["key"].startswith("review:meta:")
    assert detail["rejection"]["providerWords"]
    assert detail["rejection"]["fix"]["url"].endswith(
        f"/manage/ad/{_ad(db, campaign).external_id}/edit/"
    )
    for found in (
        tree["groups"][0]["rejection"],
        tree["groups"][0]["ads"][0]["rejection"],
        listed["campaigns"][0]["rejection"],
        rows["campaigns"][0]["rejection"],
        rows["adsets"][0]["rejection"],
        rows["ads"][0]["rejection"],
    ):
        assert found == detail["rejection"]


def test_a_refused_post_is_told_to_make_another_advert(
    client, db: Session, queued: list
) -> None:  # type: ignore[no-untyped-def]
    owner, headers, campaign = _ready(client, db)
    ad = _ad(db, campaign)
    db.add(
        AdCreative(
            owner_id=owner.id,
            ad_account_id=campaign.ad_account_id,
            provider="meta",
            external_id="cr_post",
            kind="existing_post",
        )
    )
    _turned_down(
        db,
        ad,
        creative_external_id="cr_post",
        issues=[{"code": "1", "summary": KEPT, "message": CAROUSEL}],
        issue_codes=["1"],
        issue_summary=KEPT,
    )

    found = client.get(f"/api/v1/campaigns/{campaign.id}", headers=headers).json()

    rejection = found["rejection"]
    assert CAROUSEL in rejection["providerWords"]
    assert rejection["fix"] is None
    assert any("yangi reklama" in step for step in rejection["steps"])


def test_one_policy_is_one_question_however_many_adverts_break_it(
    client, db: Session, queued: list
) -> None:  # type: ignore[no-untyped-def]
    owner, _, campaign = _ready(client, db)
    ad = _ad(db, campaign)
    _turned_down(db, ad, review_feedback={"overall": {"Policy": "Birinchi."}})
    same = {"overall": {"Policy": "Boshqa so'z bilan."}}
    second = type(ad)(
        owner_id=owner.id,
        provider="meta",
        external_id="a_second",
        adset_id=ad.adset_id,
        name="Ikkinchi",
        status="ACTIVE",
        delivery="rejected",
        review_feedback=same,
        synced_at=utcnow(),
    )
    db.add(second)
    db.commit()
    key = review_key(ad)
    assert key == review_key(second)
    cache.delete(REFUSAL_LOCK.format(key=key))
    queued.clear()

    explain_rejections(db, owner=owner, ads=[ad, second])

    asked = [name for name, _ in queued if name.endswith("explain_action_refusal")]
    assert len(asked) == 1
    cache.delete(REFUSAL_LOCK.format(key=key))


def test_a_kept_answer_is_not_asked_again(client, db: Session, queued: list) -> None:  # type: ignore[no-untyped-def]
    owner, _, campaign = _ready(client, db)
    ad = _ad(db, campaign)
    _turned_down(db, ad, review_feedback={"overall": {"Kept": "Sabab."}})
    db.add(RefusalAnswer(key=review_key(ad), prompt_version="office", answer_uz="Bor."))
    db.commit()
    queued.clear()

    explain_rejections(db, owner=owner, ads=[ad])

    assert not [name for name, _ in queued if "explain" in name]


def test_a_lost_broker_does_not_fail_the_sync(
    client, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    owner, _, campaign = _ready(client, db)
    ad = _ad(db, campaign)
    _turned_down(db, ad, review_feedback={"overall": {"Lost": "Sabab."}})
    cache.delete(REFUSAL_LOCK.format(key=review_key(ad)))

    def lost(**_: Any) -> None:
        raise ConnectionError("no broker")

    monkeypatch.setattr("app.modules.chat.services.refused.explain_action_later", lost)

    mirror._explain_rejections(db, owner=owner, ads=[ad])


def test_presses_left_to_the_worker_answer_their_state(
    client, db: Session, queued: list
) -> None:  # type: ignore[no-untyped-def]
    _, headers, campaign = _ready(client, db)
    ad = _ad(db, campaign)

    saved = client.post(
        f"/api/v1/campaigns/ads/{ad.external_id}/edit",
        json={"message": "Yangi matn"},
        headers=headers,
    )

    assert saved.status_code == 200, saved.text
    assert saved.json()["level"] == "ad"
    assert saved.json()["externalId"] == ad.external_id
    assert saved.json()["pending"] is True


@pytest.mark.parametrize("level", ["campaign", "adset", "ad"])
def test_a_delete_answers_its_state(
    client, db: Session, queued: list, level: str
) -> None:  # type: ignore[no-untyped-def]
    _, headers, campaign = _ready(client, db)
    group = campaign.adsets[0]
    address, external_id = {
        "campaign": (str(campaign.id), campaign.external_id),
        "adset": (f"adsets/{group.external_id}", group.external_id),
        "ad": (f"ads/{group.ads[0].external_id}", group.ads[0].external_id),
    }[level]

    sent = client.delete(f"/api/v1/campaigns/{address}", headers=headers)

    assert sent.status_code == 200, sent.text
    assert sent.json()["level"] == level
    assert sent.json()["externalId"] == external_id
    assert sent.json()["pending"] is True


def test_the_state_of_what_was_deleted_says_so(
    client, db: Session, queued: list
) -> None:  # type: ignore[no-untyped-def]
    owner, headers, _campaign = _ready(client, db)
    db.add(
        ActionLog(
            owner_id=owner.id,
            action=ActionType.DELETE_AD,
            target_provider="meta",
            target_level=ManagedLevel.AD,
            target_external_id="deleted_ad",
            idempotency_key="deleted_ad",
            status=ActionStatus.APPLIED,
        )
    )
    db.commit()

    found = client.get("/api/v1/campaigns/manage/ad/deleted_ad/state", headers=headers)

    assert found.status_code == 200, found.text
    assert found.json()["gone"] is True
    assert found.json()["pending"] is False


def test_what_never_existed_is_still_not_found(
    client, db: Session, queued: list
) -> None:  # type: ignore[no-untyped-def]
    _, headers, _campaign = _ready(client, db)

    found = client.get("/api/v1/campaigns/manage/ad/no_such_ad/state", headers=headers)

    assert found.status_code == 404
