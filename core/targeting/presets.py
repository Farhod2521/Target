"""The preset catalogue: YAML in, ``Preset`` out.

Named ``presets`` and not ``catalog``, because ``catalog/`` next door is a
directory of YAML files. Two importable names differing only by extension
resolve correctly and read wrongly.

A preset is data. Adding a business category is a YAML file, never an
``if category == ...`` - the moment that branch is written, the catalogue
has stopped being the thing that decides.
"""

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

# Where the YAML ships. A path, not configuration: these files are part of
# the package the way a translation catalogue is part of an app.
CATALOG_DIR = Path(__file__).parent / "catalog"


@dataclass(frozen=True, slots=True)
class Preset:
    """One category plus one goal, and everything that follows from it.

    The provider vocabulary starts here. Everything above this line speaks
    about businesses and goals; everything from here down is what gets sent.
    """

    provider: str
    category: str
    goal: str
    label: str
    version: str
    objective: str
    optimization_goal: str
    billing_event: str
    # Where the tap lands, in the domain's own words. **Not**
    # ``destination_type`` below - see :mod:`core.targeting.destinations`
    # for why one cannot be read off the other.
    sends_to: AdDestination
    # The button, in Meta's vocabulary. On the preset rather than decided
    # where the creative is assembled, because it is the same kind of thing
    # as ``optimization_goal``: a provider word that follows from the goal,
    # and the catalogue is where those live. The alternative is a branch on
    # the goal's name in the one module allowed to be provider-shaped,
    # which is rule 7 dying quietly.
    call_to_action: str
    destination_type: str
    targeting: Mapping[str, Any]
    # Fills a question nobody answered. Bare names, no prefix - see render.
    defaults: Mapping[str, Any]
    # What the ad set optimises towards when the event happens somewhere
    # else. Present only on goals that measure a sale on the advertiser's
    # own site, and empty on every goal the provider can measure itself.
    promoted_object: Mapping[str, Any] = field(default_factory=dict)
    # How the conversation opens, on the goals that open one. Both empty
    # everywhere else, and the loader refuses either one on a goal that
    # sends nobody to a chat - a greeting written for an ad that cannot
    # show it reads as a promise the catalogue is keeping.
    #
    # The first is a **suggestion**: it carries a ``{business.name}`` hole
    # and fills the box the owner then edits. The second is never shown to
    # anybody here - it is what the customer's own message box opens
    # pre-typed with, and it follows from the goal rather than from the
    # business. See :mod:`core.targeting.chat`.
    welcome_message: str = ""
    autofill_message: str = ""
    # Questions the customer taps under the greeting - offered to the owner
    # only when they ask for questions, and never sent unless they keep them.
    chat_questions: tuple[str, ...] = ()
    # Whether the wizard may still offer this goal, as opposed to whether
    # it can still be built.
    #
    # The two are different questions. ``store_visits`` is off the first
    # screen because its destination is not deliverable, which is a fact
    # about this repository; a goal can also be withdrawn because the
    # product decided against it - two awareness goals side by side ask a
    # business owner to tell "Tanilish" from "Ko'proq ko'rilsin" - and this
    # key is how that is said.
    #
    # Deleting the preset is not that way. A launch answered months ago
    # names its goal by key and the builder still has to find it, so the
    # entry stays and stops being offered. See
    # :func:`shared.presets.offered_goals`.
    offered: bool = True

    @property
    def is_deliverable(self) -> bool:
        """Whether the launch sequence can actually build this goal today.

        Five shapes are implemented: a form on the ad, a link to the
        advertiser's own site, a conversation the provider hosts, a number
        the tap dials, and no button at all. The sixth is designed and not
        built, and the sequence would attach a lead form to it anyway - so
        somebody choosing it was sold an outcome and handed a different
        one, with delivery bought against an event the ad could not
        produce.

        Read off ``sends_to`` rather than off ``destination_type``, and the
        difference is not cosmetic. Meta's field is objective-dependent - a
        traffic ad set that goes to a website sends **no** destination_type
        at all - so reading it would call the goal undeliverable for a
        reason that has nothing to do with whether it can be built.

        The catalogue keeps the unbuilt presets. They are the design work
        for the flows that come next, and deleting them to hide them would
        mean writing them again.
        """
        return is_deliverable(self.sends_to)

    @property
    def needs_lead_form(self) -> bool:
        """Whether the sequence has to create a form and hang it on the ad.

        The one step that cannot be undone - Meta refuses a DELETE on a
        lead form - so a goal that does not need one must not make one.
        """
        return needs_lead_form(self.sends_to)

    @property
    def needs_link(self) -> bool:
        """Whether the ad has to carry the advertiser's own address.

        Every creative Meta accepts carries a link. On five of the six
        destinations it is a formality nobody follows; on this one it is
        what is being bought.
        """
        return needs_link(self.sends_to)

    @property
    def needs_phone(self) -> bool:
        """Whether the ad has to carry a number the tap dials.

        Read off ``sends_to`` like every other shape question, and worth
        saying why it is not read off ``call_to_action``: a preset naming
        ``CALL_NOW`` is naming a *button label*, and Meta will happily put
        that label on a button that opens a web page. What decides is where
        the tap lands, which is this field and only this field.
        """
        return needs_phone(self.sends_to)

    @property
    def shows_a_button(self) -> bool:
        """Whether the creative gets a call-to-action at all.

        False for the one goal that sends nobody anywhere. The preset still
        names a provider word for it - ``NO_BUTTON`` - because that is what
        gets sent, and this is the domain's own way of asking the same
        question without reading Meta's vocabulary back.
        """
        return shows_a_button(self.sends_to)

    @property
    def opens_chat(self) -> bool:
        """Whether tapping this ad opens a conversation rather than a page.

        What decides the button. A chat ad's call to action carries the
        provider's own destination instead of a link, and getting it wrong
        does not produce a broken ad - it produces a working website ad
        sold to somebody who was promised a conversation.
        """
        return opens_chat(self.sends_to)

    @property
    def opens_profile(self) -> bool:
        """Whether tapping this ad opens the business's Instagram profile.

        What the first step reads to show the connected account instead of
        an address field, and what the launch reads to demand one.
        """
        return opens_profile(self.sends_to)

    @property
    def needs_conversion_source(self) -> bool:
        """Whether this goal cannot be created without a pixel or its like.

        Read off the preset rather than off a list of optimisation goals
        kept somewhere else: the YAML is what decides, and a second list
        would be a second place to forget.
        """
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
    # What the interest screen opens with when Claude is unreachable, the
    # key is missing, or the answer came back empty. The list the owner sees
    # is never allowed to be empty, and hoping for an API is not a guarantee.
    interest_seeds: tuple[Interest, ...]
    # Behaviours and life events for this category, from the file and from
    # nowhere else.
    #
    # **Never proposed by a model, and that is the point of them being
    # here.** An interest is searched for, so a name a model invented either
    # matches something or is dropped with a reason. These two classes are
    # *closed lists* the platform publishes, so an invented name matches
    # nothing at all - and a model asked for one would produce plausible
    # English that silently resolves to an empty audience.
    #
    # Empty for most categories, and that is not an omission either. A
    # restaurant has no life event; a wedding hall, a removals firm and a
    # mortgage broker are almost entirely one, which is the whole reason
    # this field exists.
    trait_seeds: tuple[Interest, ...] = ()


class PresetCatalog:
    """Every preset on disk, indexed by the three things that select one.

    Loading parses a dozen files, so callers hold onto an instance rather
    than building one per request. This class has no clock, no cache and no
    opinion about how long that instance lives.
    """

    def __init__(
        self,
        *,
        categories: Sequence[Category],
        presets: Sequence[Preset],
    ) -> None:
        # Indexed by provider rather than filtered by it. Every lookup below
        # is then a dict access, which is both faster and the only shape
        # that keeps rule 7 honest: there is no name to compare against.
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
        # Imported inside the method rather than at the top of the file.
        # The reader builds the two dataclasses declared above, so a
        # module-level import would be a cycle - and the alternative,
        # a third module holding nothing but those two dataclasses, would
        # split one idea across three files to avoid this one line.
        from core.targeting.loader import read_directory

        categories, presets = read_directory(path)
        return cls(categories=categories, presets=presets)

    def find(self, *, provider: str, category: str, goal: str) -> Preset:
        """The one preset for this combination.

        A dict lookup rather than a search: comparing provider names in
        domain code is the abstraction dying, one branch at a time.
        """
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
        """The behaviours and life events this category may target.

        Empty for most categories and for every unknown one, and the two
        mean the same thing here: nothing to offer. A restaurant has no life
        event worth targeting; a wedding hall is almost entirely one.
        """
        return self._traits.get((provider, category), ())
