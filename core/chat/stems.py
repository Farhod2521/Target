"""The stems that decide which parts of an account a question needs.

The table :func:`core.chat.route.route` reads, kept in a file of its own
because it is the part that grows: every section added to the digest adds a
dozen stems in three languages, and each stem carries the reason it is the
length it is.

**Stems rather than words, because two of the three languages inflect.**
"reklamangiz", "reklamalarim" and "reklamada" are one word with three
endings, and a whole-word match would find none of them. The stems are
short enough to survive the endings and long enough not to collide.
"""

from typing import Final, Literal

# The parts of the digest that are worth deciding about. The business and
# the window's totals are not here: together they are a hundred tokens,
# they say who is asking and what the account did, and there is no question
# about an advertising account that is better answered without them.
Section = Literal["campaigns", "adsets", "ads", "landing", "audiences", "suggestions"]

# Fixed order, because it is printed. The list of what was left out is read
# by a model, and a set that came out in a different order every time would
# make two identical questions into two different prompts.
SECTIONS: Final[tuple[Section, ...]] = (
    "campaigns",
    "adsets",
    "ads",
    "landing",
    "audiences",
    "suggestions",
)

WORDS: Final[dict[Section, frozenset[str]]] = {
    # "reklama" covers the Uzbek word and every ending on it; "kampan"
    # stops short of "kampaniyalarim" only if it were longer. "sarf" and
    # "byudjet" are here rather than under the totals because somebody
    # asking where the money went is asking which advert took it.
    #
    # So are the price words: "nega murojaat qimmatlashdi?" reads like a
    # question about the totals and is not. The totals say a lead cost
    # more; only the campaigns say which one did.
    "campaigns": frozenset(
        {
            "reklama",
            "kampan",
            "byudjet",
            "sarf",
            "xarajat",
            "qimmat",
            "arzon",
            "narx",
            "to'xta",
            "pauza",
            "faol",
            "ishlayap",
            "ishlamay",
            "реклам",
            "кампан",
            "бюджет",
            "расход",
            "дорож",
            "дешев",
            "цена",
            "стоим",
            "трат",
            "останов",
            "campaign",
            "budget",
            "spend",
            "expensive",
            "cheaper",
            "cost per",
            "advert",
            " ads",
            "paused",
        }
    ),
    # One rung below the campaigns, and the rung every fault and every
    # cause sits on.
    #
    # Three kinds of question end up here. One says "guruh" outright - the
    # word every screen prints, since "adset" is a word this product does
    # not use. One is about something being broken, and that is a group
    # question whether or not the reader knows it: a provider stops a
    # *group*, and the campaign above it goes on looking healthy. And one
    # asks why: each group line carries last night's diagnosis, so the
    # campaigns say *which* advert costs more and only the groups say what
    # is wrong with it.
    #
    # "muammo" and "xato" are the words the waiting list itself uses, so
    # somebody quoting the line they just read arrives with one of them.
    # Deliberately not "to'xta": that stem is already the campaigns' and a
    # question about something being paused is usually a question about
    # which advert is paused, not about the group's audience.
    "adsets": frozenset(
        {
            "guruh",
            "muammo",
            "nosozlik",
            "xato",
            "ogohlantirish",
            "bloklan",
            "nega",
            "sabab",
            "natija",
            "групп",
            "проблем",
            "ошибк",
            "неполадк",
            "предупрежд",
            "заблокир",
            "почему",
            "причин",
            "результат",
            "ad set",
            "adset",
            "ad group",
            "issue",
            "problem",
            "error",
            "warning",
            "blocked",
            "why",
            "reason",
            "result",
        }
    ),
    # The adverts themselves: their words, their pictures, whether anybody
    # clicks. "bosil", "bosma" and "bosyap" are the three ways an owner says
    # people do or do not click; "rasm" also opens "rasmiy", which costs one
    # section on a rare question and is cheaper than missing "rasmni
    # almashtiraymi". "ssenar" is somebody asking for a video to be planned,
    # which is planned from what their adverts already did.
    "ads": frozenset(
        {
            "matn",
            "ssenar",
            "сценар",
            "scenario",
            "script",
            "rasm",
            "video",
            "kreativ",
            "sarlavha",
            "bosil",
            "bosma",
            "bosyap",
            "bosish",
            "klik",
            "reyting",
            "текст",
            "креатив",
            "картин",
            "фото",
            "видео",
            "заголов",
            "клик",
            "рейтинг",
            "creative",
            "image",
            "picture",
            "headline",
            "click",
            " copy",
            "ranking",
        }
    ),
    # What a click lands on. " form" and " форм" carry a leading space
    # because "platform", "performance" and "информация" contain the bare
    # stem; "savol" is left out because "savolim bor" opens half of all
    # conversations.
    "landing": frozenset(
        {
            "forma",
            "sayt",
            "sahifa",
            "piksel",
            "havola",
            "to'ldir",
            " форм",
            "сайт",
            "страниц",
            "пиксел",
            "ссылк",
            "заполн",
            " form",
            "site",
            "landing",
            "pixel",
            "link",
        }
    ),
    # "auditor" rather than "auditoriya": the Russian "аудитория" inflects
    # to "аудитории" and the Uzbek takes possessives. "qamrov" is reach,
    # "manzil" a place, "yosh" an age - the three things a targeting
    # question is actually about.
    "audiences": frozenset(
        {
            "auditor",
            "qamrov",
            "target",
            "o'xshash",
            "manzil",
            "hudud",
            "yosh",
            "jins",
            "qiziqish",
            "аудитор",
            "охват",
            "таргет",
            "похож",
            "локац",
            "возраст",
            "интерес",
            "audience",
            "reach",
            "lookalike",
            "targeting",
            "interest",
            "location",
        }
    ),
    # "taklif" is the product's own word for a proposal and the one on the
    # screen; "agent" is what the reader calls the thing that makes them.
    "suggestions": frozenset(
        {
            "taklif",
            "agent",
            "tavsiya",
            "tasdiq",
            "rad et",
            "o'zgartir",
            "предлож",
            "агент",
            "совет",
            "рекоменд",
            "одобр",
            "отклон",
            "suggestion",
            "propose",
            "advice",
            "approve",
            "reject",
        }
    ),
}


__all__ = ["SECTIONS", "WORDS", "Section"]
