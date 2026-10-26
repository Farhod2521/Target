"""Which part of an advert the provider refused it over.

A refusal is fixed in one place, and the place decides the fix: new words
for words, another picture for a picture, a working page for a page. Words
written for a refusal that was about the picture fix nothing and cost the
owner a review cycle - so the fix is chosen from this, never assumed.

Read from the provider's own policy names and sentences, which arrive in
the ad account's language - English or Russian here - so each part is
listed in both. Rules rather than a model: the answer decides what gets
proposed, and a table of words can be read by somebody who doubts it.

**What cannot be fixed by changing the advert is told apart.** A product the
policy restricts, or an account under restriction, is not answered by new
words or a new picture, and proposing either would be a button that changes
the advert and leaves it refused.
"""

from typing import Final, Literal

RefusalCause = Literal["words", "picture", "site", "offer", "account", "unknown"]

# In the order they are tried. What the advert cannot fix comes first: a
# restricted product refused "for its image" is still a restricted product.
_TERMS: Final[tuple[tuple[RefusalCause, tuple[str, ...]], ...]] = (
    (
        "account",
        (
            "circumventing",
            "account integrity",
            "unauthorized",
            "authenticity",
            "restricted account",
            "обход",
            "аккаунт",
            "подлинност",
        ),
    ),
    (
        "offer",
        (
            "prohibited",
            "unacceptable business",
            "tobacco",
            "weapon",
            "drug",
            "alcohol",
            "gambling",
            "dating",
            "cryptocurrenc",
            "adult products",
            "special ad categor",
            "social issues",
            "political",
            "запрещ",
            "недопустим",
            "табак",
            "оруж",
            "алкогол",
            "азартн",
            "криптовалют",
            "особые категории",
            "политическ",
        ),
    ),
    (
        "site",
        (
            "landing page",
            "destination",
            "website",
            "целевая страница",
            "целевой страниц",
            "сайт",
        ),
    ),
    (
        "picture",
        (
            "image",
            "video",
            "visual",
            "photo",
            "before-and-after",
            "before and after",
            "изображен",
            "видео",
            "фото",
            "картинк",
        ),
    ),
    (
        "words",
        (
            "personal attribute",
            "personal health",
            "misleading",
            "false claim",
            "grammar",
            "profanity",
            "text",
            "wording",
            "headline",
            "language",
            "личные характеристики",
            "личное здоровье",
            "вводящ",
            "текст",
            "заголов",
            "ненормативн",
        ),
    ),
)


def refusal_cause(text: str) -> RefusalCause:
    """The part of the advert this refusal is about, or ``unknown``.

    ``text`` is the provider's policy names and sentences together, as
    ``apps.agent.selectors.ads.refusal_of`` joins them.
    """
    said = text.lower()
    if not said.strip():
        return "unknown"
    for cause, terms in _TERMS:
        if any(term in said for term in terms):
            return cause
    return "unknown"


__all__ = ["RefusalCause", "refusal_cause"]
