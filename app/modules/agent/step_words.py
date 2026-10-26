"""What each step of the diagnosis is called, for the two readers of it.

The agent's review reads the figures in Uzbek, beside the Uzbek cause
sentence it checks them against. The chat and the reports read them in
English, the language their prompts are written in. One table per reader
and one formatter between them - see :mod:`apps.agent.steps` - so a rate
is the same string wherever a model sees it, and only the words around it
differ.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StepWords:
    """The labels and joining words of one reader's language."""

    cpm: str
    ctr: str
    arrival: str
    click_to_lead: str
    hook: str
    hold: str
    spend_share: str
    junk: str
    learning: str
    trend: str
    trend_none: str
    trend_usual: str
    trend_share: str
    warn: str
    act: str
    enough: str
    enough_yes: str
    enough_no: str
    enough_shown_yes: str
    enough_shown_no: str
    launch: str
    launch_new: str
    launch_now: str
    frequency: str
    frequency_now: str
    frequency_before: str
    halves: str
    halves_early: str
    halves_late: str
    slice: str
    slice_share: str
    slice_cpm: str
    usual: str


UZ = StepWords(
    cpm="1000 ko'rsatish narxi",
    ctr="1000 ko'rsatishdan havolaga bosish",
    arrival="Bosganlardan saytga yetib kelgan",
    click_to_lead="100 bosishdan murojaat",
    hook="Videoni 3 soniyadan ko'p ko'rgan",
    hold="3 soniyadan o'tganlardan oxirigacha ko'rgan",
    spend_share="Kunlik byudjetdan sarflangani",
    junk="Noto'g'ri yoki takror raqamli murojaat",
    learning="Haftalik natija: {results} (Meta o'rganishi uchun taxminan 50 kerak)",
    trend="Oxirgi 3 kunda natija narxi",
    trend_none="natija yo'q",
    trend_usual="14 kunlik odatiy",
    trend_share="odatdagining {pct}%",
    warn="ogohlantirish: 1,5 baravardan qimmat",
    act="chora kerak: 2 baravardan qimmat",
    enough="Xulosa uchun sarf",
    enough_yes="yetarli ({spent}, odatdagi 3 ta natija narxi {needed})",
    enough_no="yetarli emas ({spent}, kerak {needed} - odatdagi 3 ta natija narxi)",
    enough_shown_yes="yetarli ({shown} ko'rsatish, {clicks} bosish; odatdagi narx hali yo'q - kerak {min_shown} va {min_clicks})",
    enough_shown_no="yetarli emas ({shown} ko'rsatish, {clicks} bosish; odatdagi narx hali yo'q - kerak {min_shown} va {min_clicks})",
    launch="Havolaga bosish ulushi",
    launch_new="yangi paytida",
    launch_now="oxirgi 3 kunda",
    frequency="Bir odam necha marta ko'rdi",
    frequency_now="oxirgi 7 kunda",
    frequency_before="undan oldingi 7 kunda",
    halves="Havolaga bosish ulushi",
    halves_early="haftaning boshida",
    halves_late="oxirida",
    slice="Qimmat qism",
    slice_share="pulning {share}% shunga ketdi",
    slice_cpm="1000 ko'rsatish",
    usual="hisobda odatda",
)
EN = StepWords(
    cpm="cost per 1000 shown",
    ctr="link clicks per 1000 shown",
    arrival="clicks that reached the site",
    click_to_lead="leads per 100 clicks",
    hook="video watched past 3 seconds",
    hold="of those, watched to the end",
    spend_share="share of the day's budget spent",
    junk="leads with a wrong or repeated number",
    learning="results this week: {results} (Meta learns on about 50)",
    trend="cost per result, last 3 days",
    trend_none="no result",
    trend_usual="usual",
    trend_share="{pct}% of usual",
    warn="a warning: past 1.5 times the usual",
    act="a reason to act: past twice the usual",
    enough="spent enough to judge",
    enough_yes="yes ({spent}; three usual results cost {needed})",
    enough_no="no ({spent} of the {needed} three usual results cost)",
    enough_shown_yes="yes ({shown} shown, {clicks} clicks; no usual price yet, so {min_shown} and {min_clicks} are the bar)",
    enough_shown_no="no ({shown} shown, {clicks} clicks; no usual price yet, so {min_shown} and {min_clicks} are the bar)",
    launch="link click rate",
    launch_new="while new",
    launch_now="last 3 days",
    frequency="times one person saw it",
    frequency_now="last 7 days",
    frequency_before="the 7 before",
    halves="link click rate",
    halves_early="first half of the week",
    halves_late="second half",
    slice="dear slice",
    slice_share="{share}% of the money",
    slice_cpm="per 1000 shown",
    usual="usual",
)
__all__ = ["EN", "UZ", "StepWords"]
