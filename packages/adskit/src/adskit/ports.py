"""The seven capabilities a provider must offer."""

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, Protocol, runtime_checkable

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
from adskit.refs import BreakdownKind, ExternalRef, Level, MinorUnits, TraitKind


@runtime_checkable
class CampaignControlPort(Protocol):
    """Read the shape of an account, and start or stop what is in it."""

    def list_campaigns(
        self, *, account: ExternalRef, token: str
    ) -> list[CampaignDTO]: ...

    def list_adsets(self, *, account: ExternalRef, token: str) -> list[AdSetDTO]:
        """Every ad set in the account, not every ad set in one campaign."""
        ...

    def list_ads(self, *, account: ExternalRef, token: str) -> list[AdDTO]:
        """Every ad in the account, for the same reason."""
        ...

    def read_objects(
        self, *, account: ExternalRef, refs: Sequence[ExternalRef], token: str
    ) -> ObjectsDTO:
        """These campaigns, ad groups and ads, and nothing else in the account."""
        ...

    def get_status(self, *, ref: ExternalRef, token: str) -> StatusDTO: ...

    def count_adsets(self, *, campaign: ExternalRef, token: str) -> int:
        """How many ad groups one campaign holds that have not been removed."""
        ...

    def get_preview(
        self, *, ref: ExternalRef, ad_format: str, token: str
    ) -> AdPreviewDTO:
        """Where this ad can be seen the way its audience will see it."""
        ...

    def set_status(
        self,
        *,
        ref: ExternalRef,
        status: str,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """Pause or resume. ``dry_run`` defaults to True on every write."""
        ...

    def set_budget(
        self,
        *,
        ref: ExternalRef,
        daily_budget_minor: MinorUnits,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """Replace the daily budget on whichever object holds it."""
        ...

    def set_end_time(
        self,
        *,
        ref: ExternalRef,
        end_time: str,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """Say when this object should stop delivering."""
        ...

    def set_spend_cap(
        self,
        *,
        ref: ExternalRef,
        spend_cap_minor: MinorUnits,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """The most this object may spend in total, ever."""
        ...

    def delete(
        self,
        *,
        ref: ExternalRef,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """Take one object off the account for good."""
        ...


@runtime_checkable
class MetricsPort(Protocol):
    """Daily performance figures."""

    def fetch_daily(
        self,
        *,
        account: ExternalRef,
        since: date,
        until: date,
        level: Level,
        token: str,
    ) -> list[MetricsDTO]:
        """Inclusive date range, in the ad account's timezone."""
        ...

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
        """The same range, cut into segments instead of summed."""
        ...

    def fetch_people(
        self,
        *,
        account: ExternalRef,
        ranges: Sequence[tuple[date, date]],
        level: Level,
        token: str,
    ) -> list[PeopleCountDTO]:
        """How many people each object reached, once per range."""
        ...


@runtime_checkable
class LeadSourcePort(Protocol):
    """Where leads come from, and how we ask to be told about them."""

    def list_forms(self, *, page: ExternalRef, token: str) -> list[LeadFormDTO]:
        """Every form on one page, whatever state each is in."""
        ...

    def fetch_lead(self, *, ref: ExternalRef, token: str) -> LeadDTO: ...

    def list_leads(
        self,
        *,
        form: ExternalRef,
        since: datetime,
        token: str,
        until: datetime | None = None,
    ) -> list[LeadDTO]:
        """Reconciliation path, for leads a webhook never delivered."""
        ...

    def subscribe(
        self, *, page: ExternalRef, token: str, dry_run: bool = True
    ) -> ActionResult:
        """Ask the provider to start sending webhooks."""
        ...


@runtime_checkable
class AudiencePort(Protocol):
    """Who an ad set is shown to."""

    def find_interests(self, *, names: list[str], token: str) -> list[InterestDTO]:
        """The catalogue rows the provider recognises under these names."""
        ...

    def find_traits(
        self, *, kind: TraitKind, names: list[str], token: str
    ) -> list[InterestDTO]:
        """The rows of a **closed** catalogue that match these names."""
        ...

    def find_locations(
        self, *, query: str, country_code: str, token: str
    ) -> list[LocationDTO]:
        """The places the provider recognises under this word."""
        ...

    def estimate_reach(
        self,
        *,
        account: ExternalRef,
        targeting: dict[str, Any],
        optimization_goal: str,
        token: str,
    ) -> ReachDTO:
        """How many people this spec would reach, before anything is created."""
        ...

    def apply(
        self,
        *,
        ref: ExternalRef,
        targeting: dict[str, Any],
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """Replace the targeting spec."""
        ...


@runtime_checkable
class AudienceSourcePort(Protocol):
    """The audiences an advertiser owns, as objects with a life of their own."""

    def list_audiences(self, *, account: ExternalRef, token: str) -> list[AudienceDTO]:
        """Every audience on the account, whatever state each is in."""
        ...

    def get_audience(self, *, ref: ExternalRef, token: str) -> AudienceDTO:
        """One audience, read fresh."""
        ...

    def create_audience(
        self,
        *,
        account: ExternalRef,
        name: str,
        description: str = "",
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """Make an empty audience that a customer list can be uploaded into."""
        ...

    def supported_rules(self) -> list[RuleSupportDTO]:
        """Which rule audiences this provider will build, and how far back."""
        ...

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
        """Make an audience the provider fills in itself, from a rule."""
        ...

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
        """Make an audience of people who resemble an audience that exists."""
        ...

    def add_members(
        self,
        *,
        ref: ExternalRef,
        members: Sequence[AudienceMemberDTO],
        token: str,
        dry_run: bool = True,
    ) -> MemberUploadDTO:
        """Add people to an audience. The one call that carries a customer list."""
        ...

    def remove_members(
        self,
        *,
        ref: ExternalRef,
        members: Sequence[AudienceMemberDTO],
        token: str,
        dry_run: bool = True,
    ) -> MemberUploadDTO:
        """Take people back out of an audience. The other half of the one-way door."""
        ...

    def delete_audience(
        self, *, ref: ExternalRef, token: str, dry_run: bool = True
    ) -> ActionResult:
        """Remove the audience, and with it everything uploaded into it."""
        ...


@runtime_checkable
class ConversionPort(Protocol):
    """What became of a lead after the provider handed it over."""

    def report_leads(
        self,
        *,
        dataset: ExternalRef,
        events: Sequence[LeadEventDTO],
        token: str,
        dry_run: bool = True,
    ) -> ConversionReceiptDTO:
        """Send a batch of verdicts. Returns how many the provider took."""
        ...

    def report_window_days(self) -> int:
        """How far back a verdict may still be sent, in whole days."""
        ...


@runtime_checkable
class ConnectPort(Protocol):
    """How a person lets this product act on their advertising account."""

    def authorize_url(self, *, redirect_uri: str, state: str) -> str:
        """Where to send the browser."""
        ...

    def complete(self, *, redirect_uri: str, code: str) -> GrantDTO:
        """Trade the callback's code for a token that lasts."""
        ...

    def access_token(self, *, stored: str) -> str:
        """The token a call is made with, from the one that was stored."""
        ...
