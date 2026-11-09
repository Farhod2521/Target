"""Leads from Google's lead forms, read from the account every half hour."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from adskit.dto import LeadDTO
from adskit.errors import TemporaryFailure
from adskit.refs import ExternalRef
from fastapi.testclient import TestClient
from googleadskit.leads import GoogleLeads
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.ads.models import Campaign
from app.modules.leads.models import Lead
from app.modules.leads.services.google import accounts_to_read, sync_google_leads
from tests.pg.test_google_controls import CAMPAIGN, _campaign
from tests.pg.test_launch_api import _ready
from tests.pg.test_launch_drafts import _google

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


def _lead(number: int) -> LeadDTO:
    return LeadDTO(
        ref=ExternalRef(
            provider="google",
            level="lead",
            id=f"customers/111/leadFormSubmissionData/{number}",
        ),
        form=ExternalRef(provider="google", level="form", id="customers/111/assets/9"),
        field_data=(
            {"name": "full_name", "values": ["Aziz Karimov"]},
            {"name": "phone_number", "values": ["+998901234567"]},
        ),
        submitted_at=NOW - timedelta(hours=number),
        campaign_external_id=CAMPAIGN,
        adset_external_id="customers/111/adGroups/6",
    )


@pytest.fixture
def google_account(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> Any:
    _auth, user = _ready(client, db)
    account, _launch = _google(db, monkeypatch, user)
    account.external_id = "111"
    _campaign(db, user=user, account=account)
    monkeypatch.setattr(
        "app.modules.leads.services.google.token_for", lambda *, ad_account: "tok"
    )
    return account


def _google_answers(monkeypatch: pytest.MonkeyPatch, *leads: LeadDTO) -> list[datetime]:
    asked: list[datetime] = []

    def list_leads(
        _self: GoogleLeads, *, form: ExternalRef, since: datetime, token: str, **_: Any
    ) -> list[LeadDTO]:
        assert form.id == "111"
        asked.append(since)
        return list(leads)

    monkeypatch.setattr(GoogleLeads, "list_leads", list_leads)
    return asked


def test_a_submission_becomes_a_lead_once_however_often_it_is_read(
    db: Session, google_account: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = _google_answers(monkeypatch, _lead(1), _lead(2))
    account_id = str(google_account.id)

    first = sync_google_leads(db, ad_account_id=account_id, now=NOW)
    again = sync_google_leads(db, ad_account_id=account_id, now=NOW)

    assert (first, again) == (2, 0)
    # The first read reaches back a month; once a lead is held, two days.
    assert asked == [NOW - timedelta(days=30), NOW - timedelta(days=2)]
    rows = db.scalars(select(Lead).where(Lead.provider == "google")).all()
    assert len(rows) == 2
    lead = next(row for row in rows if row.leadgen_id.endswith("/1"))
    assert (lead.full_name, lead.phone_e164, lead.campaign_external_id) == (
        "Aziz Karimov",
        "+998901234567",
        CAMPAIGN,
    )
    assert lead.owner_id == google_account.owner_id


def test_an_account_with_nothing_running_is_not_read(
    db: Session, google_account: Any
) -> None:
    assert accounts_to_read(db, now=NOW + timedelta(days=1)) == [google_account.id]

    campaign = db.scalar(select(Campaign).where(Campaign.external_id == CAMPAIGN))
    assert campaign is not None
    campaign.status = "PAUSED"
    campaign.updated_at = NOW - timedelta(days=5)
    db.commit()

    assert accounts_to_read(db, now=NOW) == []


def test_google_refusing_a_read_loses_nothing_and_breaks_nothing(
    db: Session, google_account: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(_self: GoogleLeads, **_: Any) -> list[LeadDTO]:
        raise TemporaryFailure("busy")

    monkeypatch.setattr(GoogleLeads, "list_leads", refused)

    assert sync_google_leads(db, ad_account_id=str(google_account.id), now=NOW) == 0
