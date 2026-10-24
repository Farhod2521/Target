"""What can go wrong between an answer and a targeting spec.

Two audiences here, and the split is the point. ``CatalogError`` and
``UnfilledTemplate`` report a mistake in the YAML: nobody outside this
repository can provoke them and the fix is a commit. The rest report a
situation the advertiser created and can correct on the screen they are
looking at.

None of them carries a sentence. Each carries the numbers a sentence would
need, because the wording belongs to the Django layer, in the reader's
language - an exception message written in Uzbek here is one that cannot
be translated and cannot be logged.
"""


class TargetingError(Exception):
    """Base for everything this package raises."""


class CatalogError(TargetingError):
    """The preset catalogue is malformed. A deployment bug, not a user one."""

    def __init__(self, message: str, *, source: str = "") -> None:
        super().__init__(f"{source}: {message}" if source else message)
        self.source = source


class PresetNotFound(TargetingError):
    """No preset covers this category and goal.

    Reachable from a real screen: a business whose category was set before
    a goal existed, or a catalogue entry removed while a draft was open.
    """

    def __init__(self, *, provider: str, category: str, goal: str) -> None:
        super().__init__(f"no preset for {provider} {category}/{goal}")
        self.provider = provider
        self.category = category
        self.goal = goal


class UnfilledTemplate(TargetingError):
    """A ``{...}`` survived rendering.

    Never sent onward. A spec with a literal ``{business.lat}`` in it is
    accepted by nobody, and the failure would surface as an opaque provider
    error hours later instead of here.
    """

    def __init__(self, *, path: str, placeholder: str) -> None:
        super().__init__(f"{path}: {placeholder} has no value and no default")
        self.path = path
        self.placeholder = placeholder


class InvalidTargeting(TargetingError):
    """The spec contradicts itself - a minimum above its maximum, say."""

    def __init__(self, message: str, *, field: str = "") -> None:
        super().__init__(message)
        self.field = field


class BudgetTooLow(TargetingError):
    """Below what the provider will accept for this account.

    Carries all three numbers: a message reading "kamida 30 000" is only
    useful next to what was typed and in which currency.
    """

    def __init__(self, *, given_minor: int, minimum_minor: int, currency: str) -> None:
        super().__init__(f"{given_minor} < {minimum_minor} {currency}")
        self.given_minor = given_minor
        self.minimum_minor = minimum_minor
        self.currency = currency


class ConversionSourceMissing(TargetingError):
    """The goal optimises for a sale on the advertiser's own site, and
    nothing is reporting those sales.

    Raised at launch time rather than at build time, like the interest rule
    beside it: the whole wizard works before any provider is connected, and
    an owner should be able to see and edit their proposal before being
    told what still has to be plugged in.

    Not a warning. The provider refuses to create an ad set optimising for
    an event it has no source for, so letting this through only moves the
    refusal to a place where the message is Meta's rather than ours.
    """


class DestinationLinkMissing(TargetingError):
    """The ad sends people to a website and nobody said which one.

    Raised at launch time rather than at build time, for the reason every
    gate in this module is: the proposal has to be viewable and editable
    before it is launchable.

    **Refused rather than filled in**, and that is the whole of why this
    exists. Every creative Meta accepts carries a link, so there has always
    been a fallback for the goals where nobody follows it - a lead ad's
    link is a formality. Reusing that fallback here would point an
    advertiser's paid traffic at somebody else's front page, spend their
    budget doing it, and look like a working campaign from every screen.

    Whether the link is one Meta will accept - it refuses a creative whose
    link stays inside Meta - is not asked here. That is the provider's
    rule, and this package does not know which hosts are theirs.
    """


class PhoneNumberMissing(TargetingError):
    """The ad is a button that dials, and no number was given.

    The third gate of its kind and the one with the shortest fuse. Meta
    takes the number inside the button, in the very key an ordinary ad
    carries a link in - so a call ad built without one is not refused
    anywhere. It becomes a *website* ad wearing a "Call now" button, it
    delivers, and every screen afterwards reports clicks for it.

    Raised at launch time rather than at build time, like every other rule
    in this file: the proposal has to be viewable and editable before it
    is launchable.

    Whether the number is one the customer's country can dial is not asked
    here - see :mod:`core.targeting.calls`, and the form, which is where
    somebody can still see what they typed.
    """


class PhoneNumberUnusable(TargetingError):
    """A number was given and it is not one that can be rung.

    Two ways, one silence. It may not parse into a dialable number at all,
    or it may be a perfectly good number **from the wrong country**: Meta
    states that *"the phone number included in Call to Action must be from
    the same country as the target audience"*, and states it as a
    limitation rather than as an error code - which is the shape of rule
    that is enforced by nobody and paid for by the advertiser.

    Carries what was read rather than a sentence. The screen needs to be
    able to say which country it found beside which one it expected; being
    told "wrong country" without either is being told to guess.
    """

    def __init__(self, *, found: str = "", expected: str = "") -> None:
        super().__init__(f"phone number is not dialable here: {found} != {expected}")
        self.found = found
        self.expected = expected


class NoInterestsChosen(TargetingError):
    """Nothing to target, and the provider was going to be asked anyway.

    Raised at launch time rather than at build time: the whole wizard works
    before any provider is connected, and at that point no interest can
    possibly carry a confirmed id yet.
    """


class LookalikeNotAllowed(TargetingError):
    """A campaign under a Special Ad Category names a lookalike audience.

    The provider lists *"Lookalike Audiences"* as **removed** for housing,
    employment and credit ads, and it does not refuse the ad set. It
    creates it, sets the campaign to ``WITH_ISSUES`` with code ``2909035``
    and delivers nothing - a failure whose whole explanation lives in the
    provider's own console, where this product's user never looks.

    So it is refused here instead, at the gate rather than at build time,
    for the reason every other rule in this file is: the review screen has
    to render in order for the choice to be correctable.

    Carries the names because the sentence needs them. An advertiser with
    four audiences is not helped by being told one of them is a problem.
    """

    def __init__(self, *, labels: tuple[str, ...] = ()) -> None:
        super().__init__(f"lookalike audiences are not available here: {labels}")
        self.labels = labels


class AudienceUnusable(TargetingError):
    """A chosen audience is one the provider will not deliver on.

    Too small, still being counted, or held for review. Refused rather than
    dropped, and that direction is the whole of the rule: an ad set built
    to reach a named list of people and sent without it reaches everybody
    the rest of the spec allows, which is a wider audience than anyone
    approved and costs the advertiser money to find out about.

    Waiting fixes most of these on its own, so the sentence the Django
    layer builds from this says which audience and points at the screen
    that says why.
    """

    def __init__(self, *, labels: tuple[str, ...] = ()) -> None:
        super().__init__(f"audiences not usable yet: {labels}")
        self.labels = labels


class CostCapTooLow(TargetingError):
    """The most-per-result figure leaves the daily budget nothing to pace with.

    Refused rather than corrected, which is the opposite of what
    ``validate_structure`` does to a radius or an age - and for the reason
    ``BudgetTooLow`` beside it is refused: both are arithmetic about
    somebody's money, and quietly raising a cap the owner typed would be
    deciding on their behalf how much they are willing to pay for a
    customer.

    The dangerous half is that the provider accepts this pair. An ad set
    with a cap it cannot pace against does not fail - it delivers to
    nobody, and reports no spend, no leads and no cost per lead, which is
    indistinguishable on every screen from a campaign that has not started.
    """

    def __init__(self, *, cap_minor: int, daily_minor: int, needed_minor: int) -> None:
        self.cap_minor = cap_minor
        self.daily_minor = daily_minor
        self.needed_minor = needed_minor
        super().__init__(
            f"a cap of {cap_minor} needs at least {needed_minor} a day, "
            f"not {daily_minor}"
        )
