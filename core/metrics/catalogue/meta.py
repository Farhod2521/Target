"""The metrics only Meta measures.

People counts, video attention and the three rankings. Google has none of
them in this form, so they are kept here and are nothing to the other
networks.
"""

from typing import Final

from core.metrics.arithmetic import percent, ratio
from core.metrics.catalogue.spec import (
    AD_ONLY,
    META_ONLY,
    Answer,
    Figures,
    Formula,
    Metric,
    Setting,
    known,
    missing,
)

# Meta ranks an advert only after this many impressions; below it the
# answer is ``UNKNOWN`` and means nothing about the advert.
RANKED_FROM: Final = 500
UNRANKED: Final = "unknown"


def _reach(figures: Figures, setting: Setting) -> Answer:
    if figures.reach is None:
        return missing("not_asked")
    return Answer(value=figures.reach)


def _frequency(figures: Figures, setting: Setting) -> Answer:
    if figures.reach is None:
        return missing("not_asked")
    return known(ratio(part=figures.impressions, whole=figures.reach))


def _unique_link_clicks(figures: Figures, setting: Setting) -> Answer:
    if setting.outcome == "chat":
        return missing("no_link")
    if figures.unique_link_clicks is None:
        return missing("not_asked")
    return Answer(value=figures.unique_link_clicks)


def _is_video(figures: Figures) -> bool:
    return figures.video_plays > 0 or figures.video_views_3s > 0


def _hook_rate(figures: Figures, setting: Setting) -> Answer:
    if not _is_video(figures):
        return missing("not_video")
    return known(percent(part=figures.video_views_3s, whole=figures.impressions))


def _hold_rate(figures: Figures, setting: Setting) -> Answer:
    if not _is_video(figures):
        return missing("not_video")
    return known(percent(part=figures.video_thruplays, whole=figures.video_views_3s))


def _ranking(name: str) -> Formula:
    def formula(figures: Figures, setting: Setting) -> Answer:
        value = str(getattr(figures, name))
        if not value:
            return missing("not_read")
        if value == UNRANKED or figures.impressions < RANKED_FROM:
            return missing("few_impressions")
        return Answer(value=value)

    return formula


META: Final[tuple[Metric, ...]] = (
    Metric(
        key="reach",
        label="Qamrov",
        hint="Reklamani ko'rgan odamlar soni. Davr uchun Meta'dan alohida o'qiladi.",
        group="delivery",
        unit="count",
        formula=_reach,
        networks=META_ONLY,
    ),
    Metric(
        key="frequency",
        label="Chastota",
        hint="Bir odam reklamani o'rtacha necha marta ko'rdi: Ko'rsatildi ÷ Qamrov.",
        group="delivery",
        unit="ratio",
        formula=_frequency,
        networks=META_ONLY,
        lower_is_better=True,
    ),
    Metric(
        key="hook_rate",
        label="Hook rate",
        hint="3 soniya ko'rganlar ÷ Ko'rsatildi × 100%. Videoning boshi qanchalik ushlaydi.",
        group="video",
        unit="percent",
        formula=_hook_rate,
        levels=AD_ONLY,
        networks=META_ONLY,
        norm="25–30% va undan yuqori. 20% dan past bo'lsa, videoning boshi zaif.",
    ),
    Metric(
        key="hold_rate",
        label="Hold rate",
        hint="ThruPlay ÷ 3 soniya ko'rganlar × 100%. Videoning o'rtasi qanchalik ushlaydi.",
        group="video",
        unit="percent",
        formula=_hold_rate,
        levels=AD_ONLY,
        networks=META_ONLY,
        norm="15–20% va undan yuqori. 10% dan past bo'lsa, videoning o'rtasi zaif.",
    ),
    Metric(
        key="unique_link_clicks",
        label="Noyob kliklar",
        hint="Havolani bosgan odamlar soni. Davr uchun Meta'dan alohida o'qiladi.",
        group="engagement",
        unit="count",
        formula=_unique_link_clicks,
        networks=META_ONLY,
    ),
    Metric(
        key="quality_ranking",
        label="Sifat",
        hint="Kreativ sifati boshqa reklamalarga nisbatan. Past bo'lsa, kreativni almashtirish kerak.",
        group="quality",
        unit="ranking",
        formula=_ranking("quality_ranking"),
        levels=AD_ONLY,
        networks=META_ONLY,
    ),
    Metric(
        key="engagement_rate_ranking",
        label="Faollik",
        hint="Odamlar reklamaga qanchalik qiziqdi. Past bo'lsa, hook va matnni kuchaytirish kerak.",
        group="quality",
        unit="ranking",
        formula=_ranking("engagement_rate_ranking"),
        levels=AD_ONLY,
        networks=META_ONLY,
    ),
    Metric(
        key="conversion_rate_ranking",
        label="Konversiya",
        hint="Bosganlar qanchalik ariza qoldirdi. Past bo'lsa, forma, sayt yoki taklifni tekshirish kerak.",
        group="quality",
        unit="ranking",
        formula=_ranking("conversion_rate_ranking"),
        levels=AD_ONLY,
        networks=META_ONLY,
    ),
)

__all__ = ["META", "RANKED_FROM"]
