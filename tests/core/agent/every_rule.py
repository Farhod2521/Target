"""The scan over the whole table, the rules that sleep included.

Four rules were retired when the half-hourly guard took over the money they
watched (``core.agent.guard``). What each of them concludes is still proven
by the tests written for it: they scan with this, the table as it was.
"""

from functools import partial

from core.agent.rules import EVERY_RULE
from core.agent.rules import scan as _scan

scan = partial(_scan, rules=EVERY_RULE)

__all__ = ["scan"]
