from enum import Enum
from typing import Final

from app.common.choices import Choices


class AnyAccount(Enum):
    EVERY = "every"


EVERY_ACCOUNT: Final = AnyAccount.EVERY


class MetricLevel(Choices):
    CAMPAIGN = "campaign"
    ADSET = "adset"
    AD = "ad"


METRIC_LEVEL_LABELS = {
    MetricLevel.CAMPAIGN: "Kampaniya",
    MetricLevel.ADSET: "Guruh",
    MetricLevel.AD: "Reklama",
}
INSIGHT_LEVELS: Final[tuple[MetricLevel, ...]] = (
    MetricLevel.ADSET,
    MetricLevel.CAMPAIGN,
    MetricLevel.AD,
)
INSIGHTS_LOCK_SECONDS: Final = 660


class Ranking(Choices):
    ABOVE_AVERAGE = "above_average"
    AVERAGE = "average"
    BELOW_AVERAGE_35 = "below_average_35"
    BELOW_AVERAGE_20 = "below_average_20"
    BELOW_AVERAGE_10 = "below_average_10"
    UNKNOWN = "unknown"


RANKING_LABELS = {
    Ranking.ABOVE_AVERAGE: "O'rtachadan yuqori",
    Ranking.AVERAGE: "O'rtacha",
    Ranking.BELOW_AVERAGE_35: "Pastki 35%",
    Ranking.BELOW_AVERAGE_20: "Pastki 20%",
    Ranking.BELOW_AVERAGE_10: "Pastki 10%",
    Ranking.UNKNOWN: "Ma'lumot yetarli emas",
}


class BreakdownKind(Choices):
    AGE_GENDER = "age_gender"
    PLATFORM_POSITION = "platform_position"
    REGION = "region"


BREAKDOWN_KIND_LABELS = {
    BreakdownKind.AGE_GENDER: "Yosh va jins",
    BreakdownKind.PLATFORM_POSITION: "Platforma va joylashuv",
    BreakdownKind.REGION: "Hudud",
}
BREAKDOWN_LEVEL: Final = MetricLevel.ADSET
NIGHTLY_BREAKDOWNS: Final[tuple[BreakdownKind, ...]] = (
    BreakdownKind.PLATFORM_POSITION,
    BreakdownKind.REGION,
    BreakdownKind.AGE_GENDER,
)
BREAKDOWN_BACKFILL_DAYS: Final = 30
BREAKDOWN_CHUNK_DAYS: Final = 15
BREAKDOWN_RETENTION_DAYS: Final = 90
AD_METRICS_RETENTION_DAYS: Final = 180
WRITE_BATCH: Final = 1000
PURGE_BATCH: Final = 5000
PERIOD_DAYS: Final[tuple[int, ...]] = (7, 30, 90)
BACKFILL_DAYS: Final = 90
MIN_READ_DAYS: Final = 7
BACKFILL_RETRY_HOURS: Final = 6


class Period(Choices):
    TODAY = "today"
    SEVEN = "7"
    THIRTY = "30"
    NINETY = "90"


PERIOD_LABELS = {
    Period.TODAY: "Bugun",
    Period.SEVEN: "7 kun",
    Period.THIRTY: "30 kun",
    Period.NINETY: "90 kun",
}
PERIOD_LENGTHS: Final[dict[str, int]] = {
    Period.TODAY: 1,
    Period.SEVEN: 7,
    Period.THIRTY: 30,
    Period.NINETY: 90,
}
PEOPLE_LEVELS: Final[tuple[MetricLevel, ...]] = (
    MetricLevel.CAMPAIGN,
    MetricLevel.ADSET,
    MetricLevel.AD,
)
PEOPLE_ROLLING_DAYS: Final[tuple[int, ...]] = (14, 28)
PEOPLE_REFRESH_SECONDS: Final = 25 * 60
PEOPLE_ASKED_SECONDS: Final = 2 * 60
DEFAULT_PERIOD: Final = Period.THIRTY


class Source(Choices):
    HERE = "here"
    ELSEWHERE = "elsewhere"
    ALL = "all"


SOURCE_LABELS = {
    Source.HERE: "Shu yerda yaratilgan",
    Source.ELSEWHERE: "Meta'da yaratilgan",
    Source.ALL: "Hammasi",
}
DEFAULT_SOURCE: Final = Source.HERE
NUMBERS_FILTERS_SESSION_KEY: Final = "metrics:numbers_filters"
RANGE_MAX_DAYS: Final = 90
RESTATE_DAYS: Final = 14
OBSERVED_RESTATE_DAYS: Final = 30
RECONCILE_PCT: Final = 10
RECONCILE_FROM: Final = 5
REFUSED_SAMPLE: Final = 10
STALE_HOURS: Final = 30
FIGURES_NEW_ACCOUNT_HOURS: Final = 24
FIGURES_REPORT_SAMPLE: Final = 10
UNTRACKED_DAYS: Final = 7
JUDGED_SHARE_FLOOR: Final = 50
TOP_CAMPAIGNS: Final = 8
RECENT_LEADS: Final = 6
RECENT_DECISIONS: Final = 6
TOP_SOURCES: Final = 5
SYNC_STALE_MINUTES: Final = 15
MAX_SYNC_POLLS: Final = 20
SYNC_POLL_SECONDS: Final = 3
AUTO_REFRESH_COOLING_MINUTES: Final = 2
FIGURES_LANDED: Final = "figures-landed"
CHASE_LEADS_KEY: Final = "metrics:chase-leads:{page}"
CHASE_LEADS_SECONDS: Final = 15 * 60
RETRY_SPREAD_SECONDS = 180
