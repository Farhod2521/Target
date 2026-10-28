"""Request and response shapes for the Google Sheets destination."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.destinations.constants import SheetMode


class ChoiceIn(BaseModel):
    """Where leads are written, chosen before Google. All empty mends a stopped
    link: Google again, nothing chosen."""

    mode: SheetMode | Literal[""] = Field(
        "", description="`single`, `per_form` or `own_file`; empty chooses nothing."
    )
    scope: Literal["all", "one", ""] = Field(
        "", description="For `own_file`: every form (`all`) or one (`one`)."
    )
    only_form: str = Field(
        "", max_length=64, description="The form's id when `scope` is `one`."
    )
    next: str = Field(
        "", description="Frontend path to come back to after Google; `/app/leads`."
    )


class PickIn(BaseModel):
    file_id: str = Field("", description="The Drive file id the picker handed back.")


class FormLabelOut(BaseModel):
    pk: str
    name: str
    page_name: str


class ChooserOut(BaseModel):
    own_file: bool = Field(description="Whether `own_file` may be offered at all.")
    forms: list[FormLabelOut] = Field(description="What `only_form` may name.")
    mode: str
    only_form: str


class FormFileOut(BaseModel):
    name: str = Field(description="Empty for the file of forms never recorded here.")
    url: str


class SheetPanelOut(BaseModel):
    state: Literal["off", "choosing", "preparing", "active", "broken"]
    mode: str
    url: str
    email: str
    reason: str = Field(description="A `BrokenReason` value when `state` is broken.")
    reason_label: str
    needs_new_sheet: bool = Field(description="`POST /sheet/recreate` fixes it.")
    needs_other_file: bool = Field(description="Another pick of the owner's file.")
    delayed: bool = Field(description="Preparing after Google turned an attempt away.")
    poll_seconds: int | None = Field(
        description="While preparing, how often to ask again: 3, or 30 when delayed."
    )
    since: datetime | None
    written: int
    files: list[FormFileOut]
    only_form_name: str
    only_form: str
    picker_ready: bool
    chooser: ChooserOut | None


class PanelOut(BaseModel):
    enabled: bool = Field(
        description="False when this deployment has no Google client."
    )
    panel: SheetPanelOut | None


class StartOut(BaseModel):
    url: str = Field(description="Google's consent screen: send the browser there.")


class ModeOut(BaseModel):
    url: str = Field(
        "", description="Set when the choice goes through Google: send the browser."
    )
    detail: str = ""
    panel: SheetPanelOut | None = None


class PickerOut(BaseModel):
    token: str
    key: str
    app_id: str
    locale: str
