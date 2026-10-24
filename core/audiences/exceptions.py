"""What can go wrong between a picker and a rule."""


class AudienceRuleError(Exception):
    """Base for everything this module raises."""


class SourceNotSupported(AudienceRuleError):
    """This provider builds no audience from this kind of source."""

    def __init__(self, *, kind: str) -> None:
        super().__init__(f"no audience can be built from {kind!r}")
        self.kind = kind


class ActionNotSupported(AudienceRuleError):
    """The source exists; this is not something it reports people doing."""

    def __init__(self, *, kind: str, action: str) -> None:
        super().__init__(f"{kind!r} does not report {action!r}")
        self.kind = kind
        self.action = action


class RetentionTooLong(AudienceRuleError):
    """The window asked for is longer than the provider will look back."""

    def __init__(self, *, kind: str, days: int, maximum: int) -> None:
        super().__init__(f"{kind!r} looks back at most {maximum} days, not {days}")
        self.kind = kind
        self.days = days
        self.maximum = maximum


class RetentionNotOffered(AudienceRuleError):
    """A window this product does not put in front of anybody."""

    def __init__(self, *, days: int) -> None:
        super().__init__(f"{days} is not one of the windows this product offers")
        self.days = days


class BreadthNotOffered(AudienceRuleError):
    """A width this product does not put in front of anybody."""

    def __init__(self, *, breadth: str) -> None:
        super().__init__(f"{breadth!r} is not one of the widths this product offers")
        self.breadth = breadth


class CountryUnknown(AudienceRuleError):
    """There is no country to build the audience inside."""

    def __init__(self, *, country: str) -> None:
        super().__init__(f"{country!r} is not a country an audience can be built in")
        self.country = country


__all__ = [
    "ActionNotSupported",
    "AudienceRuleError",
    "BreadthNotOffered",
    "CountryUnknown",
    "RetentionNotOffered",
    "RetentionTooLong",
    "SourceNotSupported",
]
