"""What the knowledge routes of ``/api/v3/businesses`` say and take."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Op = Literal[
    "set_about",
    "add_item",
    "update_item",
    "archive_item",
    "restore_item",
    "set_fact",
    "clear_fact",
]


class ChoiceOut(BaseModel):
    key: str
    label: str


class ChangeIn(BaseModel):
    """One small change. Which fields it reads depends on ``op``:

    - ``set_about``: ``text`` (empty clears it);
    - ``add_item``: ``name``, and optionally ``kind``, ``price``, ``note``,
      ``link``. A name already on the list updates that item instead;
    - ``update_item``: ``id`` and the fields to change;
    - ``archive_item``, ``restore_item``: ``id``;
    - ``set_fact``: ``key`` and ``value``; ``clear_fact``: ``key``.
    """

    op: Op
    id: str | None = Field(None, max_length=32)
    text: str | None = None
    name: str | None = None
    kind: str | None = None
    price: str | None = None
    note: str | None = None
    link: str | None = None
    key: str | None = None
    value: str | None = None


class ChangesIn(BaseModel):
    changes: list[ChangeIn] = Field(min_length=1, max_length=40)
    version: int | None = Field(
        None,
        description="The version the form was filled over. Sent by a form that "
        "edits what it read; a write that only adds leaves it out.",
    )


class KindIn(BaseModel):
    direction: str = Field(
        min_length=1, max_length=64, description="A direction's key."
    )
    subtype_id: uuid.UUID | None = None
    subtype: str | None = Field(
        None,
        max_length=80,
        description="A narrower kind by name: found under the direction, or made.",
    )


class SubtypeOut(BaseModel):
    id: uuid.UUID
    name: str
    is_checked: bool


class KindOut(BaseModel):
    direction: ChoiceOut | None
    label: str
    state: Literal["unset", "guessed", "confirmed"]
    subtype: SubtypeOut | None


class AboutOut(BaseModel):
    text: str
    source: str
    source_label: str
    at: datetime | None


class ItemOut(BaseModel):
    id: str
    name: str
    kind: str
    kind_label: str
    price: str
    note: str
    link: str
    status: Literal["active", "archived"]
    source: str
    source_label: str
    at: datetime | None


class FactOut(BaseModel):
    key: str
    label: str
    value: str
    source: str
    source_label: str
    at: datetime | None


class KnowledgeProposalOut(BaseModel):
    id: str
    source: str
    source_label: str
    why: str
    at: datetime | None
    lines: list[str] = Field(description="Each change in words, ready to show.")
    changes: list[dict[str, object]]


class KnowledgeAdviceOut(BaseModel):
    goal_first: ChoiceOut
    reason_first: str
    goal_second: ChoiceOut | None
    when_second: str
    never_say: str


class KnowledgeOut(BaseModel):
    business_id: uuid.UUID
    kept_by: uuid.UUID = Field(
        description="The business whose knowledge this is: the page's own "
        "business for a page's second ad account, otherwise the same id."
    )
    version: int
    may_edit: bool
    kind: KindOut
    does: str = Field(description="What the business does, in its own words.")
    about: AboutOut | None
    items: list[ItemOut]
    facts: list[FactOut]
    pending: list[KnowledgeProposalOut]
    advice: KnowledgeAdviceOut | None


class KnowledgeCatalogOut(BaseModel):
    directions: list[ChoiceOut]
    item_kinds: list[ChoiceOut]
    fact_keys: list[ChoiceOut]
    sources: list[ChoiceOut]
    goals: list[ChoiceOut]
    ops: list[str]
    limits: dict[str, int]


class SubtypesOut(BaseModel):
    direction: ChoiceOut | None
    subtypes: list[SubtypeOut]


class KnowledgeEventOut(BaseModel):
    id: uuid.UUID
    at: datetime
    kind: str
    label: str
    via: str
    source: str
    source_label: str
    by_name: str
    lines: list[str]


class KnowledgeHistoryOut(BaseModel):
    items: list[KnowledgeEventOut]
