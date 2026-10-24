"""Google, for the one thing this product asks of it: a spreadsheet of leads."""

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
