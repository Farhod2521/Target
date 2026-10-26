"""A group's last three days at its week's own pace.

The brief prices "dearer" on the last three finished days - see
:func:`core.agent.usual.price_level` - so a fixture dear over the week is
dear lately too, unless its test says the last days were different.
"""

from dataclasses import fields

from core.agent import Recent
from core.metrics import Totals

DAYS = 3
WEEK = 7


def at_week_pace(totals: Totals, *, link_clicks: int | None = None) -> Recent:
    """Three sevenths of every count in ``totals``."""
    scaled = Totals(
        **{
            field.name: getattr(totals, field.name) * DAYS // WEEK
            for field in fields(Totals)
            if isinstance(getattr(totals, field.name), int)
            and not isinstance(getattr(totals, field.name), bool)
        }
    )
    clicks = totals.clicks if link_clicks is None else link_clicks
    return Recent(days=DAYS, totals=scaled, link_clicks=clicks * DAYS // WEEK)
