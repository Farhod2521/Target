"""The shape of Claude's second read of advert copy.

Its own module rather than a few more classes in ``schemas.py``: this is the
one answer here that is not a proposal. It judges one - problem by problem,
with the words that show each - and hands back the advert with them fixed.

Problems first in each item, and that order is the instruction. The model
fills the fields in the order the schema lists them, so a list of what is
wrong is written before the corrected text rather than justified after it.
"""

from typing import Literal

from pydantic import BaseModel, Field

CopyProblemCode = Literal[
    "changed_fact",
    "invented_promise",
    "personal_attribute",
    "action_mismatch",
    "contact_rule",
]


class CopyProblem(BaseModel):
    """One thing wrong with an advert."""

    code: CopyProblemCode = Field(
        description=(
            "changed_fact - egasi yozmagan yoki boshqa narsaga bog'langan fakt; "
            "invented_promise - egasi aytmagan va'da; personal_attribute - "
            "o'quvchining sog'lig'i, tanasi yoki puli haqida gap; "
            "action_mismatch - tugma qilmaydigan ishni so'rash; contact_rule - "
            "telefon raqami qoidasi buzilgan."
        )
    )
    quote: str = Field(
        description="Reklamadagi noto'g'ri so'zlar, aynan ko'chirilgan.",
        max_length=300,
    )


class ReviewedAdvert(BaseModel):
    """One advert after the second read, fixed where anything was wrong."""

    problems: list[CopyProblem] = Field(
        default_factory=list,
        description="Topilgan muammolar. Reklama to'g'ri bo'lsa - bo'sh ro'yxat.",
        max_length=8,
    )
    # Empty when nothing was wrong. The words are kept from the advert
    # itself, and an echo of every right advert was the bulk of the answer:
    # paid for at the output price and thrown away by the caller.
    primary_text: str = Field(
        default="",
        description=(
            "Asosiy matn. Muammo bo'lmasa - bo'sh qoldiring. Bo'lsa - faqat "
            "muammo tuzatilgan holda. 300 belgidan oshmasin."
        ),
        max_length=300,
    )
    headline: str = Field(
        default="",
        description="Sarlavha, 40 belgidan oshmasin. Muammo bo'lmasa - bo'sh.",
        max_length=60,
    )
    description: str = Field(
        default="",
        description=(
            "Qo'shimcha qator, 120 belgidan oshmasin. Muammo bo'lmasa - bo'sh."
        ),
        max_length=120,
    )


class CopyReview(BaseModel):
    """Every advert that was proposed, in the order it was proposed.

    No ceiling, for the reason ``LaunchDraft.creatives`` has none.
    """

    adverts: list[ReviewedAdvert] = Field(
        description="Promptdagi har reklamaga bittadan, o'sha tartibda.",
        min_length=1,
    )
