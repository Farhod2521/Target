"""A placeholder that satisfies every port and refuses every call."""

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from adskit.dto import (
    ActionResult,
    AdDTO,
    AdPreviewDTO,
    AdSetDTO,
    AudienceDTO,
    AudienceMemberDTO,
    AudienceRuleDTO,
    CampaignDTO,
    ConversionReceiptDTO,
    GrantDTO,
    InterestDTO,
    LeadDTO,
    LeadEventDTO,
    LeadFormDTO,
    LocationDTO,
    LookalikeSpecDTO,
    MemberUploadDTO,
    MetricsDTO,
    ObjectsDTO,
    PeopleCountDTO,
    ReachDTO,
    RuleSupportDTO,
    SegmentMetricsDTO,
    StatusDTO,
)
from adskit.errors import PortNotAvailable
from adskit.refs import BreakdownKind, ExternalRef, Level, MinorUnits, TraitKind


class Unavailable:
    """Stands in for one port of one provider."""

    def __init__(self, *, provider: str, port: str) -> None:
        self._provider = provider
        self._port = port

    def __repr__(self) -> str:
        return f"Unavailable(provider={self._provider!r}, port={self._port!r})"

    def _refuse(self) -> PortNotAvailable:
        return PortNotAvailable(provider=self._provider, port=self._port)

    def list_campaigns(self, *, account: ExternalRef, token: str) -> list[CampaignDTO]:
        raise self._refuse()

    def list_adsets(self, *, account: ExternalRef, token: str) -> list[AdSetDTO]:
        raise self._refuse()

    def list_ads(self, *, account: ExternalRef, token: str) -> list[AdDTO]:
        raise self._refuse()

    def read_objects(
        self, *, account: ExternalRef, refs: Sequence[ExternalRef], token: str
    ) -> ObjectsDTO:
        raise self._refuse()

    def get_status(self, *, ref: ExternalRef, token: str) -> StatusDTO:
        raise self._refuse()

    def count_adsets(self, *, campaign: ExternalRef, token: str) -> int:
        raise self._refuse()

    def get_preview(
        self, *, ref: ExternalRef, ad_format: str, token: str
    ) -> AdPreviewDTO:
        raise self._refuse()

    def set_status(
        self, *, ref: ExternalRef, status: str, token: str, dry_run: bool = True
    ) -> ActionResult:
        raise self._refuse()

    def set_budget(
        self,
        *,
        ref: ExternalRef,
        daily_budget_minor: MinorUnits,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        raise self._refuse()

    def set_end_time(
        self, *, ref: ExternalRef, end_time: str, token: str, dry_run: bool = True
    ) -> ActionResult:
        raise self._refuse()

    def set_spend_cap(
        self,
        *,
        ref: ExternalRef,
        spend_cap_minor: MinorUnits,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        raise self._refuse()

    def delete(
        self, *, ref: ExternalRef, token: str, dry_run: bool = True
    ) -> ActionResult:
        raise self._refuse()

    def fetch_daily(
        self,
        *,
        account: ExternalRef,
        since: date,
        until: date,
        level: Level,
        token: str,
    ) -> list[MetricsDTO]:
        raise self._refuse()

    def fetch_breakdown(
        self,
        *,
        account: ExternalRef,
        since: date,
        until: date,
        level: Level,
        kind: BreakdownKind,
        token: str,
    ) -> list[SegmentMetricsDTO]:
        raise self._refuse()

    def fetch_people(
        self,
        *,
        account: ExternalRef,
        ranges: Sequence[tuple[date, date]],
        level: Level,
        token: str,
    ) -> list[PeopleCountDTO]:
        raise self._refuse()

    def list_forms(self, *, page: ExternalRef, token: str) -> list[LeadFormDTO]:
        raise self._refuse()

    def fetch_lead(self, *, ref: ExternalRef, token: str) -> LeadDTO:
        raise self._refuse()

    def list_leads(
        self,
        *,
        form: ExternalRef,
        since: datetime,
        token: str,
        until: datetime | None = None,
    ) -> list[LeadDTO]:
        raise self._refuse()

    def subscribe(
        self, *, page: ExternalRef, token: str, dry_run: bool = True
    ) -> ActionResult:
        raise self._refuse()

    def find_interests(self, *, names: list[str], token: str) -> list[InterestDTO]:
        raise self._refuse()

    def find_traits(
        self, *, kind: TraitKind, names: list[str], token: str
    ) -> list[InterestDTO]:
        raise self._refuse()

    def find_locations(
        self, *, query: str, country_code: str, token: str
    ) -> list[LocationDTO]:
        raise self._refuse()

    def estimate_reach(
        self,
        *,
        account: ExternalRef,
        targeting: dict[str, Any],
        optimization_goal: str,
        token: str,
    ) -> ReachDTO:
        raise self._refuse()

    def apply(
        self,
        *,
        ref: ExternalRef,
        targeting: dict[str, Any],
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        raise self._refuse()

    def list_audiences(self, *, account: ExternalRef, token: str) -> list[AudienceDTO]:
        raise self._refuse()

    def get_audience(self, *, ref: ExternalRef, token: str) -> AudienceDTO:
        raise self._refuse()

    def create_audience(
        self,
        *,
        account: ExternalRef,
        name: str,
        description: str = "",
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        raise self._refuse()

    def supported_rules(self) -> list[RuleSupportDTO]:
        raise self._refuse()

    def create_rule_audience(
        self,
        *,
        account: ExternalRef,
        name: str,
        description: str = "",
        rule: AudienceRuleDTO,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        raise self._refuse()

    def create_lookalike_audience(
        self,
        *,
        account: ExternalRef,
        name: str,
        description: str = "",
        spec: LookalikeSpecDTO,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        raise self._refuse()

    def add_members(
        self,
        *,
        ref: ExternalRef,
        members: Sequence[AudienceMemberDTO],
        token: str,
        dry_run: bool = True,
    ) -> MemberUploadDTO:
        raise self._refuse()

    def remove_members(
        self,
        *,
        ref: ExternalRef,
        members: Sequence[AudienceMemberDTO],
        token: str,
        dry_run: bool = True,
    ) -> MemberUploadDTO:
        raise self._refuse()

    def delete_audience(
        self, *, ref: ExternalRef, token: str, dry_run: bool = True
    ) -> ActionResult:
        raise self._refuse()

    def report_leads(
        self,
        *,
        dataset: ExternalRef,
        events: Sequence[LeadEventDTO],
        token: str,
        dry_run: bool = True,
    ) -> ConversionReceiptDTO:
        raise self._refuse()

    def report_window_days(self) -> int:
        raise self._refuse()

    def authorize_url(self, *, redirect_uri: str, state: str) -> str:
        raise self._refuse()

    def complete(self, *, redirect_uri: str, code: str) -> GrantDTO:
        raise self._refuse()

    def access_token(self, *, stored: str) -> str:
        raise self._refuse()
