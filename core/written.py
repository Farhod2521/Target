"""Which language, and which script, a person wrote in.

The answer to "what language do I reply in" and "what language is the advert
written in" is the person's own text, not a setting: someone who writes in
Uzbek on a Russian page means Uzbek, and an owner who describes the business
in Cyrillic wants Cyrillic copy. A setting is the fallback when the text says
too little (``None``), never the other way round.

Word lists rather than a model: the answer must be the same every time and
cost nothing. Every word is compared in one spelling - lowered, Cyrillic
transliterated, one apostrophe - so an Uzbek word typed on a Russian keyboard
("кандай", "булади") is caught by the same entry as its Latin spelling.
"""

import re
from dataclasses import dataclass
from typing import Final

from core.agent.copy_words import normalize

UZBEK: Final = "uz"
RUSSIAN: Final = "ru"
ENGLISH: Final = "en"

# The four letters only Uzbek Cyrillic has (ў қ ғ ҳ), by code point.
_UZBEK_CYRILLIC: Final = frozenset(map(chr, (0x045E, 0x049B, 0x0493, 0x04B3)))
# Letters only Russian uses outside loanwords (ы щ).
_RUSSIAN_ONLY: Final = frozenset(map(chr, (0x044B, 0x0449)))

_APOSTROPHES: Final = re.compile(
    "[" + "".join(map(chr, (0x02BB, 0x02BC, 0x2018, 0x2019, 0x60, 0xB4))) + "]"
)
_NOISE: Final = re.compile(r"https?://\S+|www\.\S+|\S+@\S+|[@#]\w+", re.UNICODE)
_WORD: Final = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)*", re.UNICODE)

# In the transliterated spelling, so both scripts and keyboard habits match.
_UZBEK_WORDS: Final = frozenset(
    [
        "va",
        "uchun",
        "bilan",
        "bu",
        "kerak",
        "bor",
        "emas",
        "men",
        "siz",
        "nima",
        "nimaga",
        "nega",
        "qanday",
        "kanday",
        "qancha",
        "kancha",
        "ham",
        "lekin",
        "agar",
        "yaxshi",
        "rahmat",
        "raxmat",
        "salom",
        "assalomu",
        "assalom",
        "alaykum",
        "aleykum",
        "menga",
        "sizga",
        "bizga",
        "biz",
        "ular",
        "shu",
        "mumkin",
        "edi",
        "ekan",
        "qilish",
        "kilish",
        "qilsam",
        "kilsam",
        "qilaman",
        "qiling",
        "kiling",
        "narx",
        "narxi",
        "narxlari",
        "yo'q",
        "yuq",
        "yoq",
        "xop",
        "ha",
        "bo'ladi",
        "buladi",
        "boladi",
        "bo'lsa",
        "bulsa",
        "bolsa",
        "qanaqa",
        "kanaka",
        "bormi",
        "kerakmi",
        "endi",
        "hozir",
        "xozir",
        "qayerda",
        "kayerda",
        "qachon",
        "kachon",
        "sotamiz",
        "sotaman",
        "bizning",
        "mening",
        "sizning",
        "bilmayman",
        "esdan",
        "chiqardim",
        "chikardim",
        "unutdim",
        "ishlamayapti",
        "yordam",
        "iltimos",
        "nimadir",
        "kim",
        "qaysi",
        "kaysi",
        "ko'p",
        "kup",
        "kop",
        "chegirma",
        "bepul",
        "yetkazib",
        "mijoz",
        "mijozlar",
        "xizmat",
        "xizmati",
        "xizmatlar",
        "sifatli",
        "arzon",
        "tez",
        "manzil",
        "telefon",
        "raqam",
        "rakam",
        "qiladi",
        "kiladi",
        "beradi",
        "oling",
        "sotib",
        "olish",
        "bering",
        "kerakli",
        "zo'r",
        "mahsulot",
        "tovar",
        "do'kon",
        "dukon",
        "dokon",
        "kurs",
        "kurslar",
        "o'qish",
        "ukish",
    ]
)
_RUSSIAN_WORDS: Final = frozenset(
    [
        "i",
        "v",
        "ne",
        "na",
        "ya",
        "chto",
        "kak",
        "eto",
        "s",
        "po",
        "dlya",
        "mi",
        "vi",
        "mne",
        "menya",
        "est",
        "net",
        "a",
        "no",
        "ili",
        "mojno",
        "nujno",
        "xochu",
        "zdravstvuyte",
        "privet",
        "spasibo",
        "pochemu",
        "gde",
        "kogda",
        "skolko",
        "nash",
        "nashi",
        "moy",
        "moya",
        "ot",
        "do",
        "za",
        "iz",
        "k",
        "tak",
        "vse",
        "vsyo",
        "uje",
        "eshyo",
        "eshe",
        "tolko",
        "ochen",
        "zabil",
        "kakoy",
        "kakaya",
        "kakie",
        "vas",
        "nas",
        "nam",
        "vam",
        "etot",
        "eta",
        "eti",
        "tam",
        "zdes",
        "kto",
        "chem",
        "esli",
        "chtobi",
        "budet",
        "mojet",
        "prodaem",
        "prodayom",
        "pojaluysta",
        "seychas",
        "sdelat",
        "dostavka",
        "skidka",
        "besplatno",
        "kachestvo",
        "nedorogo",
        "zvonite",
        "pishite",
    ]
)
# Russian typed in Latin letters: only words no Uzbek or English text has.
_RUSSIAN_LATIN: Final = frozenset(
    [
        "kak",
        "chto",
        "eto",
        "privet",
        "spasibo",
        "pochemu",
        "mozhno",
        "mojno",
        "nuzhno",
        "nujno",
        "khochu",
        "hochu",
        "xochu",
        "zdravstvuyte",
        "skolko",
        "kogda",
        "gde",
        "zabyl",
        "zabil",
        "mne",
        "menya",
        "ochen",
        "tolko",
        "pozhaluysta",
        "pojaluysta",
        "seychas",
        "sdelat",
    ]
)
_ENGLISH_WORDS: Final = frozenset(
    [
        "the",
        "and",
        "is",
        "are",
        "was",
        "how",
        "what",
        "my",
        "you",
        "your",
        "i",
        "to",
        "for",
        "can",
        "do",
        "does",
        "please",
        "password",
        "forgot",
        "hello",
        "hi",
        "why",
        "where",
        "when",
        "it",
        "this",
        "that",
        "with",
        "of",
        "in",
        "on",
        "an",
        "me",
        "want",
        "need",
        "help",
        "not",
        "have",
        "has",
        "we",
        "our",
        "will",
        "would",
        "should",
        "could",
        "get",
        "buy",
        "order",
        "price",
        "free",
        "delivery",
        "best",
        "quality",
        "call",
        "now",
        "from",
        "about",
        "just",
    ]
)
# Endings Uzbek words take and Russian or English ones do not.
_UZBEK_ENDINGS: Final = (
    "lar",
    "larni",
    "larga",
    "ning",
    "dagi",
    "imiz",
    "ingiz",
    "yapti",
    "yapman",
    "moqchi",
    "sizmi",
    "dimi",
    "ganman",
)


@dataclass(frozen=True, slots=True)
class Written:
    """A language, and for Uzbek the script it is written in."""

    code: str
    cyrillic: bool = False

    @property
    def key(self) -> str:
        """``uz``, ``uz-cyrl``, ``ru`` or ``en``: what a table of fixed
        words is looked up by."""
        return "uz-cyrl" if self.code == UZBEK and self.cyrillic else self.code

    @property
    def name(self) -> str:
        """The language as a model is told it: a name, never a code."""
        if self.code == UZBEK:
            script = "Cyrillic" if self.cyrillic else "Latin"
            return f"Uzbek, in the {script} script"
        return {RUSSIAN: "Russian", ENGLISH: "English"}.get(
            self.code, "Uzbek, in the Latin script"
        )


UZBEK_LATIN: Final = Written(UZBEK)


def written_in(*texts: str) -> Written | None:
    """The language the texts are written in, or None when they say too little.

    Too little is a greeting of one word, a number, a link: the caller then
    falls back on the page's or the account's language.
    """
    raw = _APOSTROPHES.sub("'", " ".join(text for text in texts if text).lower())
    words = _WORD.findall(_NOISE.sub(" ", raw))
    cyrillic = [word for word in words if _is_cyrillic(word)]
    latin = [word for word in words if not _is_cyrillic(word)]
    cyrillic_letters = sum(map(len, cyrillic))
    latin_letters = sum(map(len, latin))
    if cyrillic_letters + latin_letters < 3:
        return None
    if cyrillic_letters > latin_letters:
        return _cyrillic(cyrillic)
    return _latin(latin)


def written_or(fallback: str, *texts: str) -> Written:
    """The language of the texts, else the given language code in its usual
    script (Uzbek in Latin letters)."""
    found = written_in(*texts)
    if found is not None:
        return found
    code = (fallback or "").split("-")[0].lower()
    return Written(code) if code in (UZBEK, RUSSIAN, ENGLISH) else UZBEK_LATIN


def reply_language(
    question: str, earlier: tuple[str, ...] = (), *fallbacks: str
) -> Written:
    """The language to answer a question in: the question's own, else the
    person's last few messages', else the first fallback code given (the
    page's language, then the account's), else Uzbek in Latin letters."""
    found = written_in(question) or written_in(*earlier[-3:])
    if found is not None:
        return found
    return written_or(next((code for code in fallbacks if code), ""))


# Uzbek Latin to Cyrillic, longest spelling first. For the product's own
# fixed words (a place's name, a status line) shown to someone who writes in
# Cyrillic; never for the owner's or a model's text.
_TO_CYRILLIC: Final = (
    ("o'", "ў"),
    ("g'", "ғ"),
    ("sh", "ш"),
    ("ch", "ч"),
    ("yo", "ё"),
    ("yu", "ю"),
    ("ya", "я"),
    ("ye", "е"),
    ("a", "а"),
    ("b", "б"),
    ("d", "д"),
    ("e", "е"),
    ("f", "ф"),
    ("g", "г"),
    ("h", "ҳ"),
    ("i", "и"),
    ("j", "ж"),
    ("k", "к"),
    ("l", "л"),
    ("m", "м"),
    ("n", "н"),
    ("o", "о"),
    ("p", "п"),
    ("q", "қ"),
    ("r", "р"),
    ("s", "с"),
    ("t", "т"),
    ("u", "у"),
    ("v", "в"),
    ("x", "х"),
    ("y", "й"),
    ("z", "з"),
    ("c", "к"),
    ("w", "в"),
    ("'", "ъ"),
)
# Names that stay as they are written, in any script.
_KEPT: Final = frozenset(
    {"telegram", "meta", "facebook", "instagram", "google", "ads", "manager", "ai"}
)


def to_cyrillic(text: str) -> str:
    """Uzbek in Latin letters, written in Cyrillic. Upper-case words (CRM)
    and the brand names in ``_KEPT`` are left alone."""
    unified = _APOSTROPHES.sub("'", text)
    return re.sub(r"[A-Za-z']+", _word_to_cyrillic, unified)


def _word_to_cyrillic(match: re.Match[str]) -> str:
    word = match.group(0)
    if word.strip("'").lower() in _KEPT or (len(word) > 1 and word.isupper()):
        return word
    head, mark, tail = word.partition("'")
    if mark and head.lower() in _KEPT:
        # Telegram'da: the name stays, its ending is Uzbek.
        return f"{head}'{_letters_to_cyrillic(tail)}"
    return _letters_to_cyrillic(word)


def _letters_to_cyrillic(word: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(word):
        for latin, cyrillic in _TO_CYRILLIC:
            piece = word[index : index + len(latin)]
            if piece.lower() != latin:
                continue
            letter = "э" if latin == "e" and index == 0 else cyrillic
            out.append(letter.upper() if piece[:1].isupper() else letter)
            index += len(latin)
            break
        else:
            out.append(word[index])
            index += 1
    return "".join(out)


def _is_cyrillic(word: str) -> bool:
    return any(0x0400 <= ord(char) <= 0x04FF for char in word)


def _uzbek_score(spelled: list[str]) -> int:
    return sum(
        2
        if word in _UZBEK_WORDS
        else int(len(word) >= 5 and word.endswith(_UZBEK_ENDINGS))
        for word in spelled
    )


def _cyrillic(words: list[str]) -> Written | None:
    joined = "".join(words)
    spelled = [normalize(word) for word in words]
    uzbek = 3 * sum(char in _UZBEK_CYRILLIC for char in joined) + _uzbek_score(spelled)
    russian = 2 * sum(word in _RUSSIAN_WORDS for word in spelled) + sum(
        char in _RUSSIAN_ONLY for char in joined
    )
    if uzbek > russian:
        return Written(UZBEK, cyrillic=True)
    if russian > uzbek or len(joined) >= 20:
        return Written(RUSSIAN)
    return None


def _latin(words: list[str]) -> Written | None:
    spelled = [normalize(word) for word in words]
    uzbek = _uzbek_score(spelled) + sum(
        2
        if "'" in word and word[0] not in "'" and ("o'" in word or "g'" in word)
        else int("q" in word and "qu" not in word)
        for word in spelled
    )
    russian = 2 * sum(word in _RUSSIAN_LATIN for word in spelled)
    english = 2 * sum(word in _ENGLISH_WORDS for word in spelled)
    best = max(uzbek, russian, english)
    if best == 0:
        return UZBEK_LATIN if len(words) >= 2 else None
    if uzbek == best:
        return UZBEK_LATIN
    return Written(ENGLISH) if english > russian else Written(RUSSIAN)


__all__ = [
    "ENGLISH",
    "RUSSIAN",
    "UZBEK",
    "UZBEK_LATIN",
    "Written",
    "reply_language",
    "to_cyrillic",
    "written_in",
    "written_or",
]
