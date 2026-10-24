"""The preset catalogue: YAML in, ``Preset`` out."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.targeting.contracts import Interest
from core.targeting.destinations import (
    AdDestination,
    is_deliverable,
    needs_lead_form,
    needs_link,
    needs_phone,
    opens_chat,
    opens_profile,
    shows_a_button,
)
from core.targeting.exceptions import PresetNotFound

CATALOG_DIR = Path(__file__).parent / "catalog"


@dataclass(frozen=True, slots=True)
class Preset:
    """One category plus one goal, and everything that follows from it."""

    provider: str
    category: str
    goal: str
    label: str
    version: str
    objective: str
    optimization_goal: str
    billing_event: str
    sends_to: AdDestination
    call_to_action: str
    destination_type: str
    targeting: Mapping[str, Any]
    defaults: Mapping[str, Any]
    promoted_object: Mapping[str, Any] = field(default_factory=dict)
    welcome_message: str = ""
    autofill_message: str = ""
    chat_questions: tuple[str, ...] = ()
    offered: bool = True

    @property
    def is_deliverable(self) -> bool:
        """Whether the launch sequence can actually build this goal today."""
        return is_deliverable(self.sends_to)

    @property
    def needs_lead_form(self) -> bool:
        """Whether the sequence has to create a form and hang it on the ad."""
        return needs_lead_form(self.sends_to)

    @property
    def needs_link(self) -> bool:
        """Whether the ad has to carry the advertiser's own address."""
        return needs_link(self.sends_to)

    @property
    def needs_phone(self) -> bool:
        """Whether the ad has to carry a number the tap dials."""
        return needs_phone(self.sends_to)

    @property
    def shows_a_button(self) -> bool:
        """Whether the creative gets a call-to-action at all."""
        return shows_a_button(self.sends_to)

    @property
    def opens_chat(self) -> bool:
        """Whether tapping this ad opens a conversation rather than a page."""
        return opens_chat(self.sends_to)

    @property
    def opens_profile(self) -> bool:
        """Whether tapping this ad opens the business's Instagram profile."""
        return opens_profile(self.sends_to)

    @property
    def needs_conversion_source(self) -> bool:
        """Whether this goal cannot be created without a pixel or its like."""
        return bool(self.promoted_object)

    @property
    def key(self) -> str:
        """``restaurant/leads`` - what gets stored on the launch row."""
        return f"{self.category}/{self.goal}"


@dataclass(frozen=True, slots=True)
class Category:
    """A business category, as the first wizard screen shows it."""

    provider: str
    key: str
    label: str
    version: str
    interest_seeds: tuple[Interest, ...]
    trait_seeds: tuple[Interest, ...] = ()


class PresetCatalog:
    """Every preset on disk, indexed by the three things that select one."""

    def __init__(
        self,
        *,
        categories: Sequence[Category],
        presets: Sequence[Preset],
    ) -> None:
        self._by_key = {(p.provider, p.category, p.goal): p for p in presets}

        by_provider: dict[str, list[Category]] = {}
        seeds: dict[tuple[str, str], tuple[Interest, ...]] = {}
        traits: dict[tuple[str, str], tuple[Interest, ...]] = {}
        for category in categories:
            by_provider.setdefault(category.provider, []).append(category)
            seeds[(category.provider, category.key)] = category.interest_seeds
            traits[(category.provider, category.key)] = category.trait_seeds

        goals: dict[tuple[str, str], list[Preset]] = {}
        for preset in presets:
            goals.setdefault((preset.provider, preset.category), []).append(preset)

        self._categories = {key: tuple(value) for key, value in by_provider.items()}
        self._goals = {key: tuple(value) for key, value in goals.items()}
        self._seeds = seeds
        self._traits = traits

    @classmethod
    def from_directory(cls, path: Path) -> "PresetCatalog":
        """Read every ``*.yaml`` under ``path``, in filename order."""
        from core.targeting.loader import read_directory

        categories, presets = read_directory(path)
        return cls(categories=categories, presets=presets)

    def find(self, *, provider: str, category: str, goal: str) -> Preset:
        """The one preset for this combination."""
        preset = self._by_key.get((provider, category, goal))
        if preset is None:
            raise PresetNotFound(provider=provider, category=category, goal=goal)
        return preset

    def categories(self, *, provider: str) -> tuple[Category, ...]:
        """Every category this provider has presets for, in filename order."""
        return self._categories.get(provider, ())

    def goals(self, *, provider: str, category: str) -> tuple[Preset, ...]:
        """The goals offered for one category, in the order the file lists."""
        return self._goals.get((provider, category), ())

    def seeds(self, *, provider: str, category: str) -> tuple[Interest, ...]:
        """The starting interest list. Empty only if the category is unknown."""
        return self._seeds.get((provider, category), ())

    def traits(self, *, provider: str, category: str) -> tuple[Interest, ...]:
        """The behaviours and life events this category may target."""
        return self._traits.get((provider, category), ())
