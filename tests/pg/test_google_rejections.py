"""Google's refused adverts on the Google Ads screen, read without the AI."""

import pytest
from fastapi.testclient import TestClient
from googleadskit import PROVIDER as GOOGLE
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.crypto import fingerprint
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.ads.selectors.google_rejections import POLICY_MANAGER, cause_of
from app.modules.ads.selectors.rejections import review_key
from app.modules.billing.services import start_trial
from app.modules.integrations.models import AdAccount, ProviderConnection
from tests.pg.conftest import sign_up

CUSTOMER = "1234567890"
CAMPAIGN = f"customers/{CUSTOMER}/campaigns/11"
GROUP = f"customers/{CUSTOMER}/adGroups/22"


@pytest.fixture
def google_on(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.common.config import settings

    monkeypatch.setattr(settings, "google_oauth_client_id", "id")
    monkeypatch.setattr(settings, "google_ads_enabled", True)


def _screen_owner(client: TestClient, db: Session) -> tuple[dict[str, str], AdSet]:
    auth = sign_up(client)
    user = db.scalar(select(User))
    assert user is not None
    start_trial(db, user=user, now=utcnow())
    connection = ProviderConnection(
        owner_id=user.id,
        provider=GOOGLE,
        external_user_id="g-1",
        token_encrypted=b"x",
        token_fingerprint=fingerprint("x"),
    )
    db.add(connection)
    db.flush()
    account = AdAccount(
        owner_id=user.id,
        provider=GOOGLE,
        external_id=CUSTOMER,
        connection_id=connection.id,
        name="Bahor Google",
        currency="USD",
        timezone="Asia/Tashkent",
        is_active=True,
        is_current=True,
    )
    db.add(account)
    db.flush()
    campaign = Campaign(
        owner_id=user.id,
        provider=GOOGLE,
        external_id=CAMPAIGN,
        ad_account_id=account.id,
        name="Qidiruv",
        delivery="active",
        status="ENABLED",
    )
    db.add(campaign)
    db.flush()
    group = AdSet(
        owner_id=user.id,
        provider=GOOGLE,
        external_id=GROUP,
        campaign_id=campaign.id,
        name="Guruh",
        delivery="active",
        status="ENABLED",
    )
    db.add(group)
    db.flush()
    return auth, group


def _ad(db: Session, group: AdSet, n: int, **columns: object) -> Ad:
    ad = Ad(
        owner_id=group.owner_id,
        provider=GOOGLE,
        external_id=f"{GROUP.replace('adGroups', 'adGroupAds')}~{n}",
        adset_id=group.id,
        name="RESPONSIVE_SEARCH_AD",
        status="ENABLED",
        **columns,
    )
    db.add(ad)
    db.flush()
    return ad


def test_a_refused_advert_is_said_on_its_group_and_campaign(
    client: TestClient, db: Session, google_on: None
) -> None:
    auth, group = _screen_owner(client, db)
    _ad(db, group, 1, delivery="active")
    _ad(
        db,
        group,
        2,
        delivery="rejected",
        review_feedback={
            "overall": {"DESTINATION_NOT_WORKING": "PROHIBITED — https://bahor.uz 404"},
            "by_placement": {},
        },
    )
    _ad(db, group, 3, delivery="rejected")
    db.commit()

    answer = client.get("/api/v1/google/screen?period=7", headers=auth)

    assert answer.status_code == 200, answer.text
    (campaign,) = answer.json()["screen"]["campaigns"]
    (shown,) = campaign["groups"]
    assert shown["rejectedAds"] == 2
    assert campaign["rejectedAds"] == 2
    refusal = shown["rejection"]
    assert refusal == campaign["rejection"]
    assert refusal["title"] == "Google reklamani rad etdi"
    assert refusal["cause"] == "Sabab — reklama olib boradigan sayt."
    assert refusal["providerWords"] == (
        "DESTINATION_NOT_WORKING: PROHIBITED — https://bahor.uz 404"
    )
    assert refusal["key"] is None and refusal["explaining"] is False
    assert refusal["fix"]["url"] == POLICY_MANAGER


def test_a_group_with_nothing_refused_says_nothing(
    client: TestClient, db: Session, google_on: None
) -> None:
    auth, group = _screen_owner(client, db)
    _ad(db, group, 1, delivery="active")
    db.commit()

    (campaign,) = client.get("/api/v1/google/screen", headers=auth).json()["screen"][
        "campaigns"
    ]

    assert campaign["rejectedAds"] == 0 and campaign["rejection"] is None
    assert campaign["groups"][0]["rejection"] is None


def test_a_refusal_google_gave_no_reason_for_points_at_google_ads(
    client: TestClient, db: Session, google_on: None
) -> None:
    auth, group = _screen_owner(client, db)
    ad = _ad(db, group, 1, delivery="rejected")
    db.commit()

    (campaign,) = client.get("/api/v1/google/screen", headers=auth).json()["screen"][
        "campaigns"
    ]

    refusal = campaign["rejection"]
    assert refusal["title"] == "Google reklamani ishga tushirmayapti"
    assert refusal["providerWords"] is None
    assert refusal["fix"]["url"] == POLICY_MANAGER
    assert review_key(ad) == ""


def test_a_google_refusal_is_never_sent_to_the_ai(
    db: Session, client: TestClient
) -> None:
    _auth, group = _screen_owner(client, db)
    ad = _ad(
        db,
        group,
        1,
        delivery="rejected",
        review_feedback={"overall": {"PUNCTUATION": "PROHIBITED — Arzon!!!"}},
    )

    assert review_key(ad) == ""


@pytest.mark.parametrize(
    ("policies", "cause"),
    [
        (["DESTINATION_MISMATCH"], "site"),
        (["MALWARE"], "site"),
        (["PUNCTUATION"], "words"),
        (["EXCESSIVE_CAPITALIZATION"], "words"),
        (["TRADEMARKS_IN_AD_TEXT"], "words"),
        (["ALCOHOL", "DESTINATION_NOT_WORKING"], "site"),
        (["ALCOHOL"], "unknown"),
        ([], "unknown"),
    ],
)
def test_the_part_at_fault_is_read_from_googles_policy_code(
    policies: list[str], cause: str
) -> None:
    assert cause_of(policies) == cause
