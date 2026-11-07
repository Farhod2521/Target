"""The answers of ``/api/v2/campaigns/expert``: rows with a cell per metric."""

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from app.common.contract import Camel, Money, Refusal
from app.modules.ads.contract.shapes import Controls, NetworkRef
from app.modules.ads.contract.words import Kind, Status


class Cell(Camel):
    value: int | float | str | None = Field(
        description="Money in minor units of the row's currency, a count, a "
        "percentage or ratio to hundredths, or a ranking word; null with `missing`."
    )
    missing: str | None = Field(
        description="Why there is no value; the words are in `/expert/columns`."
    )


class ExpertRow(Camel):
    level: Literal["campaign", "adset", "ad"]
    id: str = Field(description="The network's id of this row.")
    campaign_id: str = Field(description="This product's id of the campaign.")
    campaign_external_id: str
    adset_external_id: str | None
    name: str
    status: Status
    kind: Kind
    network: NetworkRef
    budget: Money | None
    budget_at: Literal["campaign", "adset"]
    controls: Controls
    problem: str | None = None
    refusal: Refusal | None = None
    rejection: Refusal | None = None
    opens: Literal["form", "chat"] | None = Field(
        None, description="An advert's row: what its button opens (TZ 2.6)."
    )
    can_swap: bool | None = Field(
        None, description="An advert's row: false when its words live on a post."
    )
    outcome: str = Field(description="What one result is for this row's goal.")
    currency: str
    cells: dict[str, Cell] = Field(description="One per metric, keyed by its key.")


class ExpertTotal(Camel):
    count: int
    currency: str | None = Field(description="Null when the rows' currencies differ.")
    cells: dict[str, Cell]


class ExpertTotals(Camel):
    campaigns: ExpertTotal
    adsets: ExpertTotal
    ads: ExpertTotal


class ExpertRange(Camel):
    since: date | None
    until: date | None


class Attribution(Camel):
    asked: str = Field(description="The window every figure is asked under.")
    differs: bool = Field(
        description="An account is set to another window in Ads Manager, so its "
        "lead counts will not match there."
    )


class ExpertTable(Camel):
    campaigns: list[ExpertRow]
    adsets: list[ExpertRow]
    ads: list[ExpertRow]
    totals: ExpertTotals
    range: ExpertRange
    synced_at: datetime | None
    attribution: Attribution


class Column(Camel):
    key: str
    label: str
    hint: str
    group: str
    unit: Literal["money", "count", "percent", "ratio", "ranking"]
    lower_is_better: bool
    norm: str


class ColumnLevels(Camel):
    campaigns: list[Column]
    adsets: list[Column]
    ads: list[Column]


class Preset(Camel):
    key: str
    label: str
    columns: list[str]


class ExpertColumns(Camel):
    levels: ColumnLevels
    chosen: list[str] = Field(description="The columns kept on, in their order.")
    presets: list[Preset]
    missing: dict[str, str] = Field(description="Words for every `missing` reason.")


class ColumnsIn(Camel):
    chosen: list[str]


__all__ = [
    "Cell",
    "ColumnsIn",
    "ExpertColumns",
    "ExpertRow",
    "ExpertTable",
]
