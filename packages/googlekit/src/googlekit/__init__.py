"""Google, for the one thing this product asks of it: a spreadsheet of leads.

Built like ``telegramkit`` rather than like ``metaads``. There is no port
and no registry: a spreadsheet is not an ad platform, and there is no
second one coming for the domain to be kept ignorant of. What is kept from
``metaads`` is the part about correctness - timeouts on both halves,
failures split by what the caller should do about them, and credentials
kept out of every string that can reach a log.

Two halves. :mod:`googlekit.oauth` signs somebody in and keeps the
permission alive; :class:`SheetsClient` creates the spreadsheet and writes
into it. Both take the credential as an argument, and neither reads
configuration or the clock.

The permission asked for is ``drive.file`` and nothing wider: files this
app created, and no other file in the person's Drive. That is the whole of
what the product needs - it creates the one spreadsheet it writes to - and
it is the scope Google classes as non-sensitive.
"""

from googlekit.cells import CELL_MAX_CHARS, DATE_TIME_PATTERN, CellValue, serial
from googlekit.errors import (
    AccessRevoked,
    GoogleAPIError,
    GoogleError,
    OutcomeUnknown,
    PermissionMissing,
    RateLimited,
    SheetMissing,
    TabMissing,
    Unavailable,
)
from googlekit.models import DriveFile, Grant, SheetColumn, Spreadsheet, Tab
from googlekit.oauth import (
    DEFAULT_SCOPES,
    SCOPE_ADWORDS,
    SCOPE_DRIVE_FILE,
    authorize_url,
    exchange_code,
    refresh,
    revoke,
)
from googlekit.sheets import SheetsClient

__all__ = [
    "CELL_MAX_CHARS",
    "DATE_TIME_PATTERN",
    "DEFAULT_SCOPES",
    "SCOPE_ADWORDS",
    "SCOPE_DRIVE_FILE",
    "AccessRevoked",
    "CellValue",
    "GoogleAPIError",
    "GoogleError",
    "Grant",
    "OutcomeUnknown",
    "PermissionMissing",
    "RateLimited",
    "SheetColumn",
    "SheetMissing",
    "SheetsClient",
    "Spreadsheet",
    "TabMissing",
    "Unavailable",
    "authorize_url",
    "exchange_code",
    "refresh",
    "revoke",
    "serial",
]
