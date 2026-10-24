"""What can go wrong between an answer and a targeting spec."""


class TargetingError(Exception):
    """Base for everything this package raises."""


class CatalogError(TargetingError):
    """The preset catalogue is malformed. A deployment bug, not a user one."""

    def __init__(self, message: str, *, source: str = "") -> None:
        super().__init__(f"{source}: {message}" if source else message)
        self.source = source


class PresetNotFound(TargetingError):
    """No preset covers this category and goal."""

    def __init__(self, *, provider: str, category: str, goal: str) -> None:
        super().__init__(f"no preset for {provider} {category}/{goal}")
        self.provider = provider
        self.category = category
        self.goal = goal


class UnfilledTemplate(TargetingError):
    """A ``{...}`` survived rendering."""

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
    """Below what the provider will accept for this account."""

    def __init__(self, *, given_minor: int, minimum_minor: int, currency: str) -> None:
        super().__init__(f"{given_minor} < {minimum_minor} {currency}")
        self.given_minor = given_minor
        self.minimum_minor = minimum_minor
        self.currency = currency


class ConversionSourceMissing(TargetingError):
    """The goal optimises for a sale on the advertiser's own site, and
    nothing is reporting those sales."""


class DestinationLinkMissing(TargetingError):
    """The ad sends people to a website and nobody said which one."""


class PhoneNumberMissing(TargetingError):
    """The ad is a button that dials, and no number was given."""


class PhoneNumberUnusable(TargetingError):
    """A number was given and it is not one that can be rung."""

    def __init__(self, *, found: str = "", expected: str = "") -> None:
        super().__init__(f"phone number is not dialable here: {found} != {expected}")
        self.found = found
        self.expected = expected


class NoInterestsChosen(TargetingError):
    """Nothing to target, and the provider was going to be asked anyway."""


class LookalikeNotAllowed(TargetingError):
    """A campaign under a Special Ad Category names a lookalike audience."""

    def __init__(self, *, labels: tuple[str, ...] = ()) -> None:
        super().__init__(f"lookalike audiences are not available here: {labels}")
        self.labels = labels


class AudienceUnusable(TargetingError):
    """A chosen audience is one the provider will not deliver on."""

    def __init__(self, *, labels: tuple[str, ...] = ()) -> None:
        super().__init__(f"audiences not usable yet: {labels}")
        self.labels = labels


class CostCapTooLow(TargetingError):
    """The most-per-result figure leaves the daily budget nothing to pace with."""

    def __init__(self, *, cap_minor: int, daily_minor: int, needed_minor: int) -> None:
        self.cap_minor = cap_minor
        self.daily_minor = daily_minor
        self.needed_minor = needed_minor
        super().__init__(
            f"a cap of {cap_minor} needs at least {needed_minor} a day, "
            f"not {daily_minor}"
        )
