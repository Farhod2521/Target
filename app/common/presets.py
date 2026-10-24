from functools import lru_cache

from app.common.config import settings
from app.common.exceptions import ConfigurationError
from core.targeting import CATALOG_DIR, Category, Interest, Preset, PresetCatalog


@lru_cache(maxsize=1)
def preset_catalog() -> PresetCatalog:
    return PresetCatalog.from_directory(CATALOG_DIR)


def default_provider() -> str:
    return settings.default_ad_provider


def categories(*, provider: str = "") -> tuple[Category, ...]:
    return preset_catalog().categories(provider=provider or default_provider())


def fallback_category(*, provider: str = "") -> str:
    key = settings.fallback_category
    if key not in {c.key for c in categories(provider=provider)}:
        raise ConfigurationError(
            f"FALLBACK_CATEGORY={key!r} names no category in the catalogue"
        )
    return key


def label_for(*, category: str, provider: str = "") -> str:
    return next(
        (c.label for c in categories(provider=provider) if c.key == category),
        category,
    )


def goal_label(*, preset: Preset) -> str:
    return preset.label


def goal_labels(*, provider: str = "") -> dict[str, str]:
    chosen = provider or default_provider()
    found: dict[str, str] = {}
    for entry in categories(provider=chosen):
        for preset in goals_for(category=entry.key, provider=chosen):
            found.setdefault(preset.goal, preset.label)
    return found


def goals_for(*, category: str, provider: str = "") -> tuple[Preset, ...]:
    return preset_catalog().goals(
        provider=provider or default_provider(), category=category
    )


def offered_goals(*, category: str, provider: str = "") -> tuple[Preset, ...]:
    return tuple(
        preset
        for preset in goals_for(category=category, provider=provider)
        if preset.is_deliverable and preset.offered
    )


def seeds_for(*, category: str, provider: str = "") -> tuple[Interest, ...]:
    return preset_catalog().seeds(
        provider=provider or default_provider(), category=category
    )


def traits_for(*, category: str, provider: str = "") -> tuple[Interest, ...]:
    return preset_catalog().traits(
        provider=provider or default_provider(), category=category
    )
