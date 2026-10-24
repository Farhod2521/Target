"""The vocabulary the advert-copy check reads, and how text is made comparable."""

import re
from typing import Final

_CYRILLIC: Final[dict[str, str]] = {
    chr(code): latin
    for code, latin in (
        (0x0430, "a"), (0x0431, "b"), (0x0432, "v"), (0x0433, "g"),
        (0x0434, "d"), (0x0435, "e"), (0x0451, "yo"), (0x0436, "j"),
        (0x0437, "z"), (0x0438, "i"), (0x0439, "y"), (0x043A, "k"),
        (0x043B, "l"), (0x043C, "m"), (0x043D, "n"), (0x043E, "o"),
        (0x043F, "p"), (0x0440, "r"), (0x0441, "s"), (0x0442, "t"),
        (0x0443, "u"), (0x0444, "f"), (0x0445, "x"), (0x0446, "ts"),
        (0x0447, "ch"), (0x0448, "sh"), (0x0449, "sh"), (0x044A, "'"),
        (0x044B, "i"), (0x044C, ""), (0x044D, "e"), (0x044E, "yu"),
        (0x044F, "ya"), (0x045E, "o'"), (0x049B, "q"), (0x0493, "g'"),
        (0x04B3, "h"),
    )
}  # fmt: skip

_APOSTROPHES: Final = re.compile(
    "[" + "".join(map(chr, (0x02BB, 0x02BC, 0x2018, 0x2019, 0x60, 0xB4))) + "]"
)
_SPACES: Final = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Lower case, Latin letters, one apostrophe, single spaces."""
    lowered = _APOSTROPHES.sub("'", text.lower())
    latin = "".join(_CYRILLIC.get(char, char) for char in lowered)
    return _SPACES.sub(" ", latin).strip()


PROMISES: Final[dict[str, tuple[str, ...]]] = {
    "free": ("bepul", "tekin", "besplatn"),
    "discount": ("chegirma", "skidk", "aksiya", "aktsiy"),
    "gift": ("sovg'a", "sovga", "podar", "bonus"),
    "guarantee": ("kafolat", "garant"),
    "best": (
        "eng yaxshi",
        "eng zo'r",
        "eng arzon",
        "eng sifatli",
        "eng taniqli",
        "1-raqamli",
        "luchsh",
    ),
}

SENSITIVE: Final[tuple[str, ...]] = (
    "to'kil",
    "kallik",
    "semiz",
    "ortiqcha vazn",
    "vazn",
    "kasal",
    "og'ri",
    "diabet",
    "husnbuzar",
    "akne",
    "ekzema",
    "bepusht",
    "depress",
    "ajin",
    "potens",
    "qarz",
    "kredit",
    "kambag'al",
)

SECOND_PERSON: Final = re.compile(
    r"(?<![a-z'])(siz|sizda|sizni|sizga|sizdan)(?![a-z'])|ngiz|sizmi(?![a-z'])"
)

ACTIONS: Final[dict[str, tuple[str, ...]]] = {
    "call": ("qo'ng'iroq qiling", "qo'ng'iroq qilib", "telefon qiling", "pozvonit"),
    "chat": ("xabar yozing", "xabar qoldiring", "direct", "direktga", "lichka"),
    "comment": ("izohga", "izohlarda", "izoh qoldiring", "komment"),
    "site": ("saytga", "saytimiz", "sayt orqali", "saytda", "havola orqali"),
    "order": ("buyurtma bering", "buyurtma qiling", "sotib oling", "xarid qiling"),
    "form": (
        "ariza qoldiring",
        "raqamingizni qoldiring",
        "formani to'ldiring",
        "ro'yxatdan o'ting",
    ),
}

ALLOWED_ACTIONS: Final[dict[str, frozenset[str]]] = {
    "form": frozenset({"form"}),
    "chat": frozenset({"chat", "order"}),
    "phone": frozenset({"call", "order"}),
    "website": frozenset({"site", "order", "form"}),
    "store": frozenset({"order", "call", "site"}),
    "nothing": frozenset(ACTIONS),
}

PHONE_UNWANTED: Final = frozenset({"form", "chat"})
PHONE_KEPT: Final = frozenset({"website", "phone", "store"})


def has_stem(text: str, stem: str) -> bool:
    """Whether a normalized text holds the stem at the start of a word."""
    return re.search(rf"(?<![a-z0-9']){re.escape(stem)}", text) is not None


def first_stem(text: str, stems: tuple[str, ...]) -> str:
    """The first of the stems the text holds, or ``""``."""
    return next((stem for stem in stems if has_stem(text, stem)), "")
