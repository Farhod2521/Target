"""``django.utils.text`` helpers ported code leans on."""

import re
import unicodedata


def slugify(value: object, allow_unicode: bool = False) -> str:
    text = str(value)
    if allow_unicode:
        text = unicodedata.normalize("NFKC", text)
    else:
        text = (
            unicodedata.normalize("NFKD", text)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-_")


def capfirst(value: str) -> str:
    return value[:1].upper() + value[1:] if value else value


def get_text_list(items: list[str], last_word: str = "va") -> str:
    if not items:
        return ""
    if len(items) == 1:
        return str(items[0])
    return f"{', '.join(str(i) for i in items[:-1])} {last_word} {items[-1]}"
