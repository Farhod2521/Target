"""The vocabulary the advert-copy check reads, and how text is made comparable.

Lists of word stems rather than a model, because the questions asked of them
are narrow and the answer has to be the same every time it is asked: is this
promise in what the owner wrote, does this sentence tell somebody to do
something the button does not do.

Everything is compared in one spelling. An owner writes in Latin or in
Cyrillic, in Uzbek or in Russian, with any of several apostrophes, and the
copy comes back in Latin Uzbek - so both sides are lowered, transliterated
and given one apostrophe before a stem is looked for.
"""

import re
from typing import Final

# Uzbek Cyrillic, then the Russian letters Uzbek does not use, each by code
# point beside its Latin spelling. Code points rather than the letters: in an
# editor a Cyrillic "a" cannot be told from a Latin one, which is exactly what
# the linter refuses them for. One table for both languages, so a Russian
# offer's stems ("besplatn", "skidk") are listed below in the spelling this
# produces.
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

# Modifier letters, typographic quotes, a backtick and an acute accent - every
# way "o'" and "g'" arrive from a phone keyboard.
_APOSTROPHES: Final = re.compile(
    "[" + "".join(map(chr, (0x02BB, 0x02BC, 0x2018, 0x2019, 0x60, 0xB4))) + "]"
)
_SPACES: Final = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Lower case, Latin letters, one apostrophe, single spaces."""
    lowered = _APOSTROPHES.sub("'", text.lower())
    latin = "".join(_CYRILLIC.get(char, char) for char in lowered)
    return _SPACES.sub(" ", latin).strip()


# Promises a model adds because adverts usually carry them. Each group is one
# promise in its several spellings; the copy may make it only when the owner's
# own text makes it too, in any spelling of the same group.
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

# What a sentence may not say *about the reader*. Meta refuses an advert that
# asserts or implies somebody's health, body or money - "Are you losing your
# hair?" - and may review the whole account for it. The same words about
# people in general, or about the service, are allowed, which is why these
# are only a finding beside a second-person marker in the same sentence.
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

# "You", in the forms an advert uses it: the pronoun, and the possessive and
# verb endings that carry it without the pronoun.
SECOND_PERSON: Final = re.compile(
    r"(?<![a-z'])(siz|sizda|sizni|sizga|sizdan)(?![a-z'])|ngiz|sizmi(?![a-z'])"
)

# What a closing sentence can ask somebody to do, by the kind of action.
# Imperatives only: "mutaxassis qo'ng'iroq qiladi" is a promise about the
# form, not a request to ring.
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

# Which of those actions the button makes possible, by where it sends
# somebody. A goal that sends nowhere has no button to contradict.
ALLOWED_ACTIONS: Final[dict[str, frozenset[str]]] = {
    "form": frozenset({"form"}),
    "chat": frozenset({"chat", "order"}),
    "phone": frozenset({"call", "order"}),
    "website": frozenset({"site", "order", "form"}),
    "store": frozenset({"order", "call", "site"}),
    "nothing": frozenset(ACTIONS),
}

# Where a phone number in the copy works against the goal, and where one the
# owner gave has to stay. On a form or a chat the number is a way round the
# form: the person rings, and the lead is never counted.
PHONE_UNWANTED: Final = frozenset({"form", "chat"})
PHONE_KEPT: Final = frozenset({"website", "phone", "store"})


def has_stem(text: str, stem: str) -> bool:
    """Whether a normalized text holds the stem at the start of a word."""
    return re.search(rf"(?<![a-z0-9']){re.escape(stem)}", text) is not None


def first_stem(text: str, stems: tuple[str, ...]) -> str:
    """The first of the stems the text holds, or ``""``."""
    return next((stem for stem in stems if has_stem(text, stem)), "")
