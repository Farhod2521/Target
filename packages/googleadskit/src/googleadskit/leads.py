"""Google's lead form submissions as :class:`adskit.LeadSourcePort`.

**Per account, not per page.** A Meta form belongs to a page and its leads
are read form by form; Google keeps every submission of an account in one
resource, ``lead_form_submission_data``. So :meth:`GoogleLeads.list_leads`
takes the account as its ``form``: one read covers every form the account
has, including ones the advertiser built by hand in Google Ads. The other
three methods are Meta's way of getting leads and refuse by name.

**No webhook here.** Google can post a submission to an address set on the
form, but only on a form whose settings carry it, and a form built by hand
does not. Reading the account reaches every form, so it is the one route.

**Answers keep the shape every provider's do**: ``{"name": key, "values":
[answer]}``. A standard field is named after its type in lower case -
``FULL_NAME`` becomes ``full_name``, ``PHONE_NUMBER`` ``phone_number`` -
which are the keys the domain's normalisation already reads; a custom
question is named by its own text.

``submission_date_time`` arrives as ``2019-01-01 12:32:45-08:00``, with its
offset, so a submission's moment is exact whatever the account's zone.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Final

import httpx
from adskit import PortNotAvailable
from adskit.dto import ActionResult, LeadDTO, LeadFormDTO
from adskit.refs import ExternalRef, ProviderName

from googleadskit.campaigns import google_calls
from googleadskit.client import AdsClient
from googleadskit.resources import customer_of

PROVIDER: Final = ProviderName("google")
LEAD_LEVEL: Final = "lead"
FORM_LEVEL: Final = "form"

_FIELDS: Final = (
    "lead_form_submission_data.resource_name, "
    "lead_form_submission_data.asset, "
    "lead_form_submission_data.campaign, "
    "lead_form_submission_data.ad_group, "
    "lead_form_submission_data.ad_group_ad, "
    "lead_form_submission_data.submission_date_time, "
    "lead_form_submission_data.lead_form_submission_fields, "
    "lead_form_submission_data.custom_lead_form_submission_fields"
)
_WHEN: Final = "%Y-%m-%d %H:%M:%S%z"
# The filter is read in a zone this module does not know, so it reaches a
# day further back and the exact edge is drawn on the parsed moments.
_FILTER_MARGIN: Final = timedelta(days=1)


class GoogleLeads:
    """Submissions of every lead form in one account."""

    def __init__(self, *, http: httpx.Client | None = None) -> None:
        self._http = http

    def list_leads(
        self,
        *,
        form: ExternalRef,
        since: datetime,
        token: str,
        until: datetime | None = None,
    ) -> list[LeadDTO]:
        """Every submission in ``[since, until)``; ``form`` is the account."""
        customer_id = customer_of(form.id) if "/" in form.id else form.id
        start = (since - _FILTER_MARGIN).astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
        query = (
            f"SELECT {_FIELDS} FROM lead_form_submission_data "
            f"WHERE lead_form_submission_data.submission_date_time >= '{start}' "
            "ORDER BY lead_form_submission_data.submission_date_time"
        )
        with google_calls(), AdsClient(token=token, http=self._http) as client:
            rows = list(client.search(customer_id, query))
        leads = [lead_of(row.get("leadFormSubmissionData") or {}) for row in rows]
        return [
            lead
            for lead in leads
            if lead.submitted_at is not None
            and lead.submitted_at >= since
            and (until is None or lead.submitted_at < until)
        ]

    # --- Meta's way of getting leads -------------------------------------

    def list_forms(self, *, page: ExternalRef, token: str) -> list[LeadFormDTO]:
        raise PortNotAvailable(provider=PROVIDER, port="leads.list_forms")

    def fetch_lead(self, *, ref: ExternalRef, token: str) -> LeadDTO:
        raise PortNotAvailable(provider=PROVIDER, port="leads.fetch_lead")

    def subscribe(
        self, *, page: ExternalRef, token: str, dry_run: bool = True
    ) -> ActionResult:
        raise PortNotAvailable(provider=PROVIDER, port="leads.subscribe")


def lead_of(node: dict[str, Any]) -> LeadDTO:
    """One ``leadFormSubmissionData`` node as a lead."""
    answers: list[dict[str, Any]] = [
        {"name": str(field.get("fieldType") or "").lower(), "values": [value]}
        for field in node.get("leadFormSubmissionFields") or []
        if (value := str(field.get("fieldValue") or "").strip())
        and field.get("fieldType")
    ]
    answers += [
        {"name": str(field.get("questionText") or "").strip(), "values": [value]}
        for field in node.get("customLeadFormSubmissionFields") or []
        if (value := str(field.get("fieldValue") or "").strip())
        and str(field.get("questionText") or "").strip()
    ]
    asset = str(node.get("asset") or "")
    return LeadDTO(
        ref=ExternalRef(
            provider=PROVIDER, level=LEAD_LEVEL, id=str(node.get("resourceName") or "")
        ),
        form=ExternalRef(provider=PROVIDER, level=FORM_LEVEL, id=asset)
        if asset
        else None,
        field_data=tuple(answers),
        submitted_at=_moment(str(node.get("submissionDateTime") or "")),
        campaign_external_id=str(node.get("campaign") or ""),
        adset_external_id=str(node.get("adGroup") or ""),
        ad_external_id=str(node.get("adGroupAd") or ""),
    )


def _moment(raw: str) -> datetime | None:
    """``2019-01-01 12:32:45-08:00`` as an aware moment; anything else, none."""
    try:
        return datetime.strptime(raw.strip(), _WHEN)
    except ValueError:
        return None


__all__ = ["GoogleLeads", "lead_of"]
