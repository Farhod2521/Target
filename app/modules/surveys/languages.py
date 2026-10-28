"""The languages a survey is kept in: every language the site speaks."""

from app.common.i18n import LANGUAGES

NAMES = {"uz": "O'zbekcha", "ru": "Русский", "en": "English"}


def all_languages() -> tuple[str, ...]:
    """Every language code the site is offered in, in the site's order."""
    return tuple(LANGUAGES)


def targets(source: str) -> tuple[str, ...]:
    """The languages a survey written in ``source`` is translated into."""
    return tuple(code for code in all_languages() if code != source)


def language_name(code: str) -> str:
    """The language's own name, as the site's switcher shows it."""
    return NAMES.get(code, code)
