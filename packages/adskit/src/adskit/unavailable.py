"""A placeholder that satisfies every port and refuses every call.

``ProviderBundle`` requires all seven ports, on the argument that a provider
missing one should fail loudly at the call site rather than quietly at an
attribute lookup somewhere unrelated. This is what makes that requirement
affordable while a provider is still being built: the bundle is complete
from the first day, and the ports that do not exist yet say so by name.

**Every method of every port is here, and that is load-bearing.** A stand-in
missing one is worse than no stand-in at all: it satisfies the protocol at
type-check time and then fails as ``AttributeError`` at the call site, which
is the exact failure this class was written to prevent. Nothing points at
such a gap, because nothing can.

Provider-independent on purpose. Google will be built out one port at a
time in exactly the same way.
"""

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from adskit.dto import (
    AccountStateDTO,
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
    """Stands in for one port of one provider.

    Implements all seven protocols rather than one. The alternative - seven
    placeholder classes - is seven files to delete instead of seven lines,
    and nothing here is specific to which port it is standing in for.

    ``port`` is the name that ends up in the error, so it is worth being
    the name a person would search for: "metrics", not "MetricsPort".
    """

    def __init__(self, *, provider: str, port: str) -> None:
        self._provider = provider
        self._port = port

    def __repr__(self) -> str:
        return f"Unavailable(provider={self._provider!r}, port={self._port!r})"

    def _refuse(self) -> PortNotAvailable:
        return PortNotAvailable(provider=self._provider, port=self._port)

    # --- CampaignControlPort ---------------------------------------------
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

    def read_account(self, *, account: ExternalRef, token: str) -> AccountStateDTO:
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

    # --- MetricsPort ------------------------------------------------------
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

    # --- LeadSourcePort ---------------------------------------------------
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

    # --- AudiencePort -----------------------------------------------------
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

    def read_targeting(self, *, ref: ExternalRef, token: str) -> dict[str, Any]:
        raise self._refuse()

    def same_targeting(self, first: dict[str, Any], second: dict[str, Any]) -> bool:
        raise self._refuse()

    # --- AudienceSourcePort -----------------------------------------------
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

    # --- ConversionPort ---------------------------------------------------
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

    # --- ConnectPort ------------------------------------------------------
    def authorize_url(self, *, redirect_uri: str, state: str) -> str:
        raise self._refuse()

    def complete(self, *, redirect_uri: str, code: str) -> GrantDTO:
        raise self._refuse()

    def access_token(self, *, stored: str) -> str:
        raise self._refuse()
