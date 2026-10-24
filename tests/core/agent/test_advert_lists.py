"""The advert lists hold as many adverts as the launch has pictures."""

from core.agent.copy_review import CopyReview
from core.agent.schemas import CreativeSection

SIX = 6


def _advert() -> dict[str, str]:
    return {"primary_text": "Matn", "headline": "Sarlavha", "description": "Qator"}


def test_try_something_else_writes_a_text_for_a_sixth_picture() -> None:
    section = CreativeSection.model_validate({"creatives": [_advert()] * SIX})

    assert len(section.creatives) == SIX


def test_the_second_read_covers_a_sixth_advert() -> None:
    review = CopyReview.model_validate({"adverts": [_advert()] * SIX})

    assert len(review.adverts) == SIX
