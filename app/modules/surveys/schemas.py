"""Response shapes for the survey dialog, for the API reference only.

Attached with ``responses=``: the routes still return plain dicts.
"""

from pydantic import BaseModel, Field


class AskedQuestionOut(BaseModel):
    id: str
    position: int
    kind: str = Field(description="`text`, `choice` or `number`.")
    text: str
    options: list[str] = Field(description="A choice's options; answer by index.")
    allows_many: bool
    numbers: list[int] = Field(description="A number question's buttons.")
    is_required: bool
    show_if: int = Field(
        description="Position of the earlier choice question this one hangs on; "
        "0 for always asked."
    )
    show_options: list[int] = Field(
        description="Option indexes there that open this question."
    )


class DueSurveyOut(BaseModel):
    survey_id: str
    language: str = Field(description="The language the words are in.")
    title: str
    intro: str
    questions: list[AskedQuestionOut]


class DueOut(BaseModel):
    survey: DueSurveyOut | None = Field(description="Null: nothing to ask now.")
    always: int = Field(
        description="How many questions are asked before any choice is made."
    )


class AnsweredOut(BaseModel):
    title: str
    message: str


class LaterOut(BaseModel):
    ask_again_in: int = Field(
        description="Seconds until `GET /surveys/due` is worth asking again."
    )
