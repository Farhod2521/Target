"""googleadskit: lead form submissions read from an account."""

import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from adskit import PortNotAvailable
from adskit.refs import ExternalRef
from googleadskit.adapter import bundle
from googleadskit.leads import GoogleLeads

from core.leads.normalise import normalise

ACCOUNT = ExternalRef(provider="google", level="account", id="111")
TASHKENT = timezone(timedelta(hours=5))


def _submission(**extra: Any) -> dict[str, Any]:
    node = {
        "resourceName": "customers/111/leadFormSubmissionData/77",
        "asset": "customers/111/assets/9",
        "campaign": "customers/111/campaigns/5",
        "adGroup": "customers/111/adGroups/6",
        "adGroupAd": "customers/111/adGroupAds/6~8",
        "submissionDateTime": "2026-11-08 14:30:00+05:00",
        "leadFormSubmissionFields": [
            {"fieldType": "FULL_NAME", "fieldValue": "Aziz Karimov"},
            {"fieldType": "PHONE_NUMBER", "fieldValue": "+998 90 123 45 67"},
            {"fieldType": "EMAIL", "fieldValue": "Aziz@Mail.uz"},
            {"fieldType": "CITY", "fieldValue": "Toshkent"},
        ],
        "customLeadFormSubmissionFields": [
            {"questionText": "Qaysi xizmat kerak?", "fieldValue": "Ta'mir"}
        ],
    }
    return {"leadFormSubmissionData": node | extra}


def _read(
    *rows: dict[str, Any], since: datetime, until: datetime | None = None
) -> tuple[list[Any], list[str]]:
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url) + " " + json.loads(request.content)["query"])
        return httpx.Response(200, json={"results": list(rows)})

    leads = GoogleLeads(http=httpx.Client(transport=httpx.MockTransport(handler)))
    return leads.list_leads(form=ACCOUNT, since=since, until=until, token="t"), asked


def test_a_submission_reads_like_any_providers_lead() -> None:
    leads, asked = _read(
        _submission(), since=datetime(2026, 11, 8, 0, 0, tzinfo=TASHKENT)
    )

    (lead,) = leads
    assert "customers/111/googleAds:search" in asked[0]
    assert "FROM lead_form_submission_data" in asked[0]
    assert lead.ref.id == "customers/111/leadFormSubmissionData/77"
    assert lead.form is not None and lead.form.id == "customers/111/assets/9"
    assert lead.submitted_at == datetime(2026, 11, 8, 9, 30, tzinfo=UTC)
    assert (
        lead.campaign_external_id,
        lead.adset_external_id,
        lead.ad_external_id,
    ) == (
        "customers/111/campaigns/5",
        "customers/111/adGroups/6",
        "customers/111/adGroupAds/6~8",
    )
    read = normalise(field_data=lead.field_data, region="UZ")
    assert (read.full_name, read.phone_e164, read.email, read.city) == (
        "Aziz Karimov",
        "+998901234567",
        "aziz@mail.uz",
        "Toshkent",
    )
    assert read.answers["Qaysi xizmat kerak?"] == ("Ta'mir",)


def test_the_window_is_drawn_on_the_exact_moment() -> None:
    early = _submission(
        resourceName="customers/111/leadFormSubmissionData/1",
        submissionDateTime="2026-11-07 23:59:59+05:00",
    )
    late = _submission(
        resourceName="customers/111/leadFormSubmissionData/2",
        submissionDateTime="2026-11-09 10:00:00+05:00",
    )

    leads, asked = _read(
        early,
        _submission(),
        late,
        since=datetime(2026, 11, 8, 0, 0, tzinfo=TASHKENT),
        until=datetime(2026, 11, 9, 0, 0, tzinfo=TASHKENT),
    )

    assert [lead.ref.id for lead in leads] == [
        "customers/111/leadFormSubmissionData/77"
    ]
    # Google is asked a day wider than the window; the edge is drawn here.
    assert "submission_date_time >= '2026-11-06 19:00:00'" in asked[0]


def test_a_submission_without_a_moment_is_not_taken_for_a_new_one() -> None:
    leads, _asked = _read(
        _submission(submissionDateTime=""),
        since=datetime(2026, 11, 1, tzinfo=UTC),
    )

    assert leads == []


def test_the_bundle_reads_leads_and_refuses_metas_routes_by_name() -> None:
    leads = bundle().leads

    assert isinstance(leads, GoogleLeads)
    with pytest.raises(PortNotAvailable):
        leads.fetch_lead(ref=ACCOUNT, token="t")
