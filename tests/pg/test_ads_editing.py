"""Editing what already runs, against PostgreSQL: an advert's words, a campaign's settings, a preview."""

from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.models import Ad, AdCreative, AdSet, Campaign, MediaAsset
from app.modules.audit.models import ActionLog
from app.modules.billing.services import start_trial
from tests.pg.conftest import sign_up
from tests.pg.test_cabinet_flows import _cabinet


def _running(db: Session, owner: User, account: object) -> Campaign:
    now = utcnow()
    campaign = Campaign(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id="c_1",
        ad_account_id=account.id,  # type: ignore[attr-defined]
        name="Bahor",
        delivery="active",
        status="ACTIVE",
        currency="USD",
        synced_at=now,
    )
    db.add(campaign)
    db.flush()
    adset = AdSet(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id="s_1",
        campaign_id=campaign.id,
        name="Guruh",
        delivery="active",
        status="ACTIVE",
        daily_budget_minor=1000,
        currency="USD",
        promoted_object_raw={"page_id": "page_1"},
        targeting_raw={
            "geo_locations": {"countries": ["UZ"]},
            "age_min": 25,
            "age_max": 45,
        },
        synced_at=now,
    )
    db.add(adset)
    db.flush()
    db.add(
        AdCreative(
            owner_id=owner.id,
            provider=PROVIDER,
            external_id="cr_1",
            ad_account_id=account.id,  # type: ignore[attr-defined]
            headline="Bahorgi tort",
            message="Buyurtma bering",
            story_raw={
                "page_id": "page_1",
                "link_data": {"message": "Buyurtma bering"},
            },
        )
    )
    for external_id in ("a_1", "a_2"):
        db.add(
            Ad(
                owner_id=owner.id,
                provider=PROVIDER,
                external_id=external_id,
                adset_id=adset.id,
                name=f"Reklama {external_id}",
                delivery="active",
                status="ACTIVE",
                creative_external_id="cr_1",
                synced_at=now,
            )
        )
    db.add(
        MediaAsset(
            owner_id=owner.id,
            provider=PROVIDER,
            ad_account_id=account.id,  # type: ignore[attr-defined]
            kind="image",
            external_id="hash_1",
            name="tort.jpg",
        )
    )
    db.commit()
    return campaign


def test_edit_a_campaigns_settings_and_an_adverts_words(
    client, db: Session, queued: list
) -> None:  # type: ignore[no-untyped-def]
    headers = sign_up(client)
    owner = db.scalar(select(User).order_by(User.date_joined.desc()))
    assert owner is not None
    account, page = _cabinet(db, owner)
    page.is_current = page.is_active = True
    account.is_active = account.is_current = True
    db.commit()
    start_trial(db, user=owner, now=utcnow())
    db.commit()
    campaign = _running(db, owner, account)

    shown = client.get(f"/api/v1/campaigns/{campaign.id}/edit", headers=headers)
    assert shown.status_code == 200, shown.text
    sections = shown.json()["sections"]
    assert sections["budget"]["level"] == "adset"
    assert sections["budget"]["current"] == "10.00"
    assert sections["audience"]["age_min"] == 25
    assert "limits" in sections

    wrong = client.post(
        f"/api/v1/campaigns/{campaign.id}/edit",
        json={"audience": {"age_min": 50, "age_max": 30}},
        headers=headers,
    )
    assert wrong.status_code == 422
    assert db.scalar(select(ActionLog.id)) is None

    saved = client.post(
        f"/api/v1/campaigns/{campaign.id}/edit",
        json={"budget": {"daily_budget": "15"}},
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["queued"] == ["budget"]
    log = db.scalar(select(ActionLog))
    assert log is not None and log.request_payload["daily_budget_minor"] == 1500

    nothing = client.post(
        f"/api/v1/campaigns/{campaign.id}/edit", json={}, headers=headers
    )
    assert nothing.json()["queued"] == []

    advert = client.get("/api/v1/campaigns/manage/ad/a_1/edit", headers=headers)
    assert advert.status_code == 200, advert.text
    body = advert.json()
    assert body["initial"]["headline"] == "Bahorgi tort"
    assert body["can_swap"] is True
    assert [row["external_id"] for row in body["library"]] == ["hash_1"]

    empty = client.post(
        "/api/v1/campaigns/manage/ad/a_1/edit", json={"message": " "}, headers=headers
    )
    assert empty.status_code == 422

    foreign = client.post(
        "/api/v1/campaigns/manage/ad/a_1/edit",
        json={
            "message": "Yangi matn",
            "asset_id": "00000000-0000-0000-0000-000000000000",
        },
        headers=headers,
    )
    assert foreign.status_code == 422

    swapped = client.post(
        "/api/v1/campaigns/manage/ad/a_1/edit",
        json={"message": "Yangi matn", "headline": "Bahorgi tort"},
        headers=headers,
    )
    assert swapped.status_code == 200, swapped.text
    assert queued[-1][0].endswith("apply_swap_task")

    preview = client.get("/api/v1/campaigns/manage/ad/a_2/preview", headers=headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()["polling"] is True
    assert preview.json()["content"]["headline"] == "Bahorgi tort"
    assert queued[-1][0].endswith("fetch_preview_task")
    again = client.get(
        "/api/v1/campaigns/manage/ad/a_2/preview?tries=3", headers=headers
    )
    assert len([name for name, _ in queued if name.endswith("fetch_preview_task")]) == 1
    assert again.json()["tries"] == 4


def test_money_finer_than_a_cent_and_an_under_age_audience_are_refused(
    client, db: Session, queued: list
) -> None:  # type: ignore[no-untyped-def]
    headers = sign_up(client)
    owner = db.scalar(select(User).order_by(User.date_joined.desc()))
    assert owner is not None
    account, page = _cabinet(db, owner)
    page.is_current = page.is_active = True
    account.is_active = account.is_current = True
    db.commit()
    start_trial(db, user=owner, now=utcnow())
    db.commit()
    campaign = _running(db, owner, account)
    edit = f"/api/v1/campaigns/{campaign.id}/edit"

    for amount in ("0.004", "12.345"):
        switch = client.post(
            "/api/v1/campaigns/manage/adset/s_1/budget",
            json={"dailyBudget": amount},
            headers=headers,
        )
        assert switch.status_code == 422, switch.text
        assert "dailyBudget" in switch.json()["problems"]
        dialog = client.post(
            edit, json={"budget": {"daily_budget": amount}}, headers=headers
        )
        assert dialog.status_code == 422, dialog.text
        assert "budget" in dialog.json()["detail"]["errors"]

    cap = client.post(edit, json={"limits": {"spend_cap": "100.001"}}, headers=headers)
    assert cap.status_code == 422 and "limits" in cap.json()["detail"]["errors"]

    young = client.post(
        edit, json={"audience": {"age_min": 13, "age_max": 30}}, headers=headers
    )
    assert young.status_code == 422, young.text
    assert db.scalar(select(ActionLog.id)) is None


def test_a_running_audience_obeys_the_launchs_rules(
    client, db: Session, queued: list
) -> None:  # type: ignore[no-untyped-def]
    """A gender that is not one is refused, an Advantage+ audience is written
    without an upper age (and the screen is told), and the dialog's own
    numbers sent back untouched open no write."""
    headers = sign_up(client)
    owner = db.scalar(select(User).order_by(User.date_joined.desc()))
    assert owner is not None
    account, page = _cabinet(db, owner)
    page.is_current = page.is_active = True
    account.is_active = account.is_current = True
    db.commit()
    start_trial(db, user=owner, now=utcnow())
    db.commit()
    campaign = _running(db, owner, account)
    adset = db.scalar(select(AdSet).where(AdSet.external_id == "s_1"))
    assert adset is not None
    adset.targeting_raw = {
        "geo_locations": {"countries": ["UZ"]},
        "age_min": 20,
        "targeting_automation": {"advantage_audience": 1},
    }
    db.commit()
    edit = f"/api/v1/campaigns/{campaign.id}/edit"

    unknown = client.post(
        edit,
        json={"audience": {"age_min": 20, "age_max": 65, "genders": [3]}},
        headers=headers,
    )
    assert unknown.status_code == 422, unknown.text

    untouched = client.post(
        edit, json={"audience": {"age_min": 20, "age_max": 65}}, headers=headers
    )
    assert untouched.status_code == 200, untouched.text
    assert untouched.json()["queued"] == []
    assert db.scalar(select(ActionLog.id)) is None

    narrowed = client.post(
        edit, json={"audience": {"age_min": 22, "age_max": 40}}, headers=headers
    )
    assert narrowed.status_code == 200, narrowed.text
    assert narrowed.json()["queued"] == ["audience"]
    assert [note["field"] for note in narrowed.json()["adjustments"]] == ["age_max"]
    log = db.scalar(select(ActionLog))
    assert log is not None
    sent = log.request_payload["targeting"]
    assert sent["age_min"] == 22 and "age_max" not in sent
