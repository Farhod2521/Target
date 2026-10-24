"""The campaign and the ad set, with Meta's own commentary on them."""

from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field, field_validator

from metaads.dto_base import MetaDTO, _minor_units


class IssueRow(MetaDTO):
    """One entry of ``issues_info``.

    Meta's own shape, renamed nowhere: ``error_code`` is what it calls the
    number, and a model that renamed it would make the payload and the
    model impossible to read side by side. The domain's version is
    ``adskit.IssueDTO`` and the adapter is what gets from one to the other.

    ``error_code`` arrives as a JSON number and leaves as one. It is turned
    into a string at the boundary, where the domain says ids and codes are
    strings because nothing promises the next provider uses digits.
    """

    level: str = ""
    error_code: int = 0
    error_summary: str = ""
    error_message: str = ""
    error_type: str = ""


class RecommendationRow(MetaDTO):
    """One entry of ``recommendations``.

    Advice about an object that is working, which is why it is a separate
    list from ``issues_info`` on Meta's side too.
    """

    code: int = 0
    title: str = ""
    message: str = ""
    importance: str = ""
    confidence: str = ""
    blame_field: str = ""


class ReviewFeedbackRow(MetaDTO):
    """``ad_review_feedback``: why an ad was refused.

    Present only on a rejected ad, and absent on every other one - which is
    the normal case, not a missing field.

    ``global`` is a Python keyword, so the model reads it under another
    name and tells pydantic where to find it. The values are a mapping from
    a policy name to Meta's explanation, and the policy list is Meta's and
    grows; a model with a field per policy would need changing every time
    an advertising rule was added.
    """

    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    overall: dict[str, str] = Field(default_factory=dict, alias="global")
    placement_specific: dict[str, dict[str, str]] = Field(default_factory=dict)


class CampaignRow(MetaDTO):
    """One row of ``/act_<id>/campaigns``.

    Named for what it is - a row of a Graph list response - rather than
    for the domain, because the domain's campaign is
    ``adskit.CampaignDTO`` and the adapter's job is to get from one to the
    other. Two names for the same idea in one file would be worse than
    a long one.

    No currency here: Meta reports it on the ad account and not on the
    objects underneath, so the caller supplies it from the account it
    already stored.
    """

    id: str
    name: str = ""
    objective: str = ""
    status: str = ""
    effective_status: str = ""
    daily_budget: str = ""
    spend_cap: str = ""
    special_ad_categories: tuple[str, ...] = ()
    created_time: datetime | None = None
    issues_info: tuple[IssueRow, ...] = ()
    recommendations: tuple[RecommendationRow, ...] = ()

    @field_validator("daily_budget", "spend_cap", mode="before")
    @classmethod
    def _as_text(cls, value: object) -> object:
        """Money arrives quoted on some edges and bare on others."""
        if value is None:
            return ""
        if isinstance(value, bool):
            return value
        return str(value) if isinstance(value, int | float) else value

    @property
    def daily_budget_minor(self) -> int | None:
        return _minor_units(self.daily_budget)

    @property
    def spend_cap_minor(self) -> int | None:
        """``None`` where Meta named no cap, which is the ordinary answer."""
        return _minor_units(self.spend_cap)


class AdSetRow(MetaDTO):
    """One row of ``/act_<id>/adsets``.

    ``targeting`` and ``promoted_object`` come through as the dicts Meta
    sent. Parsing them into fields would mean deciding today what a
    targeting spec is, and Meta changes that answer more often than it
    changes API versions.
    """

    id: str
    name: str = ""
    campaign_id: str = ""
    status: str = ""
    effective_status: str = ""
    optimization_goal: str = ""
    billing_event: str = ""
    destination_type: str = ""
    daily_budget: str = ""
    targeting: dict[str, Any] = Field(default_factory=dict)
    promoted_object: dict[str, Any] = Field(default_factory=dict)
    learning_stage_info: dict[str, Any] = Field(default_factory=dict)
    start_time: datetime | None = None
    end_time: datetime | None = None
    issues_info: tuple[IssueRow, ...] = ()
    recommendations: tuple[RecommendationRow, ...] = ()

    @property
    def daily_budget_minor(self) -> int | None:
        return _minor_units(self.daily_budget)

    @property
    def learning_status(self) -> str:
        """``LEARNING``, ``SUCCESS``, ``LEARNING_LIMITED``, or empty."""
        status = self.learning_stage_info.get("status", "")
        return status if isinstance(status, str) else ""
