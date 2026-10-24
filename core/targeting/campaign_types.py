"""Which kinds of campaign may deliver each goal - one table, in one place."""

from dataclasses import dataclass
from typing import Final, Literal

ObjectiveGroup = Literal["awareness", "traffic", "engagement", "leads", "sales"]


@dataclass(frozen=True, slots=True)
class CampaignType:
    """One way of buying one goal."""

    provider: str
    goal: str
    key: str
    objective: str
    optimization_goal: str
    provider_label: str
    provider_goal_label: str
    objective_group: ObjectiveGroup
    destination_type: str = ""

    @property
    def provider_goal_name(self) -> str:
        """The performance goal's short name, as Ads Manager heads its rows."""
        return PERFORMANCE_GOAL_NAMES.get(
            self.provider_goal_label, self.provider_goal_label
        )


PERFORMANCE_GOAL_NAMES: Final[dict[str, str]] = {
    "Maximize number of calls": "Calls",
    "Maximize number of leads": "Leads",
    "Maximize number of qualified leads": "Qualified leads",
    "Maximize number of landing page views": "Landing page views",
    "Maximize number of link clicks": "Link clicks",
    "Maximize daily unique reach": "Daily unique reach",
    "Maximize number of impressions": "Impressions",
    "Maximize number of conversions": "Conversions",
    "Maximize reach of ads": "Reach",
    "Maximize ad recall lift": "Ad recall lift",
    "Instagram profile visits": "Profile visits",
    "Maximize number of conversations": "Conversations",
}


CAMPAIGN_TYPES: Final[tuple[CampaignType, ...]] = (
    CampaignType(
        "meta",
        "calls",
        "calls_many",
        "OUTCOME_TRAFFIC",
        "QUALITY_CALL",
        "Traffic",
        "Maximize number of calls",
        "traffic",
    ),
    CampaignType(
        "meta",
        "calls",
        "calls_engaged",
        "OUTCOME_ENGAGEMENT",
        "QUALITY_CALL",
        "Engagement",
        "Maximize number of calls",
        "engagement",
    ),
    CampaignType(
        "meta",
        "calls",
        "calls_ready",
        "OUTCOME_LEADS",
        "QUALITY_CALL",
        "Leads",
        "Maximize number of calls",
        "leads",
    ),
    CampaignType(
        "meta",
        "leads",
        "form_leads",
        "OUTCOME_LEADS",
        "LEAD_GENERATION",
        "Leads",
        "Maximize number of leads",
        "leads",
    ),
    CampaignType(
        "meta",
        "traffic",
        "site_page_views",
        "OUTCOME_TRAFFIC",
        "LANDING_PAGE_VIEWS",
        "Traffic",
        "Maximize number of landing page views",
        "traffic",
    ),
    CampaignType(
        "meta",
        "traffic",
        "site_link_clicks",
        "OUTCOME_TRAFFIC",
        "LINK_CLICKS",
        "Traffic",
        "Maximize number of link clicks",
        "traffic",
    ),
    CampaignType(
        "meta",
        "profile_visits",
        "profile_visits",
        "OUTCOME_TRAFFIC",
        "PROFILE_VISIT",
        "Traffic",
        "Instagram profile visits",
        "traffic",
        destination_type="INSTAGRAM_PROFILE",
    ),
    CampaignType(
        "meta",
        "traffic",
        "site_daily_reach",
        "OUTCOME_TRAFFIC",
        "REACH",
        "Traffic",
        "Maximize daily unique reach",
        "traffic",
    ),
    CampaignType(
        "meta",
        "traffic",
        "site_impressions",
        "OUTCOME_TRAFFIC",
        "IMPRESSIONS",
        "Traffic",
        "Maximize number of impressions",
        "traffic",
    ),
    CampaignType(
        "meta",
        "site_leads",
        "site_requests",
        "OUTCOME_LEADS",
        "OFFSITE_CONVERSIONS",
        "Leads",
        "Maximize number of conversions",
        "leads",
    ),
    CampaignType(
        "meta",
        "site_leads",
        "site_requests_views",
        "OUTCOME_LEADS",
        "LANDING_PAGE_VIEWS",
        "Leads",
        "Maximize number of landing page views",
        "leads",
    ),
    CampaignType(
        "meta",
        "site_leads",
        "site_requests_clicks",
        "OUTCOME_LEADS",
        "LINK_CLICKS",
        "Leads",
        "Maximize number of link clicks",
        "leads",
    ),
    CampaignType(
        "meta",
        "site_leads",
        "site_requests_reach",
        "OUTCOME_LEADS",
        "REACH",
        "Leads",
        "Maximize daily unique reach",
        "leads",
    ),
    CampaignType(
        "meta",
        "views",
        "seen_often",
        "OUTCOME_AWARENESS",
        "IMPRESSIONS",
        "Awareness",
        "Maximize number of impressions",
        "awareness",
    ),
    CampaignType(
        "meta",
        "views",
        "seen_widely",
        "OUTCOME_AWARENESS",
        "REACH",
        "Awareness",
        "Maximize reach of ads",
        "awareness",
    ),
    CampaignType(
        "meta",
        "views",
        "seen_remembered",
        "OUTCOME_AWARENESS",
        "AD_RECALL_LIFT",
        "Awareness",
        "Maximize ad recall lift",
        "awareness",
    ),
    CampaignType(
        "meta",
        "messages",
        "chat_conversations",
        "OUTCOME_ENGAGEMENT",
        "CONVERSATIONS",
        "Engagement",
        "Maximize number of conversations",
        "engagement",
    ),
    CampaignType(
        "meta",
        "messages",
        "chat_link_clicks",
        "OUTCOME_ENGAGEMENT",
        "LINK_CLICKS",
        "Engagement",
        "Maximize number of link clicks",
        "engagement",
    ),
)

_BY_GOAL: Final[dict[tuple[str, str], tuple[CampaignType, ...]]] = {}
for _row in CAMPAIGN_TYPES:
    _BY_GOAL[(_row.provider, _row.goal)] = (
        *_BY_GOAL.get((_row.provider, _row.goal), ()),
        _row,
    )


@dataclass(frozen=True, slots=True)
class ShapeIndex:
    """What a campaign was built as, from the words the provider reads back."""

    exact: dict[tuple[str, str, str, str], CampaignType]
    claimed: frozenset[tuple[str, str]]

    @classmethod
    def of(cls, rows: tuple[CampaignType, ...]) -> "ShapeIndex":
        return cls(
            exact={
                (
                    row.provider,
                    row.objective,
                    row.destination_type,
                    row.optimization_goal,
                ): row
                for row in rows
            },
            claimed=frozenset(
                (row.provider, row.destination_type)
                for row in rows
                if row.destination_type
            ),
        )

    def find(
        self,
        *,
        provider: str,
        objective: str,
        destination_type: str,
        optimization_goal: str,
    ) -> CampaignType | None:
        if (provider, destination_type) in self.claimed:
            return self.exact.get(
                (provider, objective, destination_type, optimization_goal)
            )
        return self.exact.get((provider, objective, "", optimization_goal))


_BY_SHAPE: Final = ShapeIndex.of(CAMPAIGN_TYPES)


def types_for(*, provider: str, goal: str) -> tuple[CampaignType, ...]:
    """Every kind this goal may be bought as, default first. Empty if none."""
    return _BY_GOAL.get((provider, goal), ())


def default_type(*, provider: str, goal: str) -> CampaignType | None:
    """What a goal is bought as when nobody chose."""
    found = types_for(provider=provider, goal=goal)
    return found[0] if found else None


def campaign_type(*, provider: str, goal: str, key: str) -> CampaignType | None:
    """The chosen kind if it belongs to this goal, the default otherwise."""
    found = types_for(provider=provider, goal=goal)
    for row in found:
        if row.key == key:
            return row
    return found[0] if found else None


def type_built_as(
    *, provider: str, objective: str, destination_type: str, optimization_goal: str
) -> CampaignType | None:
    """The kind a campaign already running at the provider was built as."""
    return _BY_SHAPE.find(
        provider=provider,
        objective=objective,
        destination_type=destination_type,
        optimization_goal=optimization_goal,
    )


__all__ = [
    "CAMPAIGN_TYPES",
    "PERFORMANCE_GOAL_NAMES",
    "CampaignType",
    "ObjectiveGroup",
    "ShapeIndex",
    "campaign_type",
    "default_type",
    "type_built_as",
    "types_for",
]
