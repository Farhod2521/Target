"""What Google answered, in the shapes this product reads."""

from pydantic import BaseModel, ConfigDict, Field


class Grant(BaseModel):
    """One answer from the token endpoint.

    ``refresh_token`` is blank more often than not. Google sends one on a
    first consent and on a forced one, never on a refresh - so a caller
    keeps the refresh token it already holds whenever this one is empty.

    The tokens and the email are left out of ``repr``. A DTO printed in a
    traceback is the easiest way for a credential to reach a log.
    """

    model_config = ConfigDict(frozen=True)

    access_token: str = Field(repr=False)
    refresh_token: str = Field(default="", repr=False)
    expires_in: int = 0
    # What was actually granted, which is not what was asked for: Google's
    # consent screen lets a person untick a permission and still press
    # continue.
    scopes: tuple[str, ...] = ()
    email: str = Field(default="", repr=False)
    # Google's own id for the person (the ID token's ``sub``). Unlike the
    # email it never changes, so it is what a rule about one person across
    # cabinets is keyed to.
    subject: str = ""

    def holds(self, scope: str) -> bool:
        """Whether this grant includes ``scope``."""
        return scope in self.scopes


class Tab(BaseModel):
    """One tab: the id every write addresses, and the name a person sees.

    Both are needed and neither stands in for the other. Writes go by id,
    because somebody renaming a tab must not stop them; a caller adding a
    tab of its own needs the names, because Sheets refuses a second tab
    called what one in the file is already called.
    """

    model_config = ConfigDict(frozen=True)

    # A string, like every id this package hands out - see
    # ``googlekit.sheets`` for where the number is rebuilt.
    sheet_id: str
    title: str = ""


class Spreadsheet(BaseModel):
    """A spreadsheet this app can reach, and the tabs inside it."""

    model_config = ConfigDict(frozen=True)

    spreadsheet_id: str
    url: str = ""
    # In the order Google lists them. A new spreadsheet has one; a file
    # somebody has worked in may have several, and the tab this app writes
    # to is found by id rather than by position.
    tabs: tuple[Tab, ...] = ()

    @property
    def sheet_ids(self) -> tuple[str, ...]:
        """Every tab's id, in the order Google listed them."""
        return tuple(tab.sheet_id for tab in self.tabs)

    @property
    def titles(self) -> frozenset[str]:
        """Every tab's name - what a caller picking a free one compares with."""
        return frozenset(tab.title for tab in self.tabs)


class DriveFile(BaseModel):
    """What Drive says about one file this app may touch.

    Asked before a tab is added to a file somebody picked themselves. A
    file in the bin, a file that is not a spreadsheet at all, and one
    shared with them read-only each fail that write - and each of them is
    a different sentence on the screen.
    """

    model_config = ConfigDict(frozen=True)

    file_id: str
    name: str = ""
    mime_type: str = ""
    trashed: bool = False
    # An absent ``capabilities`` is read as "yes". The write itself is the
    # authority on whether it may happen, and refusing over a field Google
    # left out of an answer would stop a link that works.
    can_edit: bool = True


class SheetColumn(BaseModel):
    """One column as it is created: a heading, a width, and whether it shows."""

    model_config = ConfigDict(frozen=True)

    header: str
    width_px: int = 120
    hidden: bool = False


__all__ = ["DriveFile", "Grant", "SheetColumn", "Spreadsheet", "Tab"]
