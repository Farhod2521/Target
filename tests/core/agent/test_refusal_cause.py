"""Which part of an advert a refusal is about - read from the provider's words."""

import pytest

from core.agent.refusal_cause import refusal_cause


@pytest.mark.parametrize(
    ("said", "cause"),
    [
        ("Personal Health: Ads may not imply a condition.", "words"),
        ("Personal attributes: The text asserts the viewer's age.", "words"),
        ("Personal attributes: The image implies the viewer's weight.", "picture"),
        ("IMAGE_TEXT: Too much text in the image.", "picture"),
        ("Adult Content: The video shows nudity.", "picture"),
        ("Landing Page Functionality: The destination does not load.", "site"),
        ("Prohibited Content: Tobacco products are not allowed.", "offer"),
        ("Unacceptable Business Practices: deceptive offer.", "offer"),
        ("Circumventing Systems: the ad tries to evade review.", "account"),
        ("Личные характеристики: текст объявления.", "words"),
        ("Изображение: на изображении слишком много текста.", "picture"),
        ("Целевая страница не работает.", "site"),
        ("ADVERTISING_POLICIES: Your ad was rejected.", "unknown"),
        ("", "unknown"),
    ],
)
def test_the_part_is_read_from_the_providers_words(said: str, cause: str) -> None:
    assert refusal_cause(said) == cause


def test_a_restricted_product_is_not_fixed_by_its_picture() -> None:
    """What the advert cannot fix outranks the part the words mention."""
    said = "Prohibited Content: the image shows a weapon."

    assert refusal_cause(said) == "offer"
