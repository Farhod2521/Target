from typing import Final, NamedTuple

from app.common.choices import Choices
from app.modules.backoffice.constants import Role


class Board(Choices):
    SALES = "sales"
    SUPPORT = "support"


BOARD_LABELS = {Board.SALES: "Sotuv", Board.SUPPORT: "Support"}


class ColumnKind(Choices):
    # Moved by a button.
    MANUAL = "manual"
    # Moved by what happened to the client; wins over a manual column.
    AUTO = "auto"


COLUMN_KIND_LABELS = {ColumnKind.MANUAL: "Tugma bilan", ColumnKind.AUTO: "Avtomatik"}


class SalesColumn(Choices):
    UNWORKED = "unworked"
    NEW_LEAD = "new_lead"
    NO_CONTACT = "no_contact"
    CONTACTED = "contacted"
    # Kept hidden until the free trial and the discount are built.
    TRIAL = "trial"
    DISCOUNT_20 = "discount_20"
    DISCOUNT_10 = "discount_10"
    NO_DISCOUNT = "no_discount"
    SOLD = "sold"
    CLOSED = "closed"


SALES_COLUMN_LABELS = {
    SalesColumn.UNWORKED: "Ishlanmagan",
    SalesColumn.NEW_LEAD: "Yangi lead",
    SalesColumn.NO_CONTACT: "Bog'lanilmadi",
    SalesColumn.CONTACTED: "Bog'lanildi",
    SalesColumn.TRIAL: "Sinovda",
    SalesColumn.DISCOUNT_20: "20% chegirma",
    SalesColumn.DISCOUNT_10: "10% chegirma",
    SalesColumn.NO_DISCOUNT: "Chegirmasiz",
    SalesColumn.SOLD: "Sotildi",
    SalesColumn.CLOSED: "Yopildi",
}


class SupportColumn(Choices):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"


SUPPORT_COLUMN_LABELS = {
    SupportColumn.NEW: "Yangi",
    SupportColumn.IN_PROGRESS: "Ishlanmoqda",
    SupportColumn.RESOLVED: "Hal qilindi",
}


class SeedColumn(NamedTuple):
    board: Board
    code: str
    name: str
    kind: ColumnKind
    is_final: bool
    is_visible: bool


def _sales(
    code: SalesColumn, kind: ColumnKind, *, final: bool = False, shown: bool = True
) -> SeedColumn:
    return SeedColumn(
        Board.SALES, str(code), SALES_COLUMN_LABELS[code], kind, final, shown
    )


def _support(
    code: SupportColumn, kind: ColumnKind, *, final: bool = False
) -> SeedColumn:
    return SeedColumn(
        Board.SUPPORT, str(code), SUPPORT_COLUMN_LABELS[code], kind, final, True
    )


# The columns each board starts with, in their first order. The code never
# changes; the office may rename and reorder them.
SEED_COLUMNS: Final[tuple[SeedColumn, ...]] = (
    _sales(SalesColumn.UNWORKED, ColumnKind.AUTO),
    _sales(SalesColumn.NEW_LEAD, ColumnKind.MANUAL),
    _sales(SalesColumn.NO_CONTACT, ColumnKind.MANUAL),
    _sales(SalesColumn.CONTACTED, ColumnKind.MANUAL),
    _sales(SalesColumn.TRIAL, ColumnKind.AUTO, shown=False),
    _sales(SalesColumn.DISCOUNT_20, ColumnKind.AUTO, shown=False),
    _sales(SalesColumn.DISCOUNT_10, ColumnKind.AUTO, shown=False),
    _sales(SalesColumn.NO_DISCOUNT, ColumnKind.AUTO, shown=False),
    _sales(SalesColumn.SOLD, ColumnKind.AUTO, final=True),
    _sales(SalesColumn.CLOSED, ColumnKind.MANUAL, final=True),
    _support(SupportColumn.NEW, ColumnKind.AUTO),
    _support(SupportColumn.IN_PROGRESS, ColumnKind.MANUAL),
    _support(SupportColumn.RESOLVED, ColumnKind.MANUAL, final=True),
)

# Columns only a board's lead (and the superuser or Owner) sees.
LEAD_ONLY_COLUMNS: Final = frozenset(
    {str(SalesColumn.UNWORKED), str(SalesColumn.CLOSED)}
)

# Who works each board. The superuser and the Owner role see both.
BOARD_ROLES: Final = {
    Board.SALES: (Role.SALES, Role.SALES_LEAD),
    Board.SUPPORT: (Role.SUPPORT,),
}
LEAD_ROLES: Final = {Board.SALES: (Role.SALES_LEAD,), Board.SUPPORT: ()}
FULL_ROLES: Final = (Role.OWNER,)

COLUMN_NAME_MAX: Final = 40
CODE_MAX: Final = 24
