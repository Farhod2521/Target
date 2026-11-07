"""TZ 6: the night's frequency levels against PostgreSQL, the dashboard's top,
and «Qo'shimcha kreativ qo'shamiz» opening the advert's copy window."""

import importlib
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.agent.models import FrequencyAlert
from app.modules.agent.selectors.frequency import Candidate
from core.agent.frequency import Reading
from tests.pg.test_ads_additions import _signed_in

# The module, not the function the package re-exports under the same name.
night = importlib.import_module("app.modules.agent.services.check_frequency")


def _week(monkeypatch: pytest.MonkeyPatch, campaign: Any, frequency: int) -> None:
    """The group s_1 seen ``frequency`` hundredths of times a person this week."""
    candidate = Candidate(
        account=campaign.ad_account,
        name="Guruh",
        reading=Reading(
            adset_id="s_1",
            impressions=frequency * 100,
            reach=10_000,
            spend_minor=5_000,
        ),
        ctr_before_bp=140,
        ctr_now_bp=90,
        cost_minor=125,
        cost_usual_minor=90,
    )
    monkeypatch.setattr(night, "frequency_candidates", lambda *_, **__: [candidate])


def _open(db: Session) -> list[FrequencyAlert]:
    db.expire_all()
    return list(
        db.scalars(select(FrequencyAlert).where(FrequencyAlert.closed_at.is_(None)))
    )


def test_the_levels_rise_and_three_goes_when_it_falls_under_three(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, owner, campaign = _signed_in(client, db)
    now = utcnow()

    _week(monkeypatch, campaign, 204)
    (advice,) = night.check_frequency(db, owner=owner, now=now)
    assert advice.level == "advice"
    assert client.get("/api/v1/agent/frequency/pressing", headers=headers).json() == {
        "alerts": []
    }

    _week(monkeypatch, campaign, 253)
    (_warning,) = night.check_frequency(db, owner=owner, now=now + timedelta(days=1))
    pressing = client.get("/api/v1/agent/frequency/pressing", headers=headers).json()
    assert [row["level"] for row in pressing["alerts"]] == ["warning"]
    assert pressing["alerts"][0]["title"] == "Kreativni almashtirish kerak"
    assert (
        "CTR: 1,4% → 0,9% · Lid narxi: $1,25 (odatda $0,90)"
        in pressing["alerts"][0]["body"]
    )

    _week(monkeypatch, campaign, 305)
    (required,) = night.check_frequency(db, owner=owner, now=now + timedelta(days=2))
    assert required.level == "required"
    assert [row.level for row in _open(db)] == ["required"]

    # Under 3.00: the message goes, and 2.50 is not said a second time.
    _week(monkeypatch, campaign, 270)
    assert night.check_frequency(db, owner=owner, now=now + timedelta(days=3)) == []
    (eased,) = _open(db)
    assert eased.level == "required" and eased.eased_at is not None
    assert client.get("/api/v1/agent/frequency/pressing", headers=headers).json() == {
        "alerts": []
    }

    # Under 2.00: the group starts again.
    _week(monkeypatch, campaign, 190)
    night.check_frequency(db, owner=owner, now=now + timedelta(days=4))
    assert _open(db) == []


def test_add_a_creative_opens_the_campaign_with_its_advert(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, owner, campaign = _signed_in(client, db)
    _week(monkeypatch, campaign, 253)
    (row,) = night.check_frequency(db, owner=owner, now=utcnow())

    answer = client.get(f"/api/v1/agent/frequency/{row.id}/creative", headers=headers)

    assert answer.status_code == 200, answer.text
    assert answer.json()["campaignId"] == str(campaign.id)
    assert answer.json()["externalId"] in {"a_1", "a_2"}
