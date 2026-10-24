"""Which kinds of campaign may deliver each goal - one table, in one place.

A goal says where the result happens: a call, a form, a visit to the site.
It does not say which of the provider's campaign kinds buys it, and the
provider offers more than one for most goals - a call can be bought under
traffic, under engagement or under leads, and each finds a different
person. This table is the whole of what may be chosen.

**Every kind the provider's own screen offers for the goal.** Its
documentation is not the source - it disagrees with that screen in both
directions - and neither is what the provider will *save*: an empty ad set
is kept under almost any pairing, so a save proves nothing. What is listed
is what somebody sitting in Ads Manager can pick for this conversion
location, which is the only list a person buying advertising can check
this one against.

**The first row of a goal is its default, and it is the proven one** - the
shape advertisers here have run and paid for. It also has to be what the
catalogue's preset already builds, and a test holds the two together, so a
launch that never chose builds exactly what the preset describes. The rows
under it are alternatives somebody asked for; only the first carries the
weight of having delivered.

**No two rows may share the provider's words.** A campaign already
running is named by reading back its objective, destination and
optimisation goal, and a shape that two kinds share could not be named.
Where the screen offers the same pairing under two goals - link clicks
sit under a form and under a website request alike - the one kept is the
one whose goal it does not contradict: a form campaign bought on clicks
would sell somebody the opposite of the result they asked for.

A kind changes two provider words: the objective and the optimisation
goal. Where the tap lands, the button and what the ad set promotes stay the
preset's - except on a row that names a destination of its own, which no
preset of its goal lands on.

Provider vocabulary on purpose, like the presets beside it: these words are
what gets sent. What the owner reads is decided above this package.
"""

from dataclasses import dataclass
from typing import Final, Literal

# The provider's objectives, as the first step groups its rows. Sales has no
# row yet and is still a group: the step shows it, switched off.
ObjectiveGroup = Literal["awareness", "traffic", "engagement", "leads", "sales"]


@dataclass(frozen=True, slots=True)
class CampaignType:
    """One way of buying one goal."""

    provider: str
    goal: str
    # Ours, and unique across the whole table. A key stored for one goal can
    # then never be read as a choice made for another after the goal changes.
    key: str
    objective: str
    optimization_goal: str
    # What the provider's own screen calls the objective and the
    # optimisation goal. Shown beside the owner's words to somebody who buys
    # advertising for a living - never the API's spelling of either.
    provider_label: str
    provider_goal_label: str
    # Which of the provider's objectives the row sits under, in our own
    # lower-case word. What the first step groups the rows by, and what the
    # screen names beside them - never sent anywhere.
    objective_group: ObjectiveGroup
    # Where the ad set lands, in the provider's read-back word - set only on
    # a row that lands somewhere no preset of its goal already does. Empty
    # everywhere else: those rows keep the preset's destination, whatever
    # word the provider stores for it, and are read back under any word no
    # other row claims.
    destination_type: str = ""

    @property
    def provider_goal_name(self) -> str:
        """The performance goal's short name, as Ads Manager heads its rows.

        What tells two rows under one objective and destination apart on a
        line too narrow for the whole of :attr:`provider_goal_label`.
        """
        return PERFORMANCE_GOAL_NAMES.get(
            self.provider_goal_label, self.provider_goal_label
        )


# The short name of each performance goal the table uses, keyed by its full
# name in Ads Manager.
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
    # A call: many and cheap, from people who engage, or from people ready
    # to act. All three dial the same number from the same button.
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
    # A form on the ad.
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
    # A visit to the site: counted when the page opens, or when the link is
    # tapped - the second needs no pixel on the site to be counted at all.
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
    # A visit to the business's Instagram profile rather than its site. The
    # one row that lands somewhere its preset alone decides, so it names the
    # destination: the same ad set bought on link clicks is Meta's too, and
    # read back without it would be named a site visit.
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
    # The same visit bought by how many people see it rather than by what
    # they do: the two the screen offers under this objective for somebody
    # who wants the address in front of a wider room.
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
    # A request left on the advertiser's own site, counted by the pixel.
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
    # The same goal bought on something the provider can count by itself.
    # Worth having because the pixel is the weak part of this route: one
    # that never reports the request leaves the conversion row delivering
    # to nobody, while these three deliver on what the provider sees.
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
    # Seen: as often as possible, or by as many people as possible.
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
    # A conversation, which Meta sells against two different events.
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
    """What a campaign was built as, from the words the provider reads back.

    Every row is the only one with its objective, destination and
    optimisation goal - a test holds that. A row with no destination of its
    own answers for any destination word **except** one another row claims:
    an ad set landing on a claimed destination is that row's or nobody's,
    never the nearest row that happens to share its other two words.
    """

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
    """The chosen kind if it belongs to this goal, the default otherwise.

    A key that belongs to another goal falls back rather than raising. It
    is what a launch holds after its goal was changed, and the answer to a
    choice made for a different result is the default of this one.

    ``None`` only for a goal the table has no rows for, which the builder
    reads as "the preset decides".
    """
    found = types_for(provider=provider, goal=goal)
    for row in found:
        if row.key == key:
            return row
    return found[0] if found else None


def type_built_as(
    *, provider: str, objective: str, destination_type: str, optimization_goal: str
) -> CampaignType | None:
    """The kind a campaign already running at the provider was built as.

    ``None`` for a shape outside the table - a campaign made by hand in
    the provider's own screen can be anything, and naming it after the
    nearest row would be the screen guessing.
    """
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
